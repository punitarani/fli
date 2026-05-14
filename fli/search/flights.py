"""Flight search implementation.

This module provides the core flight search functionality, interfacing directly
with Google Flights' API to find available flights and their details.
"""

import json
import logging
from copy import deepcopy
from datetime import datetime
from typing import Any

from fli.core import extract_currency_from_price_token
from fli.models import (
    Airline,
    Airport,
    Amenities,
    FlightLeg,
    FlightResult,
    FlightSearchFilters,
    Layover,
)
from fli.models.google_flights.base import TripType
from fli.search.client import get_client

logger = logging.getLogger(__name__)


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

    def search(
        self,
        filters: FlightSearchFilters,
        top_n: int = 5,
        currency: str | None = None,
        language: str | None = None,
        country: str | None = None,
    ) -> list[FlightResult | tuple[FlightResult, ...]] | None:
        """Search for flights using the given FlightSearchFilters.

        Args:
            filters: Full flight search object including airports, dates, and preferences
            top_n: Number of flights to limit the return flight search to
            currency: Optional ISO 4217 currency code (e.g. ``"EUR"``) to bill prices in.
                When omitted, Google returns prices in the currency it picks from the
                request's IP / locale (usually USD).
            language: Optional BCP-47 language code (e.g. ``"en-GB"``) for the
                ``hl`` query parameter.
            country: Optional ISO 3166-1 alpha-2 country code (e.g. ``"GB"``) for
                the ``gl`` query parameter.

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
        url = _with_locale_params(self.BASE_URL, currency, language, country)

        try:
            response = self.client.post(
                url=url,
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
            flights = []
            for flight in flights_data:
                try:
                    flights.append(self._parse_flights_data(flight))
                except (AttributeError, KeyError, ValueError, TypeError) as e:
                    logger.debug("Skipping flight with unparseable data: %s", e)
                    continue

            if not flights:
                return None

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

            # Select each flight option and fetch the next leg
            flight_combos = []
            for selected_flight in flights[:top_n]:
                next_filters = deepcopy(filters)
                next_filters.flight_segments[selected_count].selected_flight = selected_flight
                next_results = self.search(
                    next_filters,
                    top_n=top_n,
                    currency=currency,
                    language=language,
                    country=country,
                )
                if next_results is not None:
                    for next_result in next_results:
                        if isinstance(next_result, tuple):
                            flight_combos.append((selected_flight,) + next_result)
                        else:
                            flight_combos.append((selected_flight, next_result))

            return flight_combos

        except Exception as e:
            raise Exception(f"Search failed: {str(e)}") from e

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_flights_data(data: list) -> FlightResult:
        """Parse a single raw flight row into a structured FlightResult.

        The row layout is documented in ``.reverse-eng/notes/response_map.md``.
        """
        detail = data[0]
        price, currency = SearchFlights._parse_price_info(data)

        raw_legs = detail[2] or []
        legs = [SearchFlights._parse_leg(fl) for fl in raw_legs]
        layovers = SearchFlights._derive_layovers(legs, detail) if len(legs) > 1 else None

        emissions = SearchFlights._parse_emissions(detail)
        primary_airline = SearchFlights._safe_airline(_safe_get(detail, 0))
        primary_airline_name = None
        names_field = _safe_get(detail, 1)
        if isinstance(names_field, list) and names_field:
            first = names_field[0]
            if isinstance(first, str):
                primary_airline_name = first

        return FlightResult(
            price=price,
            currency=currency,
            duration=detail[9],
            stops=max(len(legs) - 1, 0),
            legs=legs,
            layovers=layovers or None,
            co2_emissions_g=emissions["this_g"],
            co2_emissions_typical_g=emissions["typical_g"],
            co2_emissions_delta_pct=emissions["delta_pct"],
            emissions_tag=emissions["tag"],
            self_transfer=_as_bool(_safe_get(detail, 12)),
            mixed_cabin=_as_bool(_safe_get(data, 10)),
            primary_airline=primary_airline,
            primary_airline_name=primary_airline_name,
            booking_token=_as_str(_safe_get(data, 8)),
        )

    @staticmethod
    def _parse_leg(fl: list) -> FlightLeg:
        """Parse one leg array into a :class:`FlightLeg`."""
        airline_info = fl[22] or []
        airline = SearchFlights._safe_airline(_safe_get(airline_info, 0))
        flight_number = _as_str(_safe_get(airline_info, 1)) or ""

        # Operating carrier: when the marketing carrier and operator differ
        # Google fills airline_info[2] with the operating airline code.
        op_code = _safe_get(airline_info, 2)
        operating_airline = SearchFlights._safe_airline(op_code) if op_code else None

        amenities = SearchFlights._parse_amenities(_safe_get(fl, 12))
        aircraft = _as_str(_safe_get(fl, 17))
        legroom_short = _as_str(_safe_get(fl, 14))
        legroom_long = _as_str(_safe_get(fl, 30))
        overnight = _as_bool(_safe_get(fl, 19)) or False
        co2 = _safe_get(fl, 31)
        co2_emissions_g = co2 if isinstance(co2, int) and co2 >= 0 else None

        dep_airport = SearchFlights._parse_airport(fl[3])
        arr_airport = SearchFlights._parse_airport(fl[6])

        return FlightLeg(
            airline=airline,
            flight_number=flight_number,
            departure_airport=dep_airport,
            arrival_airport=arr_airport,
            departure_datetime=SearchFlights._parse_datetime(fl[20], fl[8]),
            arrival_datetime=SearchFlights._parse_datetime(fl[21], fl[10]),
            duration=fl[11],
            departure_airport_name=_as_str(_safe_get(fl, 4)),
            arrival_airport_name=_as_str(_safe_get(fl, 5)),
            operating_airline=operating_airline,
            operating_flight_number=None,
            aircraft=aircraft,
            legroom_short=legroom_short,
            legroom=legroom_long or legroom_short,
            amenities=amenities,
            overnight=overnight,
            co2_emissions_g=co2_emissions_g,
        )

    @staticmethod
    def _parse_amenities(slots: Any) -> Amenities | None:
        if not isinstance(slots, list) or not slots:
            return None
        # Slots positions inferred from comparison across many leg rows.
        # Tri-state: True / False / None.
        wifi = _as_bool(_safe_get(slots, 1))
        power = _as_bool(_safe_get(slots, 5))
        usb_power = _as_bool(_safe_get(slots, 9))
        on_demand_video = _as_bool(_safe_get(slots, 9))
        in_seat_video = None
        legroom_rating = _safe_get(slots, 11)
        if not isinstance(legroom_rating, int):
            legroom_rating = None
        if wifi is None and power is None and usb_power is None and legroom_rating is None:
            return None
        return Amenities(
            wifi=wifi,
            power=power,
            usb_power=usb_power,
            in_seat_video=in_seat_video,
            on_demand_video=on_demand_video,
            legroom_rating=legroom_rating,
        )

    @staticmethod
    def _parse_emissions(detail: list) -> dict[str, Any]:
        emissions_block = _safe_get(detail, 22)
        out: dict[str, Any] = {
            "this_g": None,
            "typical_g": None,
            "delta_pct": None,
            "tag": None,
        }
        if not isinstance(emissions_block, list):
            return out
        this_g = _safe_get(emissions_block, 7)
        typ_g = _safe_get(emissions_block, 8)
        delta = _safe_get(emissions_block, 3)
        tag_int = _safe_get(emissions_block, 11)

        if isinstance(this_g, int) and this_g >= 0:
            out["this_g"] = this_g
        if isinstance(typ_g, int) and typ_g >= 0:
            out["typical_g"] = typ_g
        if isinstance(delta, int):
            out["delta_pct"] = delta
        if tag_int in (1, 2, 3):
            out["tag"] = {1: "lower", 2: "typical", 3: "higher"}[tag_int]
        return out

    @staticmethod
    def _derive_layovers(legs: list[FlightLeg], detail: list) -> list[Layover]:
        """Compute layover objects from leg arrival/departure times.

        Falls back to Google's own ``detail[13]`` block when it exists for the
        layover airport name; durations are recomputed from leg timestamps for
        consistency.
        """
        if len(legs) < 2:
            return []
        layovers: list[Layover] = []
        # detail[13] is list of [mins, iata, iata, null, name, city, name, city] entries
        detail_block = _safe_get(detail, 13)
        if not isinstance(detail_block, list):
            detail_block = []
        for i in range(len(legs) - 1):
            prev = legs[i]
            nxt = legs[i + 1]
            wait = (nxt.departure_datetime - prev.arrival_datetime).total_seconds()
            delta_minutes = int(wait // 60)
            if delta_minutes < 0:
                delta_minutes = 0
            overnight = prev.arrival_datetime.date() != nxt.departure_datetime.date()
            change_of_airport = prev.arrival_airport != nxt.departure_airport
            layovers.append(
                Layover(
                    airport=prev.arrival_airport,
                    duration=delta_minutes,
                    overnight=overnight,
                    change_of_airport=change_of_airport,
                )
            )
        return layovers

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
    def _safe_airline(code: Any) -> Airline | None:
        """Parse an airline code defensively; return None when invalid/missing."""
        if not isinstance(code, str) or not code:
            return None
        try:
            return SearchFlights._parse_airline(code)
        except (AttributeError, IndexError):
            return None

    @staticmethod
    def _parse_airport(airport_code: str) -> Airport:
        """Convert airport code to Airport enum.

        Args:
            airport_code: Raw airport code from API

        Returns:
            Corresponding Airport enum value

        """
        return getattr(Airport, airport_code)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _safe_get(seq: Any, idx: int) -> Any:
    if isinstance(seq, list) and 0 <= idx < len(seq):
        return seq[idx]
    return None


def _as_bool(v: Any) -> bool | None:
    return v if isinstance(v, bool) else None


def _as_str(v: Any) -> str | None:
    return v if isinstance(v, str) and v else None


def _with_locale_params(
    url: str, currency: str | None, language: str | None, country: str | None
) -> str:
    """Append the optional ``curr``/``hl``/``gl`` query parameters to ``url``."""
    params: list[str] = []
    if currency:
        params.append(f"curr={currency.upper()}")
    if language:
        params.append(f"hl={language}")
    if country:
        params.append(f"gl={country.upper()}")
    if not params:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{'&'.join(params)}"
