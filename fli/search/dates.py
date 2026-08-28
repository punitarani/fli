"""Date-based flight search implementation for finding the cheapest dates to fly.

This module provides functionality to search for the cheapest flights across a date range.
It uses Google Flights' calendar view API to find the best prices for each date.
It is intended to be used for finding the cheapest dates to fly, not the cheapest flights.
"""

import logging
from copy import deepcopy
from datetime import datetime, timedelta

from pydantic import BaseModel

from fli.core import extract_currency_from_price_token
from fli.models import DateSearchFilters
from fli.models.google_flights.base import TripType
from fli.search._concurrency import parallel_map
from fli.search._decoders import parse_flight_row
from fli.search._tfs import build_tfs, extract_payload, page_url, unsupported_filters
from fli.search.client import get_client

logger = logging.getLogger(__name__)


class DatePrice(BaseModel):
    """Flight price for a specific date."""

    date: tuple[datetime] | tuple[datetime, datetime]
    price: float
    currency: str | None = None


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

    def search(
        self,
        filters: DateSearchFilters,
        currency: str | None = None,
        language: str | None = None,
        country: str | None = None,
    ) -> list[DatePrice] | None:
        """Search for flight prices across a date range and search parameters.

        Args:
            filters: Search parameters including date range, airports, and preferences
            currency: Optional ISO 4217 currency code (e.g. ``"EUR"``) to bill prices in.
            language: Optional BCP-47 language code passed via the ``hl`` URL param.
            country: Optional ISO 3166-1 alpha-2 country code passed via the ``gl`` URL param.

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
            return self._search_chunk(
                filters, currency=currency, language=language, country=country
            )

        # Build every chunk descriptor up front so the per-chunk requests
        # share no mutable state. This both enables parallel execution and
        # fixes a latent bug in the previous sequential version: each chunk
        # rewrote ``filters.flight_segments[*].travel_date`` in place, so
        # the second-and-later chunks had segment dates that no longer
        # matched ``current_from``.
        chunk_filters = self._build_chunk_filters(filters, from_date, to_date)

        chunk_results = parallel_map(
            lambda cf: self._search_chunk(
                cf, currency=currency, language=language, country=country
            ),
            chunk_filters,
        )

        all_results: list[DatePrice] = []
        for r in chunk_results:
            if r:
                all_results.extend(r)
        return all_results if all_results else None

    def _build_chunk_filters(
        self,
        filters: DateSearchFilters,
        from_date: datetime,
        to_date: datetime,
    ) -> list[DateSearchFilters]:
        """Split ``filters``' date range into independent per-chunk filter copies.

        The flight segments are deep-copied per chunk and their
        ``travel_date`` advanced by the chunk offset so each chunk
        represents a distinct, self-contained search.
        """
        chunks: list[DateSearchFilters] = []
        current_from = from_date
        chunk_index = 0
        while current_from <= to_date:
            current_to = min(current_from + timedelta(days=self.MAX_DAYS_PER_SEARCH - 1), to_date)
            segments = deepcopy(filters.flight_segments)
            if chunk_index > 0:
                shift = self.MAX_DAYS_PER_SEARCH * chunk_index
                for segment in segments:
                    segment.travel_date = (
                        datetime.strptime(segment.travel_date, "%Y-%m-%d") + timedelta(days=shift)
                    ).strftime("%Y-%m-%d")
            chunks.append(
                DateSearchFilters(
                    trip_type=filters.trip_type,
                    passenger_info=filters.passenger_info,
                    flight_segments=segments,
                    stops=filters.stops,
                    seat_type=filters.seat_type,
                    price_limit=filters.price_limit,
                    airlines=filters.airlines,
                    max_duration=filters.max_duration,
                    layover_restrictions=filters.layover_restrictions,
                    emissions=filters.emissions,
                    bags=filters.bags,
                    from_date=current_from.strftime("%Y-%m-%d"),
                    to_date=current_to.strftime("%Y-%m-%d"),
                    duration=filters.duration,
                )
            )
            current_from = current_to + timedelta(days=1)
            chunk_index += 1
        return chunks

    def _search_chunk(
        self,
        filters: DateSearchFilters,
        currency: str | None = None,
        language: str | None = None,
        country: str | None = None,
    ) -> list[DatePrice] | None:
        """Price every date in one chunk's range and return the cheapest per date.

        Google's ``GetCalendarGraph`` RPC used to hand back a whole date
        grid in one call, but it now requires a browser-signed
        ``x-goog-batchexecute-bgr`` header (see :mod:`fli.search._tfs`).
        The public search page has no such grid, so each date is priced by
        its own page fetch instead. The requests run concurrently under the
        shared rate limiter, so a 61-day chunk costs one round trip's
        latency plus the 10 req/sec drain, not 61 serial fetches.

        Args:
            filters: Search parameters including date range, airports, and preferences
            currency: Optional ISO 4217 currency code passed via the ``curr`` URL param.
            language: Optional BCP-47 language code passed via the ``hl`` URL param.
            country: Optional ISO 3166-1 alpha-2 country code passed via the ``gl`` URL param.

        Returns:
            List of DatePrice objects containing date and price pairs, or None if no results

        """
        dropped = unsupported_filters(filters)
        if dropped:
            logger.warning(
                "Filters not supported by the search-page transport, ignored: %s",
                ", ".join(dropped),
            )

        from_date = datetime.strptime(filters.from_date, "%Y-%m-%d")
        to_date = datetime.strptime(filters.to_date, "%Y-%m-%d")
        days = [
            from_date + timedelta(days=offset) for offset in range((to_date - from_date).days + 1)
        ]

        priced = parallel_map(
            lambda day: self._price_one_date(
                filters, day, currency=currency, language=language, country=country
            ),
            days,
        )
        results = [p for p in priced if p is not None]
        return results or None

    def _price_one_date(
        self,
        filters: DateSearchFilters,
        day: datetime,
        *,
        currency: str | None,
        language: str | None,
        country: str | None,
    ) -> DatePrice | None:
        """Return the cheapest itinerary price for one departure date."""
        dates = [day]
        if filters.trip_type == TripType.ROUND_TRIP:
            # ``duration`` is optional (its validator doesn't run on the
            # default), so fall back to the gap between the two segments —
            # which the filter model already keeps consistent with it.
            trip_days = filters.duration
            if trip_days is None:
                segments = filters.flight_segments
                trip_days = (segments[1].parsed_travel_date - segments[0].parsed_travel_date).days
            dates.append(day + timedelta(days=trip_days))
        travel_dates = [d.strftime("%Y-%m-%d") for d in dates]

        # A date sweep can straddle today, and past dates are simply not
        # bookable — skip them rather than letting the segment validator
        # abort the whole chunk.
        if day.date() < datetime.now().date():
            return None

        url = page_url(build_tfs(filters, travel_dates=travel_dates), currency, language, country)
        try:
            response = self.client.get(url, impersonate="chrome", allow_redirects=True)
            response.raise_for_status()
            payload = extract_payload(response.text)
        except Exception:  # noqa: BLE001 — one bad date must not sink the sweep
            logger.warning("Pricing %s failed", travel_dates[0], exc_info=True)
            return None
        if payload is None:
            return None

        prices = []
        for index in (2, 3):
            if index < len(payload) and isinstance(payload[index], list):
                for row in payload[index][0]:
                    try:
                        prices.append(parse_flight_row(row).price)
                    except (AttributeError, KeyError, ValueError, TypeError):
                        continue
        prices = [p for p in prices if p]
        if not prices:
            return None

        return DatePrice(
            date=tuple(dates),
            price=min(prices),
            currency=currency,
        )

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

    @staticmethod
    def __parse_currency(item: list[list] | list | None) -> str | None:
        """Parse the returned currency code from the API response."""
        try:
            if item and isinstance(item, list) and len(item) > 2:
                if isinstance(item[2], list) and len(item[2]) > 1:
                    return extract_currency_from_price_token(item[2][1])
        except (IndexError, TypeError, ValueError):
            pass

        return None
