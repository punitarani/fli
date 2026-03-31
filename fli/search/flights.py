"""Flight search implementation.

This module provides the core flight search functionality, interfacing directly
with Google Flights' API to find available flights and their details.
"""

import json
from copy import deepcopy
from datetime import datetime

from fli.core import (
    extract_currency_from_price_token,
)
from fli.models import (
    Airline,
    Airport,
    BookingOffer,
    FlightLeg,
    FlightResult,
    FlightSearchFilters,
    PassengerInfo,
    SeatType,
)
from fli.models.google_flights.base import TripType
from fli.search.booking_offers import (
    build_booking_f_req,
    build_booking_filter_block,
    parse_booking_results,
)
from fli.search.client import get_client


class SearchFlights:
    """Flight search implementation using Google Flights' API.

    This class handles searching for specific flights with detailed filters,
    parsing the results into structured data models.
    """

    BASE_URL = "https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/GetShoppingResults"
    BOOKING_URL = "https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/GetBookingResults"
    DEFAULT_HEADERS = {
        "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
    }

    def __init__(self):
        """Initialize the search client for flight searches."""
        self.client = get_client()

    def search(
        self, filters: FlightSearchFilters, top_n: int = 5
    ) -> list[FlightResult | tuple[FlightResult, FlightResult]] | None:
        """Search for flights using the given FlightSearchFilters.

        Args:
            filters: Full flight search object including airports, dates, and preferences
            top_n: Number of flights to limit the return flight search to

        Returns:
            List of FlightResult objects containing flight details, or None if no results

        Raises:
            Exception: If the search fails or returns invalid data

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

            # Select each flight option and fetch the next leg
            flight_combos = []
            for selected_flight in flights[:top_n]:
                next_filters = deepcopy(filters)
                next_filters.flight_segments[selected_count].selected_flight = selected_flight
                next_results = self.search(next_filters, top_n=top_n)
                if next_results is not None:
                    for next_result in next_results:
                        if isinstance(next_result, tuple):
                            flight_combos.append((selected_flight,) + next_result)
                        else:
                            flight_combos.append((selected_flight, next_result))

            return flight_combos

        except Exception as e:
            raise Exception(f"Search failed: {str(e)}") from e

    def get_booking_offers(
        self,
        itinerary: FlightResult | tuple[FlightResult, ...],
        *,
        passenger_info: PassengerInfo | None = None,
        cabin_class: SeatType = SeatType.ECONOMY,
    ) -> list[BookingOffer]:
        """Fetch booking offers for an exact found itinerary.

        Args:
            itinerary: A one-way `FlightResult` or the tuple returned for a
                round-trip or multi-city itinerary.
                For multi-leg itineraries, the booking token from the last
                flight is used for the booking lookup.
            passenger_info: Passenger configuration for the booking lookup.
                Defaults to `PassengerInfo(adults=1)` when omitted.
            cabin_class: Cabin class to include in the booking lookup request.

        Returns:
            A list of `BookingOffer` objects. Returns an empty list when the
            itinerary does not include a booking token.

        Raises:
            Exception: If the booking-offer lookup fails at any stage.

        """
        flights = list(itinerary) if isinstance(itinerary, tuple) else [itinerary]
        booking_token = next(
            (flight.booking_token for flight in reversed(flights) if flight.booking_token),
            None,
        )
        if not booking_token:
            return []

        try:
            filter_block = build_booking_filter_block(
                flights=flights,
                passenger_info=passenger_info or PassengerInfo(adults=1),
                cabin_class=cabin_class,
            )
            encoded_body = build_booking_f_req(
                booking_token=booking_token,
                filter_block=filter_block,
            )
            response = self.client.post(
                url=self.BOOKING_URL,
                data=f"f.req={encoded_body}",
                impersonate="chrome",
                allow_redirects=True,
            )
            response.raise_for_status()
            return parse_booking_results(response.text)
        except Exception as e:
            raise Exception(f"Booking offer lookup failed: {str(e)}") from e

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
            booking_token=SearchFlights._parse_booking_token(data),
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
    def _parse_price(data: list) -> float:
        """Extract the numeric price from raw flight data.

        Args:
            data: Raw flight data from the API response

        Returns:
            Flight price, or 0.0 if price data is unavailable

        """
        try:
            price_block = SearchFlights._get_price_block(data)
            if price_block and price_block[0]:
                return float(price_block[0][-1])
        except (IndexError, TypeError):
            pass
        return 0.0

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
    def _parse_booking_token(data: list) -> str | None:
        """Extract the booking token from a shopping result price block."""
        try:
            price_block = SearchFlights._get_price_block(data)
            if price_block and len(price_block) > 1 and isinstance(price_block[1], str):
                return price_block[1]
        except (IndexError, TypeError):
            pass
        return None

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
