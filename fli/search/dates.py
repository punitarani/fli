"""Date search implementation."""

import json
from datetime import datetime

from curl_cffi import requests
from pydantic import BaseModel
from ratelimit import limits, sleep_and_retry
from tenacity import retry, stop_after_attempt, wait_exponential

from fli.models import DateSearchFilters


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
        self._client = requests.Session()
        self._client.headers.update(self.DEFAULT_HEADERS)

    def __del__(self):
        """Cleanup client session."""
        if hasattr(self, "_client"):
            self._client.close()

    @sleep_and_retry
    @limits(calls=10, period=1)
    @retry(stop=stop_after_attempt(1), wait=wait_exponential(), reraise=True)
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

            data = json.loads(parsed)
            dates_data = [
                DatePrice(
                    date=datetime.strptime(item[0], "%Y-%m-%d"),
                    price=item[2][0][1],
                )
                for item in data[-1]
            ]
            return dates_data

        except Exception as e:
            raise Exception(f"Search failed: {str(e)}") from e
