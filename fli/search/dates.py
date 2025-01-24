"""Date-based flight search implementation for finding the cheapest dates to fly.

This module provides functionality to search for the cheapest flights across a date range.
It uses Google Flights' calendar view API to find the best prices for each date.
It is intended to be used for finding the cheapest dates to fly, not the cheapest flights.
"""

import json
from datetime import datetime, timedelta

from pydantic import BaseModel

from fli.models import DateSearchFilters
from fli.models.google_flights.base import TripType
from fli.search.client import get_client


class DatePrice(BaseModel):
    """Flight price for a specific date."""

    date: tuple[datetime] | tuple[datetime, datetime]
    price: float


class SearchDates:
    """Date-based flight search implementation.

    This class provides methods to search for flight prices across a date range,
    useful for finding the cheapest dates to fly.
    """

    BASE_URL = "https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/GetCalendarGraph"
    DEFAULT_HEADERS = {
        "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
    }
    MAX_DAYS_PER_SEARCH = 61

    def __init__(self):
        """Initialize the search client for date-based searches."""
        self.client = get_client()

    def search(self, filters: DateSearchFilters) -> list[DatePrice] | None:
        """Search for flight prices across a date range and search parameters.

        Args:
            filters: Search parameters including date range, airports, and preferences

        Returns:
            List of DatePrice objects containing date and price pairs, or None if no results

        Raises:
            Exception: If the search fails or returns invalid data

        Notes:
            - For date ranges larger than 61 days, splits into multiple searches.
            - We can't search more than 305 days in the future.

        """
        from_date = datetime.strptime(filters.from_date, "%Y-%m-%d")
        to_date = datetime.strptime(filters.to_date, "%Y-%m-%d")
        date_range = (to_date - from_date).days + 1

        if date_range <= self.MAX_DAYS_PER_SEARCH:
            return self._search_chunk(filters)

        # Split into chunks of MAX_DAYS_PER_SEARCH
        all_results = []
        current_from = from_date
        while current_from <= to_date:
            current_to = min(current_from + timedelta(days=self.MAX_DAYS_PER_SEARCH - 1), to_date)

            # Update the travel date for the flight segments
            if current_from > from_date:
                for segment in filters.flight_segments:
                    segment.travel_date = (
                        datetime.strptime(segment.travel_date, "%Y-%m-%d")
                        + timedelta(days=self.MAX_DAYS_PER_SEARCH)
                    ).strftime("%Y-%m-%d")

            # Create new filters for this chunk
            chunk_filters = DateSearchFilters(
                trip_type=filters.trip_type,
                passenger_info=filters.passenger_info,
                flight_segments=filters.flight_segments,
                stops=filters.stops,
                seat_type=filters.seat_type,
                airlines=filters.airlines,
                from_date=current_from.strftime("%Y-%m-%d"),
                to_date=current_to.strftime("%Y-%m-%d"),
                duration=filters.duration,
            )

            chunk_results = self._search_chunk(chunk_filters)
            if chunk_results:
                all_results.extend(chunk_results)

            current_from = current_to + timedelta(days=1)

        return all_results if all_results else None

    def _search_chunk(self, filters: DateSearchFilters) -> list[DatePrice] | None:
        """Search for flight prices for a single date range chunk.

        Args:
            filters: Search parameters including date range, airports, and preferences

        Returns:
            List of DatePrice objects containing date and price pairs, or None if no results

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

            data = json.loads(parsed)
            dates_data = [
                DatePrice(
                    date=self.__parse_date(item, filters.trip_type),
                    price=self.__parse_price(item),
                )
                for item in data[-1]
                if self.__parse_price(item)
            ]
            return dates_data

        except Exception as e:
            raise Exception(f"Search failed: {str(e)}") from e

    @staticmethod
    def __parse_date(
        item: list[list] | list | None, trip_type: TripType
    ) -> tuple[datetime] | tuple[datetime, datetime]:
        """Parse date data from the API response.

        Args:
            item: Raw date data from the API response
            trip_type: Trip type (one-way or round-trip)

        Returns:
            Tuple of datetime objects

        """
        if trip_type == TripType.ONE_WAY:
            return (datetime.strptime(item[0], "%Y-%m-%d"),)
        else:
            return (
                datetime.strptime(item[0], "%Y-%m-%d"),
                datetime.strptime(item[1], "%Y-%m-%d"),
            )

    @staticmethod
    def __parse_price(item: list[list] | list | None) -> float | None:
        """Parse price data from the API response.

        Args:
            item: Raw price data from the API response

        Returns:
            Float price value if valid, None if invalid or missing

        """
        try:
            if item and isinstance(item, list) and len(item) > 2:
                if isinstance(item[2], list) and len(item[2]) > 0:
                    if isinstance(item[2][0], list) and len(item[2][0]) > 1:
                        return float(item[2][0][1])
        except (IndexError, TypeError, ValueError):
            pass

        return None
