"""Flight search implementation.

This module provides the core flight search functionality, interfacing directly
with Google Flights' API to find available flights and their details.
"""

import json
from copy import deepcopy
from datetime import datetime

from fli.core import extract_currency_from_price_token
from fli.models import (
    Airline,
    Airport,
    FlightLeg,
    FlightResult,
    FlightSearchFilters,
)
from fli.models.google_flights.base import TripType
from fli.search.client import get_client


class SearchFlights:
    """Flight search implementation using Google Flights' API.

    This class handles searching for specific flights with detailed filters,
    parsing the results into structured data models.
    """

    BASE_URL = "https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/GetShoppingResults"
    DEFAULT_HEADERS = {
        "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
    }

    def __init__(self):
        """Initialize the search client for flight searches."""
        self.client = get_client()

    # For multi-leg queries Google's GetShoppingResults backend frequently
    # returns an HTTP 200 with an empty body on cold queries (server-side
    # ~60s timeout).  Retrying the same request often succeeds because the
    # session warms up — see the variance characterisation in the commit
    # that introduced this constant.  One extra attempt covers ~50% of
    # cold-path failures without pushing wall time past ~2 minutes.
    _EMPTY_RETRIES_MULTI_LEG = 1

    def _do_single_search(
        self, filters: FlightSearchFilters, *, include_metadata: bool = False
    ) -> list[FlightResult] | tuple[list[FlightResult], dict] | None:
        """Execute a single API call and return flight options for the current unselected leg.

        Args:
            filters: Full flight search object including airports, dates, and preferences
            include_metadata: If True, return (flights, metadata) with response-level
                data such as price_range.

        Returns:
            List of FlightResult, or (flights, metadata) tuple, or None if no results

        """
        # Multi-leg queries (round-trip and multi-city) hit a notably flakier
        # path on Google's backend.  One-way queries are reliable enough that
        # a retry just slows them down on legitimate "no flights" results.
        is_multi_leg = filters.trip_type != TripType.ONE_WAY
        max_attempts = 1 + (self._EMPTY_RETRIES_MULTI_LEG if is_multi_leg else 0)

        encoded_filters = filters.encode()
        decoded = None
        for attempt in range(max_attempts):
            response = self.client.post(
                url=self.BASE_URL,
                data=f"f.req={encoded_filters}",
                impersonate="chrome",
                allow_redirects=True,
            )
            response.raise_for_status()
            parsed = json.loads(response.text.lstrip(")]}'"))[0][2]
            if parsed:
                decoded = json.loads(parsed)
                break
            # Empty body — Google's backend timed out.  For multi-leg
            # requests we retry once; for one-way we accept the empty.
            if attempt + 1 < max_attempts:
                continue

        if decoded is None:
            return None

        flights_data = [
            item
            for i in [2, 3]
            if isinstance(decoded[i], list)
            for item in decoded[i][0]
        ]
        flights = [self._parse_flights_data(flight) for flight in flights_data]

        if not include_metadata:
            return flights

        metadata = {}
        try:
            if decoded[7] and len(decoded[7]) > 3 and isinstance(decoded[7][3], list):
                metadata["price_range"] = decoded[7][3]
        except (IndexError, TypeError):
            pass

        return flights, metadata

    def search(
        self, filters: FlightSearchFilters, top_n: int = 5
    ) -> list[FlightResult | tuple[FlightResult, ...]] | None:
        """Search for flights using the given FlightSearchFilters.

        Args:
            filters: Full flight search object including airports, dates, and preferences
            top_n: Number of flights to limit the return flight search to

        Returns:
            List of FlightResult objects (one-way), tuples of FlightResult (round-trip
            or multi-city), or None if no results

        Raises:
            Exception: If the search fails or returns invalid data

        Note:
            Multi-city searches (TripType.MULTI_CITY) with distinct city pairs may
            time out due to limitations of the Google Flights API endpoint.  The
            endpoint reliably supports one-way and round-trip searches.

        """
        encoded_filters = filters.encode()

        try:
            response = self.client.post(
                url=self.BASE_URL,
                data=f"f.req={encoded_filters}",
                impersonate="chrome",
                allow_redirects=True,
            )
            response.raise_for_status()

            parsed = json.loads(response.text.lstrip(")]}'"))[0][2]
            if not parsed:
                return None

            encoded_filters = json.loads(parsed)
            flights_data = [
                item
                for i in [2, 3]
                if isinstance(encoded_filters[i], list)
                for item in encoded_filters[i][0]
            ]
            flights = [self._parse_flights_data(flight) for flight in flights_data]

            if filters.trip_type == TripType.ONE_WAY:
                return flights

            # For round-trip and multi-city, iteratively select each leg
            # and fetch the next leg's options with combined pricing.
            num_segments = len(filters.flight_segments)
            selected_count = sum(
                1 for s in filters.flight_segments if s.selected_flight is not None
            )

            # If all previous segments are selected, we're on the last leg
            if selected_count >= num_segments - 1:
                return flights

            # Select each flight option and fetch the next leg.
            #
            # Multi-city continuation calls hit Google Flights'
            # ``GetShoppingResults`` endpoint with ``selected_flight`` set,
            # which is intermittently slow.  Without per-iteration timeout
            # handling, a single slow continuation kills the entire outer
            # search — meaning a 4-leg trip with one flaky branch returns
            # zero combos instead of the 4 that actually completed.  Treat
            # timeouts as "this branch is unavailable right now" and keep
            # whatever combos succeeded.  Non-timeout errors still bubble
            # up so real bugs aren't swallowed.
            flight_combos = []
            timeout_skipped = 0
            for selected_flight in flights[:top_n]:
                next_filters = deepcopy(filters)
                next_filters.flight_segments[selected_count].selected_flight = selected_flight
                try:
                    next_results = self.search(next_filters, top_n=top_n)
                except Exception as inner:
                    msg = str(inner).lower()
                    if "timed out" in msg or "curl: (28)" in msg:
                        timeout_skipped += 1
                        continue
                    raise
                if next_results is not None:
                    for next_result in next_results:
                        if isinstance(next_result, tuple):
                            flight_combos.append((selected_flight,) + next_result)
                        else:
                            flight_combos.append((selected_flight, next_result))

            # If every continuation timed out and we have nothing to
            # return, surface the timeout so callers (notably the MCP
            # layer) can classify it correctly instead of reporting a
            # misleading "no flights" outcome.
            if timeout_skipped > 0 and not flight_combos:
                raise Exception(
                    f"All {timeout_skipped} multi-city continuation calls"
                    " timed out on the Google Flights API. Retry the search."
                )

            return flight_combos

        except Exception as e:
            raise Exception(f"Search failed: {str(e)}") from e

    @staticmethod
    def _parse_flights_data(data: list) -> FlightResult:
        """Parse raw flight data into a structured FlightResult.

        Args:
            data: Raw flight data from the API response

        Returns:
            Structured FlightResult object with all flight details

        """
        price, currency = SearchFlights._parse_price_info(data)
        flight = FlightResult(
            price=price,
            currency=currency,
            duration=data[0][9],
            stops=len(data[0][2]) - 1,
            legs=[
                FlightLeg(
                    airline=SearchFlights._parse_airline(fl[22][0]),
                    flight_number=fl[22][1],
                    departure_airport=SearchFlights._parse_airport(fl[3]),
                    arrival_airport=SearchFlights._parse_airport(fl[6]),
                    departure_datetime=SearchFlights._parse_datetime(fl[20], fl[8]),
                    arrival_datetime=SearchFlights._parse_datetime(fl[21], fl[10]),
                    duration=fl[11],
                )
                for fl in data[0][2]
            ],
        )
        return flight

    @staticmethod
    def _parse_price_info(data: list) -> tuple[float, str | None]:
        """Extract the numeric price and returned currency from raw flight data."""
        price_block = SearchFlights._get_price_block(data)
        price = 0.0
        currency = None
        try:
            if price_block and price_block[0]:
                price = float(price_block[0][-1])
        except (IndexError, TypeError):
            pass
        try:
            if price_block and len(price_block) > 1:
                currency = extract_currency_from_price_token(price_block[1])
        except (IndexError, TypeError):
            pass
        return price, currency

    @staticmethod
    def _parse_currency(data: list) -> str | None:
        """Extract the returned currency code from raw flight data."""
        try:
            price_block = SearchFlights._get_price_block(data)
            if price_block and len(price_block) > 1:
                return extract_currency_from_price_token(price_block[1])
        except (IndexError, TypeError):
            pass
        return None

    @staticmethod
    def _get_price_block(data: list) -> list | None:
        """Return the raw price block attached to a flight row."""
        try:
            if len(data) > 1 and isinstance(data[1], list):
                return data[1]
        except TypeError:
            pass
        return None

    @staticmethod
    def _parse_datetime(date_arr: list[int], time_arr: list[int]) -> datetime:
        """Convert date and time arrays to datetime.

        Args:
            date_arr: List of integers [year, month, day]
            time_arr: List of integers [hour, minute]

        Returns:
            Parsed datetime object

        Raises:
            ValueError: If arrays contain only None values

        """
        if not any(x is not None for x in date_arr) or not any(x is not None for x in time_arr):
            raise ValueError("Date and time arrays must contain at least one non-None value")

        return datetime(*(x or 0 for x in date_arr), *(x or 0 for x in time_arr))

    @staticmethod
    def _parse_airline(airline_code: str) -> Airline:
        """Convert airline code to Airline enum.

        Args:
            airline_code: Raw airline code from API

        Returns:
            Corresponding Airline enum value

        """
        if airline_code[0].isdigit():
            airline_code = f"_{airline_code}"
        return getattr(Airline, airline_code)

    @staticmethod
    def _parse_airport(airport_code: str) -> Airport:
        """Convert airport code to Airport enum.

        Args:
            airport_code: Raw airport code from API

        Returns:
            Corresponding Airport enum value

        """
        return getattr(Airport, airport_code)
