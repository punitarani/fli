"""Flight search orchestrator.

A thin wrapper around the FlightsFrontendService's ``GetShoppingResults``
and ``GetBookingResults`` endpoints. Response decoding lives in
:mod:`fli.search._decoders`; wire framing lives in :mod:`fli.search._wire`;
URL parameter construction lives in :mod:`fli.search._urls`.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from copy import deepcopy

from fli.models import (
    BookingOption,
    FlightResult,
    FlightSearchFilters,
)
from fli.models.google_flights.base import TripType
from fli.search._decoders import (
    _try_parse_booking_row,  # noqa: F401 — back-compat re-export for tests
    parse_booking_chunk,
    parse_flight_row,
)
from fli.search._urls import with_locale_params
from fli.search._urls import with_locale_params as _with_locale_params  # noqa: F401
from fli.search._wire import iter_wrb_chunks
from fli.search.client import get_client

logger = logging.getLogger(__name__)


class SearchFlights:
    """Flight search via Google Flights' FlightsFrontendService API.

    Public surface:

    - :meth:`search` — issue a GetShoppingResults call and return the
      parsed flights.
    - :meth:`get_booking_options` — follow up with GetBookingResults to
      surface bookable fares for a selected itinerary. See the method
      docstring for the live-token limitation.
    """

    BASE_URL = (
        "https://www.google.com/_/FlightsFrontendUi/data/"
        "travel.frontend.flights.FlightsFrontendService/GetShoppingResults"
    )
    BOOKING_URL = (
        "https://www.google.com/_/FlightsFrontendUi/data/"
        "travel.frontend.flights.FlightsFrontendService/GetBookingResults"
    )
    DEFAULT_HEADERS = {
        "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
    }

    def __init__(self):
        """Initialize the search client."""
        self.client = get_client()

    # ------------------------------------------------------------------
    # Public search API
    # ------------------------------------------------------------------

    def search(
        self,
        filters: FlightSearchFilters,
        top_n: int = 5,
        currency: str | None = None,
        language: str | None = None,
        country: str | None = None,
    ) -> list[FlightResult | tuple[FlightResult, ...]] | None:
        """Search for flights using the given :class:`FlightSearchFilters`.

        Args:
            filters: Full search descriptor (airports, dates, preferences).
            top_n: Number of outbound options to expand when chasing a
                round-trip or multi-city itinerary.
            currency: Optional ISO 4217 currency code (``curr`` URL param).
            language: Optional BCP-47 language code (``hl`` URL param).
            country: Optional ISO 3166-1 alpha-2 country code (``gl`` URL param).

        Returns:
            For one-way trips, a list of :class:`FlightResult`. For
            round-trip / multi-city, a list of tuples of
            :class:`FlightResult` (one per segment, in order). ``None``
            when no results.

        Raises:
            Exception: HTTP failure or unparseable response.

        """
        encoded = filters.encode()
        url = with_locale_params(self.BASE_URL, currency, language, country)

        try:
            response = self.client.post(
                url=url,
                data=f"f.req={encoded}",
                impersonate="chrome",
                allow_redirects=True,
            )
            response.raise_for_status()

            parsed = json.loads(response.text.lstrip(")]}'"))[0][2]
            if not parsed:
                return None
            inner = json.loads(parsed)
            flights_raw = [
                item
                for i in (2, 3)
                if isinstance(inner[i], list)
                for item in inner[i][0]
            ]
            flights: list[FlightResult] = []
            for row in flights_raw:
                try:
                    flights.append(parse_flight_row(row))
                except (AttributeError, KeyError, ValueError, TypeError) as e:
                    logger.debug("Skipping flight with unparseable data: %s", e)

            if not flights:
                return None
            if filters.trip_type == TripType.ONE_WAY:
                return flights
            return self._expand_multi_leg(
                flights,
                filters,
                top_n=top_n,
                currency=currency,
                language=language,
                country=country,
            )
        except Exception as e:
            raise Exception(f"Search failed: {str(e)}") from e

    def get_booking_options(
        self,
        flight: FlightResult | tuple[FlightResult, ...],
        filters: FlightSearchFilters,
        currency: str | None = None,
        language: str | None = None,
        country: str | None = None,
        booking_token: str | None = None,
        session_id: str | None = None,
    ) -> list[BookingOption]:
        """Fetch bookable fare options for a selected itinerary.

        ⚠️  KNOWN LIMITATION (May 2026): GetBookingResults at outer[0][1]
        wants a server-generated protobuf token that bundles the shopping
        session id with the selected airline+flight pair and currency
        metadata. The per-flight ``booking_token`` (``f0[8]``) from
        :meth:`search` is *not* the same token, so live calls usually
        return Google's ``ErrorResponse`` (INVALID_ARGUMENT). The parser
        path is fully validated against a captured response — pass an
        externally-captured token via ``booking_token`` to use it.

        Args:
            flight: A :class:`FlightResult` or tuple of results from
                :meth:`search`.
            filters: The same filters used in the preceding :meth:`search`
                call. A copy is made internally; caller filters are not
                mutated.
            currency: Optional ISO 4217 currency code.
            language: Optional BCP-47 language code.
            country: Optional ISO 3166-1 alpha-2 country code.
            booking_token: Explicit override for outer[0][1].
            session_id: Server-generated session token (extracted from the
                booking page's ``tfu`` URL parameter). When provided and
                ``booking_token`` is None, the protobuf token is
                constructed from the flight's metadata + this session id.

        Returns:
            A list of :class:`BookingOption` (empty list when Google
            returns no vendors or rejects the request).

        Raises:
            ValueError: No token available.
            Exception: HTTP request failure.

        """
        results: list[FlightResult] = list(flight) if isinstance(flight, tuple) else [flight]
        if not results:
            raise ValueError("flight argument must be a FlightResult or non-empty tuple of them")

        # Construct the booking token from session_id + flight metadata when
        # the caller supplies the session id (extracted client-side from the
        # `tfu` URL parameter, since the search-response session id is not
        # the same as the one Google's booking page uses).
        token = booking_token
        if token is None and session_id:
            from fli.search._proto import build_booking_token

            last = results[-1]
            last_leg = last.legs[-1]
            token = build_booking_token(
                session_id=session_id,
                airline_code=last_leg.airline.name.lstrip("_"),
                flight_number=last_leg.flight_number,
                leg_index=1,
                price_cents=int(last.price * 100),
                currency=last.currency or currency or "USD",
            )

        if token is None:
            token = getattr(results[0], "booking_token", None)
        if not token:
            raise ValueError(
                "Missing booking token. Pass `booking_token` explicitly, or "
                "pass `session_id` (extracted from the `tfu` URL parameter on "
                "the booking page) to construct it from flight metadata."
            )

        prepared = deepcopy(filters)
        segments = prepared.flight_segments
        if len(results) > len(segments):
            raise ValueError(
                f"flight has {len(results)} segments but filters has {len(segments)}"
            )
        for seg, res in zip(segments, results, strict=False):
            seg.selected_flight = res

        encoded = self._encode_booking_payload(token, prepared)
        url = with_locale_params(self.BOOKING_URL, currency, language, country)
        try:
            response = self.client.post(
                url=url,
                data=f"f.req={encoded}",
                impersonate="chrome",
                allow_redirects=True,
            )
            response.raise_for_status()
        except Exception as e:
            raise Exception(f"Booking options request failed: {str(e)}") from e

        options: list[BookingOption] = []
        for chunk in iter_wrb_chunks(response.text):
            options.extend(parse_booking_chunk(chunk))
        return options

    # ------------------------------------------------------------------
    # Round-trip / multi-city expansion
    # ------------------------------------------------------------------

    def _expand_multi_leg(
        self,
        flights: list[FlightResult],
        filters: FlightSearchFilters,
        *,
        top_n: int,
        currency: str | None,
        language: str | None,
        country: str | None,
    ) -> list[tuple[FlightResult, ...]] | list[FlightResult]:
        """Recursively fetch next-leg options for round-trip / multi-city."""
        num_segments = len(filters.flight_segments)
        selected_count = sum(
            1 for s in filters.flight_segments if s.selected_flight is not None
        )
        if selected_count >= num_segments - 1:
            return flights

        combos: list[tuple[FlightResult, ...]] = []
        for outbound in flights[:top_n]:
            next_filters = deepcopy(filters)
            next_filters.flight_segments[selected_count].selected_flight = outbound
            next_results = self.search(
                next_filters,
                top_n=top_n,
                currency=currency,
                language=language,
                country=country,
            )
            if next_results is None:
                continue
            for nxt in next_results:
                if isinstance(nxt, tuple):
                    combos.append((outbound,) + nxt)
                else:
                    combos.append((outbound, nxt))
        return combos

    # ------------------------------------------------------------------
    # Booking-payload construction
    # ------------------------------------------------------------------

    @staticmethod
    def _encode_booking_payload(token: str, filters: FlightSearchFilters) -> str:
        """URL-encode the ``f.req`` body for GetBookingResults."""
        formatted = filters.format()
        main = formatted[1] if len(formatted) > 1 else None
        payload = [
            [None, token],
            main,
            None,
            0,
        ]
        wrapped = [None, json.dumps(payload, separators=(",", ":"))]
        return urllib.parse.quote(json.dumps(wrapped, separators=(",", ":")))

    @staticmethod
    def _parse_booking_chunk(chunk):
        """Back-compat shim — prefer :func:`fli.search._decoders.parse_booking_chunk`."""
        return parse_booking_chunk(chunk)

    # ------------------------------------------------------------------
    # Back-compat static-method shims for older test fixtures.
    # The real implementations live in ``fli.search._decoders``.
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_flights_data(row):  # noqa: D401  (alias)
        """Alias for :func:`fli.search._decoders.parse_flight_row`."""
        return parse_flight_row(row)

    @staticmethod
    def _parse_price_info(row):  # noqa: D401
        """Alias for the internal price-block decoder."""
        from fli.search._decoders import _parse_price_info as _impl

        return _impl(row)

    @staticmethod
    def _parse_currency(row):  # noqa: D401
        """Alias returning only the ISO currency code from the price block."""
        from fli.search._decoders import _parse_price_info as _impl

        return _impl(row)[1]
