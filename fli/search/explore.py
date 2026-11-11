"""Google Flights Explore search implementation.

Explore answers "where can I fly cheaply?" — one request returns dozens of
destinations (each with its cheapest found fare) for an origin and a broad
destination such as :attr:`fli.models.ExploreRegion.ANYWHERE` or a continent.

The RPC has intermittently returned Google's payload-less error-13 envelope
since 2026-09. Live checks on 2026-11-11 returned priced destinations for
LHR to Anywhere and JFK to Europe with the request below. Unlike the flight
search page, the public Explore page currently embeds only configuration
and locale data, not destination or fare records, so it is not a replacement
transport. Rejections propagate as SearchRejectedError; missing destination
records raise SearchParseError instead of masquerading as an empty search.

Live checks on 2026-11-11 measured error 13 on roughly 40% of identical
requests, arriving fast (~0.2 s) and in clusters, while every other request
succeeded. So error 13 here is treated as transient: :meth:`SearchExplore.search`
retries it a few times with a short backoff, and if every attempt is refused it
raises a ``SearchRejectedError`` marked ``retryable``. Error 3
(``INVALID_ARGUMENT``) is Google refusing the request itself and is never
retried.

Same-origin signals (``x-same-domain`` / ``origin``) are required. Locale
parameters (``curr``, ``hl``, ``gl``) use the shared URL builder and the
shared client supplies the regional consent cookie.
"""

import logging
import time

from fli.models import ExplorePlace, ExploreResult, ExploreSearchFilters
from fli.search._decoders import (
    is_explore_destinations_chunk,
    is_explore_prices_chunk,
    merge_explore_payloads,
    parse_explore_destinations_chunk,
    parse_explore_prices_chunk,
)
from fli.search._urls import with_locale_params
from fli.search._wire import iter_wrb_chunks
from fli.search.client import get_client
from fli.search.exceptions import SearchParseError, SearchRejectedError

logger = logging.getLogger(__name__)

# Error 13 attempts per search and the pause before each retry, in seconds.
# Refusals cluster, so the pauses grow; the worst case adds ~6 s to a search.
EXPLORE_ATTEMPTS = 4
EXPLORE_RETRY_BACKOFF = (1.0, 2.0, 3.0)

_INTERMITTENT_HINT = (
    "Explore refuses a share of requests intermittently (about 40% in live checks "
    "on 2026-11-11); this one was refused on every attempt. Retry after a few seconds."
)


class SearchExplore:
    """Explore search: one origin, a broad destination, many priced results."""

    BASE_URL = "https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/GetExploreDestinations"
    DEFAULT_HEADERS = {
        "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
        # Same-origin signals — required by this endpoint (see module docstring).
        "x-same-domain": "1",
        "origin": "https://www.google.com",
    }

    def __init__(self):
        """Initialize the search client for explore searches."""
        self.client = get_client()

    def search(
        self,
        filters: ExploreSearchFilters,
        currency: str | None = None,
        language: str | None = None,
        country: str | None = None,
    ) -> ExploreResult:
        """Search destinations and prices for an Explore query.

        Args:
            filters: Explore search parameters (origin, destination region, date, ...)
            currency: Optional ISO 4217 currency code passed via the ``curr`` URL param.
            language: Optional BCP-47 language code passed via the ``hl`` URL param.
            country: Optional ISO 3166-1 alpha-2 country code passed via the ``gl`` URL param.

        Returns:
            An :class:`ExploreResult` with one entry per destination (price fields
            are None for destinations Google returned without a fare).

        Raises:
            SearchRejectedError: Google rejected the RPC. Error 13 is retried
                ``EXPLORE_ATTEMPTS`` times first and is raised with
                ``retryable=True``; other codes are raised at once.
            SearchParseError: The response contained no usable destination records.

        """
        encoded_filters = filters.encode()
        url = with_locale_params(self.BASE_URL, currency, language, country)

        for attempt in range(1, EXPLORE_ATTEMPTS + 1):
            try:
                return self._search_once(filters, url, encoded_filters, currency)
            except SearchRejectedError as exc:
                if exc.code != 13:
                    raise
                if attempt == EXPLORE_ATTEMPTS:
                    raise SearchRejectedError(
                        exc.code, detail=exc.detail, hint=_INTERMITTENT_HINT, retryable=True
                    ) from exc
                delay = EXPLORE_RETRY_BACKOFF[min(attempt, len(EXPLORE_RETRY_BACKOFF)) - 1]
                logger.info(
                    "Explore request refused with error 13 (attempt %d of %d); retrying in %.0fs",
                    attempt,
                    EXPLORE_ATTEMPTS,
                    delay,
                )
                time.sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    def _search_once(
        self,
        filters: ExploreSearchFilters,
        url: str,
        encoded_filters: str,
        currency: str | None,
    ) -> ExploreResult:
        """Send one Explore request and parse the response."""
        response = self.client.post(
            url=url,
            data=f"f.req={encoded_filters}",
            impersonate="chrome",
            allow_redirects=True,
            headers=self.DEFAULT_HEADERS,
        )
        response.raise_for_status()

        # Destination and price records stream across MANY wrb.fr chunks in
        # no guaranteed order (24 chunks observed for large regions), so
        # classify every chunk by shape and accumulate before joining.
        meta: dict = {}
        destinations: list = []
        prices: dict = {}
        for chunk in iter_wrb_chunks(response.text):
            if is_explore_destinations_chunk(chunk):
                chunk_meta, chunk_destinations = parse_explore_destinations_chunk(chunk)
                for key, value in chunk_meta.items():
                    if meta.get(key) is None:
                        meta[key] = value
                destinations.extend(chunk_destinations)
            if is_explore_prices_chunk(chunk):
                prices.update(parse_explore_prices_chunk(chunk, default_currency=currency))

        if not destinations:
            message = (
                "Explore search returned no parseable destination records. Google may "
                "have changed the response shape or served a blocked/consent response."
            )
            if isinstance(filters.destination, ExplorePlace):
                # Live checks: a city mid sent as the destination returns an
                # empty body like this one, while region and country mids work.
                message += (
                    f" The destination mid {filters.destination.mid!r} may also be a city; "
                    "Explore only answers for region, continent or country mids."
                )
            raise SearchParseError(message)

        return merge_explore_payloads(meta, destinations, prices)
