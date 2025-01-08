"""Flight search implementation.

This module provides the core flight search functionality, interfacing directly
with Google Flights' API to find available flights and their details.

Currently only supports one-way flights.
"""

import json
from datetime import datetime

from pydantic import BaseModel

from fli.models import (
    Airline,
    Airport,
    FlightLeg,
    FlightResult,
    FlightSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
)
from fli.search.client import get_client


class SearchFlightsFilters(BaseModel):
    """Simplified search filters for flight searches.

    This model provides a simpler interface compared to the full FlightSearchFilters,
    focusing on the most common search parameters.

    Attributes:
        departure_airport: Origin airport
        arrival_airport: Destination airport
        departure_date: Date in YYYY-MM-DD format
        passenger_info: Passenger configuration (defaults to 1 adult)
        seat_type: Cabin class (defaults to economy)
        stops: Maximum stops allowed (defaults to any)
        sort_by: Sort criteria (defaults to cheapest)

    """

    departure_airport: Airport
    arrival_airport: Airport
    departure_date: str
    passenger_info: PassengerInfo = PassengerInfo(adults=1)
    seat_type: SeatType = SeatType.ECONOMY
    stops: MaxStops = MaxStops.ANY
    sort_by: SortBy = SortBy.CHEAPEST


class SearchFlights:
    """Flight search implementation using Google Flights' API.

    This class handles searching for specific flights with detailed filters,
    parsing the results into structured data models.

    Currently only supports one-way flights.
    """

    BASE_URL = "https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/GetShoppingResults"
    DEFAULT_HEADERS = {
        "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
    }

    def __init__(self):
        """Initialize the search client for flight searches."""
        self.client = get_client()

    def search(self, filters: SearchFlightsFilters) -> list[FlightResult] | None:
        """Search for flights using the provided filters.

        Args:
            filters: Search parameters including airports, dates, and preferences

        Returns:
            List of FlightResult objects containing flight details, or None if no results

        Raises:
            Exception: If the search fails or returns invalid data

        """
        search_filters = self._create_flight_search_data(filters)
        encoded_filters = search_filters.encode()

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
            return flights

        except Exception as e:
            raise Exception(f"Search failed: {str(e)}") from e

    @staticmethod
    def _create_flight_search_data(params: SearchFlightsFilters) -> FlightSearchFilters:
        """Convert simplified filters to full API filters.

        Args:
            params: Simplified search parameters

        Returns:
            Complete FlightSearchFilters object ready for API use

        """
        return FlightSearchFilters(
            passenger_info=params.passenger_info,
            flight_segments=[
                FlightSegment(
                    departure_airport=[[params.departure_airport, 0]],
                    arrival_airport=[[params.arrival_airport, 0]],
                    travel_date=params.departure_date,
                )
            ],
            stops=params.stops,
            seat_type=params.seat_type,
            sort_by=params.sort_by,
        )

    @staticmethod
    def _parse_flights_data(data: list) -> FlightResult:
        """Parse raw flight data into a structured FlightResult.

        Args:
            data: Raw flight data from the API response

        Returns:
            Structured FlightResult object with all flight details

        """
        flight = FlightResult(
            price=data[1][0][-1],
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
