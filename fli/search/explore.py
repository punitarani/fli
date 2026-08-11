"""Google Flights Explore search implementation.

Explore answers "where can I fly cheaply?" — one request returns dozens of
destinations (each with its cheapest found fare) for an origin and a broad
destination such as :attr:`fli.models.ExploreRegion.ANYWHERE` or a continent.

Request recipe (probed live via ``scripts/probe_explore.py``, 2026-08):
unlike the sibling endpoints, ``GetExploreDestinations`` enforces a
same-origin check — at least one of ``x-same-domain`` / ``origin`` /
``referer`` must be present or every request fails with an opaque ``wrb.fr``
error ``[13]``. Nothing else from the browser's ceremony is needed: no
cookies, no ``at`` XSRF token, no ``f.sid``/``bl``/``soc-*``/``rt=c`` query
params, and the ``curr=``/``hl=``/``gl=`` locale params work as on every
other endpoint. Escalation ladder should this break in future:

1. current shape (``x-same-domain: 1`` + ``origin`` headers)
2. add ``referer: https://www.google.com/travel/explore``
3. add ``soc-app=162&soc-platform=1&soc-device=1&rt=c`` query params
4. currency via ``x-goog-ext-259736195-jspb: [hl, gl, curr, 1, null,
   [tz_minutes], null, null, 1, []]`` if ``curr=`` stops working
5. priming ``GET /travel/explore`` to harvest cookies + the ``SNlM0e``
   (``at``) token from ``WIZ_global_data``
"""

import logging

from fli.models import ExploreResult, ExploreSearchFilters
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

logger = logging.getLogger(__name__)


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
    ) -> ExploreResult | None:
        """Search destinations and prices for an Explore query.

        Args:
            filters: Explore search parameters (origin, destination region, date, ...)
            currency: Optional ISO 4217 currency code passed via the ``curr`` URL param.
            language: Optional BCP-47 language code passed via the ``hl`` URL param.
            country: Optional ISO 3166-1 alpha-2 country code passed via the ``gl`` URL param.

        Returns:
            An :class:`ExploreResult` with one entry per destination (price fields
            are None for destinations Google returned without a fare), or None if
            the response could not be parsed.

        """
        encoded_filters = filters.encode()
        url = with_locale_params(self.BASE_URL, currency, language, country)

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
            logger.warning("Explore search returned no parseable destination chunks")
            return None

        return merge_explore_payloads(meta, destinations, prices)
