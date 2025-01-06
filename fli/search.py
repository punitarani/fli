import json
from datetime import datetime
from typing import Dict, List

from curl_cffi import requests
from pydantic import BaseModel
from ratelimit import limits, sleep_and_retry
from tenacity import retry, stop_after_attempt, wait_exponential

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


class SearchFilters(BaseModel):
    departure_airport: Airport
    arrival_airport: Airport
    departure_date: str
    passenger_info: PassengerInfo = PassengerInfo(adults=1)
    seat_type: SeatType = SeatType.ECONOMY
    stops: MaxStops = MaxStops.ANY
    sort_by: SortBy = SortBy.CHEAPEST


class Search:
    """Flight search implementation."""

    BASE_URL = "https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/GetShoppingResults"
    DEFAULT_HEADERS = {
        "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
    }

    def __init__(self):
        """Initialize the search client."""
        self._client = requests.Session()
        self._client.headers.update(self.DEFAULT_HEADERS)

    def __del__(self):
        """Cleanup client session."""
        if hasattr(self, "_client"):
            self._client.close()

    def _create_flight_search_data(self, params: SearchFilters) -> FlightSearchFilters:
        """
        Helper function to convert from our simpler param model to the existing FlightSearchFilters model.
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

    @sleep_and_retry
    @limits(calls=10, period=1)
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(), reraise=True)
    def search(self, filters: SearchFilters) -> List[FlightResult] | None:
        """
        Perform the flight search using the new simplified parameters.
        """
        search_filters = self._create_flight_search_data(filters)
        encoded_filters = search_filters.encode()

        try:
            response = self._client.post(
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
    def _parse_flights_data(data: List) -> FlightResult:
        flight = FlightResult(
            price=data[1][0][-1],
            duration=data[0][9],
            stops=len(data[0][2]) - 1,
            legs=[
                FlightLeg(
                    airline=Search._parse_airline(fl[22][0]),
                    flight_number=fl[22][1],
                    departure_airport=Search._parse_airport(fl[3]),
                    arrival_airport=Search._parse_airport(fl[6]),
                    departure_datetime=Search._parse_datetime(fl[20], fl[8]),
                    arrival_datetime=Search._parse_datetime(fl[21], fl[10]),
                    duration=fl[11],
                )
                for fl in data[0][2]
            ],
        )
        return flight

    @staticmethod
    def _parse_datetime(date_arr: List[int], time_arr: List[int]) -> datetime:
        """
        Convert date and time arrays to datetime.

        Args:
            date_arr: List of integers representing the date. Ex: [2025, 1, 1] (year, month, day)
            time_arr: List of integers representing the time. Ex: [13, 45] (hour, minute)

        Returns:
            datetime: The parsed datetime object.

        Note:
            date and time arrays can contain None values to represent 0.
        """
        # Raise error if either date or time arrays are empty, or contain only None values
        if not any(x is not None for x in date_arr) or not any(x is not None for x in time_arr):
            raise ValueError("Date and time arrays must contain at least one non-None value")

        return datetime(*(x or 0 for x in date_arr), *(x or 0 for x in time_arr))

    @staticmethod
    def _parse_airline(airline_code: str) -> Airline:
        """
        Parse the airline code to the corresponding Airline enum.
        """
        if airline_code[0].isdigit():
            airline_code = f"_{airline_code}"
        return getattr(Airline, airline_code)

    @staticmethod
    def _parse_airport(airport_code: str) -> Airport:
        """
        Parse the airport code to the corresponding Airport enum.
        """
        return getattr(Airport, airport_code)
