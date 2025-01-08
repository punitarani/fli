"""Date-based flight search implementation for finding the cheapest dates to fly.

This module provides functionality to search for the cheapest flights across a date range.
It uses Google Flights' calendar view API to find the best prices for each date.
It is intended to be used for finding the cheapest dates to fly, not the cheapest flights.

Currently only supports one-way flights.
"""

import json
from datetime import datetime

from pydantic import BaseModel

from fli.models import DateSearchFilters
from fli.search.client import get_client


class DatePrice(BaseModel):
    """Flight price for a specific date."""

    date: datetime
    price: float


class SearchDates:
    """Date-based flight search implementation.

    This class provides methods to search for flight prices across a date range,
    useful for finding the cheapest dates to fly.
    """

    BASE_URL = "https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/GetCalendarGrid"
    DEFAULT_HEADERS = {
        "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
    }

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
                    date=datetime.strptime(item[0], "%Y-%m-%d"),
                    price=self.__parse_price(item),
                )
                for item in data[-1]
                if self.__parse_price(item)
            ]
            return dates_data

        except Exception as e:
            raise Exception(f"Search failed: {str(e)}") from e

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
