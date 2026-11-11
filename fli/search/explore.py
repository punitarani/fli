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

Same-origin signals (``x-same-domain`` / ``origin``) are required. Locale
parameters (``curr``, ``hl``, ``gl``) use the shared URL builder and the
shared client supplies the regional consent cookie.
"""

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
from fli.search.exceptions import SearchParseError


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
            SearchRejectedError: Google rejected the RPC (including error 13).
            SearchParseError: The response contained no usable destination records.

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
            raise SearchParseError(
                "Explore search returned no parseable destination records. Google may "
                "have changed the response shape or served a blocked/consent response."
            )

        return merge_explore_payloads(meta, destinations, prices)
