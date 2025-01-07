"""Date search implementation."""

import json
from datetime import datetime

from pydantic import BaseModel

from fli.models import DateSearchFilters
from fli.search.client import get_client


class DatePrice(BaseModel):
    date: datetime
    price: float


class SearchDates:
    """Date search implementation."""

    BASE_URL = "https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/GetCalendarGrid"
    DEFAULT_HEADERS = {
        "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
    }

    def __init__(self):
        """Initialize the search client."""
        self.client = get_client()

    def search(self, filters: DateSearchFilters) -> list[DatePrice] | None:
        """
        Perform the date search using the search parameters.

        Args:
            filters: The search filters to use.

        Returns:
            A list of DatePrice objects containing date and price pairs, or None if no results found.
        """
        encoded_filters = filters.encode()

        try:
            # Debugging
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
        """Parse the price string safely."""
        try:
            if item and isinstance(item, list) and len(item) > 2:
                if isinstance(item[2], list) and len(item[2]) > 0:
                    if isinstance(item[2][0], list) and len(item[2][0]) > 1:
                        return float(item[2][0][1])
        except (IndexError, TypeError, ValueError):
            pass

        return None
