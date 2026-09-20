"""Flight search orchestrator.

A thin wrapper around the FlightsFrontendService's ``GetShoppingResults``
and ``GetBookingResults`` endpoints. Response decoding lives in
:mod:`fli.search._decoders`; wire framing lives in :mod:`fli.search._wire`;
URL parameter construction lives in :mod:`fli.search._urls`.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.parse
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from fli.models import (
    BookingOption,
    FlightResult,
    FlightSearchFilters,
    PassengerInfo,
    SeatType,
)
from fli.models.google_flights.base import SortBy, TripType
from fli.search._concurrency import parallel_map
from fli.search._decoders import (
    _try_parse_booking_row,  # noqa: F401 — back-compat re-export for tests
    parse_booking_chunk,
    parse_flight_row,
)
from fli.search._tfs import (
    apply_client_side_filters,
    build_tfs,
    fetch_payload,
    page_url,
    unsupported_filters,
)
from fli.search._urls import with_locale_params
from fli.search._urls import with_locale_params as _with_locale_params  # noqa: F401
from fli.search._wire import iter_wrb_chunks
from fli.search.client import get_client
from fli.search.exceptions import SearchParseError

logger = logging.getLogger(__name__)

# Re-exported from its original home so ``from fli.search.flights import
# SearchParseError`` keeps working; the class now lives with the rest of the
# typed error family in ``fli.search.exceptions`` so it inherits
# ``SearchClientError`` and is classified as a search failure, not a crash.
__all__ = ["SearchFlights", "SearchParseError"]

# Google inlines fewer rows — in premium cabins often none — for parties with
# children or infants, because those fares are priced client-side through the
# gated RPC this transport cannot reach; extra adults cost nothing. Shared
# verbatim by the CLI's empty-result hint and the MCP `search_flights` empty
# response's `note` field, so every surface explains an empty result the
# same way. Measured live 2026-09-20: JFK-LHR economy held 23 rows for one
# adult and 16 with a lap infant; SFO-NRT business held 9 for one or two
# adults and 0 with a child.
SPARSE_PASSENGER_MIX_WARNING = (
    "No itineraries were inlined for this passenger mix. Google's search page "
    "prices parties with children or infants client-side, so it often carries "
    "few or no rows for them — most of all in premium cabins. This does not "
    "mean the route has no flights: an adults-only search shows the schedule."
)


def _has_children_or_infants(passenger_info: PassengerInfo) -> bool:
    """Whether the party includes anyone Google prices client-side.

    Extra adults ride the request for free; children and infants (lap or
    seat) are the passenger types that make the search-page transport inline
    fewer — sometimes zero — rows. See ``SPARSE_PASSENGER_MIX_WARNING``.
    """
    return (
        passenger_info.children + passenger_info.infants_on_lap + passenger_info.infants_in_seat > 0
    )


class _RowCountTracker:
    """Notes whether any fetched page decoded to zero rows before filtering.

    A round trip fetches the outbound page and then one page per expanded
    candidate (up to ``top_n``) in parallel worker threads, so this is a
    fresh, per-:meth:`SearchFlights.search` object — never instance state —
    guarded by a lock the same way ``fli.search.dates._SweepHealth`` guards
    its own cross-thread counters. Distinguishes "Google itself inlined
    nothing" (rows == 0) from "Google inlined rows and the caller's own
    airline/price/duration/window filter removed every one of them" (rows >
    0 but ``apply_client_side_filters`` emptied the list) — only the former
    is evidence of the sparse-passenger-mix pricing gap.
    """

    __slots__ = ("_lock", "_any_zero_rows")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._any_zero_rows = False

    def record(self, raw_row_count: int) -> None:
        """Note one page's decoded row count, before client-side filtering."""
        if raw_row_count == 0:
            with self._lock:
                self._any_zero_rows = True

    @property
    def any_zero_rows(self) -> bool:
        """Whether any recorded page decoded to zero rows."""
        with self._lock:
            return self._any_zero_rows


def _sort_key(sort_by: SortBy) -> Callable[[FlightResult], Any]:
    """Return the result-ordering key for ``sort_by``.

    The search page serves Google's own default order, so the sort the
    caller asked for is applied here instead of in the request.
    ``TOP_FLIGHTS`` / ``BEST`` are Google's own blended rankings, which we
    can't reproduce — those keep the page's order.
    """
    if sort_by == SortBy.CHEAPEST:
        return lambda f: (f.price is None, f.price)
    if sort_by == SortBy.DURATION:
        return lambda f: (f.duration is None, f.duration)
    if sort_by == SortBy.DEPARTURE_TIME:
        return lambda f: f.legs[0].departure_datetime
    if sort_by == SortBy.ARRIVAL_TIME:
        return lambda f: f.legs[-1].arrival_datetime
    return lambda f: 0


class SearchFlights:
    """Flight search via Google Flights' FlightsFrontendService API.

    Public surface:

    - :meth:`search` — issue a GetShoppingResults call and return the
      parsed flights.
    - :meth:`get_booking_options` — follow up with GetBookingResults to
      surface bookable fares for a selected itinerary. See the method
      docstring for the live-token limitation.

    Concurrency:
        ``SearchFlights`` is **not thread-safe**. The instance caches the
        shopping-session id from the most recent :meth:`search` call so
        :meth:`get_booking_options` can derive the booking token; two
        concurrent ``search`` calls on the same instance will race on that
        cache and may cross-pollinate sessions between unrelated bookings.
        :attr:`sparse_passenger_mix` has the same limitation — it reflects
        only the most recently *completed* :meth:`search` call.

        For multi-threaded or async server use, either (a) instantiate a
        fresh ``SearchFlights`` per request, or (b) pass the
        ``session_id`` returned by your own session bookkeeping into
        :meth:`get_booking_options` explicitly (the kwarg overrides the
        cached value).
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
        # Last successful search response's ``inner[0][4]`` — the shopping
        # session id used to authenticate the follow-up GetBookingResults
        # call. Captured automatically by :meth:`search` so that
        # :meth:`get_booking_options` can derive the booking token without
        # the caller having to pass anything.
        self._last_session_id: str | None = None
        # Set at the start of every search() call — see the
        # sparse_passenger_mix property.
        self._sparse_passenger_mix: bool = False

    @property
    def sparse_passenger_mix(self) -> bool:
        """Whether the sparse-passenger-mix warning fired on the most recent search().

        ``True`` exactly when the empty result this instance last returned
        (or raised out of) was consistent with Google's client-side pricing
        gap for children/infants — at least one fetched page decoded to zero
        rows before client-side filtering, and the party had a child or
        infant — rather than the caller's own airline/price/duration/window
        filter removing rows Google did inline. See
        ``SPARSE_PASSENGER_MIX_WARNING``. Reset to ``False`` at the start of
        every :meth:`search` call, including ones that raise, so a stale
        ``True`` from an earlier call never leaks into a later one.

        Reflects only the *last completed* :meth:`search` call on this
        instance and is not meant for instances shared across concurrent
        searches — two overlapping :meth:`search` calls on one
        ``SearchFlights`` would race on this attribute the same way they
        already race on ``_last_session_id`` (see the class docstring's
        Concurrency section). The MCP server and CLI each construct a fresh
        ``SearchFlights`` per request, so this is safe there; both read this
        attribute after :meth:`search` instead of recomputing the condition
        themselves.
        """
        return self._sparse_passenger_mix

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
                round-trip or multi-city itinerary. Must be between 1 and
                10 (inclusive). A round trip costs ``1 + top_n`` page
                fetches — one for the outbound search plus one per
                candidate expanded into return flights — so raising it
                surfaces more airlines (the default sort otherwise expands
                only the cheapest ``top_n`` outbounds, which are often all
                from the same carrier) at the cost of more requests.
                Ignored for one-way searches.
            currency: Optional ISO 4217 currency code (``curr`` URL param).
            language: Optional BCP-47 language code (``hl`` URL param).
            country: Optional ISO 3166-1 alpha-2 country code (``gl`` URL param).

        Returns:
            For one-way trips, a list of :class:`FlightResult`. For
            round-trip / multi-city, a list of tuples of
            :class:`FlightResult` (one per segment, in order). ``None``
            when no results.

        Raises:
            ValueError: ``top_n`` is not an ``int`` (``bool`` included — a
                Python ``int`` subclass, rejected explicitly rather than
                silently treated as ``0``/``1``) or is outside ``1..10``
                inclusive.
            Exception: HTTP failure or unparseable response.

        """
        # Reset before any code below can raise, so a search that raises
        # never leaves a stale True from an earlier call on this instance.
        self._sparse_passenger_mix = False

        if not isinstance(top_n, int) or isinstance(top_n, bool) or not 1 <= top_n <= 10:
            raise ValueError(
                f"top_n must be an integer between 1 and 10 (inclusive); got {top_n!r} "
                f"({type(top_n).__name__}). It controls how many outbound options a "
                "round-trip search expands into return-flight combinations — cost is "
                "1 + top_n page fetches, hence the cap."
            )
        # Per-search, lock-guarded — never instance state, which the round
        # trip's parallel expansion workers (below) would trample mid-flight.
        tracker = _RowCountTracker()
        flights = self._fetch_flights(
            filters,
            currency=currency,
            language=language,
            country=country,
            capture_session=True,
            tracker=tracker,
        )
        if flights is None:
            self._warn_if_sparse_passenger_mix(filters, tracker)
            return None
        if filters.trip_type == TripType.ONE_WAY:
            return flights
        combos = self._expand_multi_leg(
            flights,
            filters,
            top_n=top_n,
            currency=currency,
            language=language,
            country=country,
            tracker=tracker,
        )
        if not combos:
            self._warn_if_sparse_passenger_mix(filters, tracker)
        return combos

    def _warn_if_sparse_passenger_mix(
        self, filters: FlightSearchFilters, tracker: _RowCountTracker
    ) -> None:
        """Warn once when an empty result may be Google's pricing gap, not a dead route.

        Called only from :meth:`search`, after the trip's final result is known
        to be empty — never from :meth:`_fetch_flights`, which the round-trip
        expansion calls once per candidate outbound. That keeps this to exactly
        one warning per :meth:`search` call, one-way or round-trip alike.

        ``tracker`` is what keeps this from misattributing an empty result:
        the final list can be empty either because Google inlined nothing
        (``tracker.any_zero_rows``) or because it inlined rows the caller's
        own airline/price/duration/window filter then removed entirely — the
        warning must only fire for the former.
        """
        if not tracker.any_zero_rows:
            return
        if _has_children_or_infants(filters.passenger_info):
            self._sparse_passenger_mix = True
            logger.warning(SPARSE_PASSENGER_MIX_WARNING)

    def _fetch_flights(
        self,
        filters: FlightSearchFilters,
        *,
        currency: str | None,
        language: str | None,
        country: str | None,
        capture_session: bool,
        tracker: _RowCountTracker | None = None,
    ) -> list[FlightResult] | None:
        """Issue one ``GetShoppingResults`` call and decode the flight rows.

        ``capture_session`` controls whether the response's session id is
        written back to ``self._last_session_id``. Only the top-level
        :meth:`search` call sets this; expansion sub-calls in
        :meth:`_expand_multi_leg` run in parallel worker threads and must
        not write to that field — both because the writes would race and
        because the user-visible session id should describe the original
        shopping query, not whichever expansion completed last.

        ``tracker``, when given, records this page's decoded row count
        *before* ``apply_client_side_filters`` runs — see
        :class:`_RowCountTracker`. Optional because this method also backs
        callers (tests, older shims) that don't care about the
        sparse-passenger-mix diagnosis.
        """
        dropped = unsupported_filters(filters)
        if dropped:
            logger.warning(
                "Filters not supported by the search-page transport, ignored: %s",
                ", ".join(dropped),
            )

        url = page_url(build_tfs(filters), currency, language, country)
        inner = fetch_payload(self.client, url)
        if inner is None:
            raise SearchParseError(
                "Search page carried no ds:1 payload — Google may have changed "
                "the page shape, or served a consent/blocked page instead."
            )

        if capture_session:
            self._capture_session_id(inner)

        try:
            flights_raw = [
                item for i in (2, 3) if isinstance(inner[i], list) for item in inner[i][0]
            ]
        except (IndexError, TypeError) as e:
            raise SearchParseError(
                f"Shopping response shape changed — no flights array at inner[2]/[3]: {e}"
            ) from e

        flights: list[FlightResult] = []
        # Bounded ring of unique failure reasons — we only surface the
        # first few in the SearchParseError below, and Google's response
        # rarely tops 100 rows, but capping at construction keeps memory
        # constant regardless of how large a future response gets.
        failure_samples: list[str] = []
        any_failure = False
        for row in flights_raw:
            try:
                flights.append(parse_flight_row(row))
            except (AttributeError, KeyError, ValueError, TypeError) as e:
                reason = f"{type(e).__name__}: {e}"
                any_failure = True
                if reason not in failure_samples and len(failure_samples) < 3:
                    failure_samples.append(reason)
                logger.debug("Skipping flight with unparseable data: %s", reason)

        if flights_raw and any_failure and not flights:
            # Every row failed to parse — likely a wire-format change.
            # Surface the failure reasons so the error isn't blindly
            # blamed on "shape change" when the cause is something else
            # (e.g. all rows hit a known structural quirk we haven't yet
            # handled in the decoder).
            sample = "; ".join(failure_samples)
            raise SearchParseError(
                f"Parsed 0/{len(flights_raw)} flight rows — "
                f"Google response shape may have changed (sample reasons: {sample})"
            )

        if tracker is not None:
            tracker.record(len(flights))
        flights = apply_client_side_filters(flights, filters)
        flights.sort(key=_sort_key(filters.sort_by))
        return flights or None

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

        After a :meth:`search` call, the session id from Google's response
        is cached on the client and used here automatically — no explicit
        token plumbing is required by callers. The booking-call payload
        carries the same selected_flight legs the caller used in their
        round-trip search and a protobuf token constructed from the
        cached session id + the chosen itinerary's identifiers.

        Args:
            flight: A :class:`FlightResult` (one-way) or tuple of results
                (round-trip / multi-city) from :meth:`search`.
            filters: The same filters used in the preceding :meth:`search`
                call. A copy is made internally; caller filters are not
                mutated.
            currency: Optional ISO 4217 currency code passed to Google as
                ``curr=``. Also forms part of the booking token.
            language: Optional BCP-47 language code (``hl`` URL param).
            country: Optional ISO 3166-1 alpha-2 country code (``gl`` URL param).
            booking_token: Explicit override for ``outer[0][1]``.
                Bypasses the automatic construction; use this when you
                have a token captured from a browser's ``tfu`` URL.
            session_id: Explicit override for the session id used to build
                the token. Defaults to the session captured by the most
                recent :meth:`search` call on this client.

        Returns:
            A list of :class:`BookingOption`. Empty list when Google
            returns no vendors.

        Raises:
            ValueError: No session id available — either pass it
                explicitly or call :meth:`search` first.
            Exception: HTTP request failure.

        """
        results: list[FlightResult] = list(flight) if isinstance(flight, tuple) else [flight]
        if not results:
            raise ValueError("flight argument must be a FlightResult or non-empty tuple of them")

        # Resolve the session id: explicit > cached from prior search.
        effective_session = session_id or self._last_session_id

        token = booking_token
        if token is None and effective_session and results[-1].price is not None:
            # Build a session-anchored token from price + flight info.
            # Skipped when the last result has no shopping-list price
            # (premium-cabin round-trips often hit this) — the per-row
            # token from ``row[8]`` is the correct fallback there.
            from fli.search._proto import build_booking_token

            last = results[-1]
            last_leg = last.legs[-1]
            token = build_booking_token(
                session_id=effective_session,
                airline_code=last_leg.airline.name.removeprefix("_"),
                flight_number=last_leg.flight_number,
                leg_index=1,
                price_cents=int(last.price * 100),
                currency=last.currency or currency or "USD",
            )

        if token is None:
            # Fall back to the per-row token captured at parse time.
            #
            # Prefer the last result's token over the first because:
            #  - For one-way / single-segment trips they are the same row.
            #  - For round-trip / multi-city, ``row[8]`` on each result
            #    encodes the *full* itinerary at parse time (every leg,
            #    every flight number), so any row's token is sufficient
            #    to identify the booking — but using the last leg's
            #    matches Google's own indexing (``build_booking_token``
            #    above uses ``leg_index=1`` for the return leg) and is
            #    the row that ``get_booking_options`` is most likely to
            #    have just parsed if the caller is iterating return-leg
            #    candidates.
            #
            # Accessing the attribute directly fails loudly if the
            # caller passes a non-FlightResult, which is what we want.
            token = results[-1].booking_token or results[0].booking_token
        if not token:
            raise ValueError(
                "Missing booking token. Call SearchFlights.search(...) before "
                "get_booking_options(...) so the client can cache the session "
                "id, or pass `session_id` / `booking_token` explicitly. If "
                "your selected flight has ``price=None`` (premium-cabin "
                "round-trip rows often do — see issue #165), make sure its "
                "``booking_token`` attribute is set; the parser populates "
                "it from ``row[8]`` automatically."
            )

        prepared = deepcopy(filters)
        segments = prepared.flight_segments
        if len(results) > len(segments):
            raise ValueError(f"flight has {len(results)} segments but filters has {len(segments)}")
        for seg, res in zip(segments, results, strict=False):
            seg.selected_flight = res

        encoded = self._encode_booking_payload(token, prepared)
        url = with_locale_params(self.BOOKING_URL, currency, language, country)
        response = self.client.post(
            url=url,
            data=f"f.req={encoded}",
            impersonate="chrome",
            allow_redirects=True,
        )
        response.raise_for_status()

        # Booking responses are typically split into two wrb.fr chunks
        # (vendor list + price refinements). Materialise both before
        # parsing so we can parse them in parallel — each chunk is a few
        # hundred KB of pure-Python tree walking, GIL-bound but cheap to
        # overlap with the next chunk's JSON decode (which releases the GIL).
        chunks = list(iter_wrb_chunks(response.text))
        if not chunks:
            return []
        parsed = parallel_map(parse_booking_chunk, chunks)
        options: list[BookingOption] = []
        for chunk_options in parsed:
            options.extend(chunk_options)
        return options

    def build_flight_booking_url(
        self,
        flight: FlightResult | tuple[FlightResult, ...],
        *,
        currency: str | None = None,
        language: str | None = None,
        country: str | None = None,
        seat_type: SeatType = SeatType.ECONOMY,
    ) -> str:
        """Build a Google Flights deep-link URL for a specific itinerary.

        Constructs ``https://www.google.com/travel/flights/booking?tfs=…`` that
        opens the booking page pre-loaded with the given itinerary — the
        airline/OTA fare options and the "Continue" booking CTA included.

        The ``tfs`` itinerary token is fully deterministic (built from the
        flight's airports, dates and flight numbers); no session id or network
        round-trip is required, so the same itinerary always yields the same
        URL. This method never raises — on malformed input it falls back to the
        generic Google Flights URL.

        Args:
            flight: A :class:`~fli.models.FlightResult` (one-way / single
                segment) or a tuple of them (round-trip / multi-city, one
                element per travel direction).
            currency: ISO 4217 currency code appended as ``curr=``.
            language: BCP-47 language code appended as ``hl=``.
            country: ISO 3166-1 alpha-2 country code appended as ``gl=``.
            seat_type: Cabin class encoded into the ``tfs`` token (field 9).
                Defaults to economy for backward compatibility.

        Returns:
            A ``https://www.google.com/travel/flights/booking?tfs=…`` URL.

        """
        from fli.search._proto import LegSpec, build_tfs_token

        def _iata(airport: object) -> str:
            # Handle both Airport enum (has .name) and plain strings.
            return getattr(airport, "name", str(airport)).lstrip("_")

        results: list[FlightResult] = list(flight) if isinstance(flight, tuple) else [flight]
        is_one_way = len(results) == 1

        try:
            segments: list[list[LegSpec]] = []
            for result in results:
                seg_legs = [
                    LegSpec(
                        origin=_iata(leg.departure_airport),
                        dep_date=leg.departure_datetime.date().isoformat(),
                        dest=_iata(leg.arrival_airport),
                        airline=_iata(leg.airline),
                        flight_number=leg.flight_number,
                    )
                    for leg in result.legs
                ]
                segments.append(seg_legs)
            tfs = build_tfs_token(segments, is_one_way=is_one_way, seat=seat_type.value)
            url = f"https://www.google.com/travel/flights/booking?tfs={tfs}"
        except Exception:
            logger.debug("build_flight_booking_url: tfs construction failed", exc_info=True)
            url = "https://www.google.com/travel/flights"

        return with_locale_params(url, currency, language, country)

    def _capture_session_id(self, inner: list) -> None:
        """Cache the shopping session id from ``inner[0][4]`` of a search response.

        The session id is used by :meth:`get_booking_options` to derive a
        booking token automatically. A shape change here means booking
        calls will fall back to "missing token" errors, so we log a
        warning rather than silently leaving the cache untouched.
        """
        try:
            session_id = inner[0][4]
        except (IndexError, TypeError) as exc:
            logger.warning(
                "Failed to capture shopping session id from search response (%s); "
                "subsequent get_booking_options() calls without an explicit "
                "session_id will fail.",
                exc,
            )
            logger.debug("session id capture failed", exc_info=True)
            return
        if isinstance(session_id, str) and session_id:
            self._last_session_id = session_id
        else:
            logger.warning(
                "Shopping response inner[0][4] is %r, not a non-empty string; "
                "session cache unchanged.",
                session_id,
            )

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
        tracker: _RowCountTracker | None = None,
    ) -> list[tuple[FlightResult, ...]] | list[FlightResult]:
        """Fetch next-leg options for round-trip / multi-city in parallel.

        Each ``outbound`` candidate triggers an independent follow-up
        ``GetShoppingResults`` call to enumerate the next leg. Those
        requests share no state, so we issue them in parallel through the
        shared rate-limited executor. With ``top_n=5`` and Google's 10
        req/sec ceiling, all five requests start within ~100ms and the
        bottleneck becomes the network round trip rather than serial
        request scheduling.

        Each worker calls :meth:`_fetch_flights` directly (not
        :meth:`search`) with ``capture_session=False`` so the parallel
        workers never write to ``self._last_session_id``. The session id
        captured by the original outbound :meth:`search` call describes
        the user-visible shopping query and is the one
        :meth:`get_booking_options` should use; letting expansion workers
        race over it would yield non-deterministic results and violate
        the "one session per visible search" contract.

        ``tracker``, when given, is forwarded to every worker's
        :meth:`_fetch_flights` call — it is already lock-guarded (see
        :class:`_RowCountTracker`), so sharing it across these parallel
        workers is safe.
        """
        num_segments = len(filters.flight_segments)
        selected_count = sum(1 for s in filters.flight_segments if s.selected_flight is not None)
        if selected_count >= num_segments - 1:
            return flights

        # Build the request descriptors up front so the worker function is
        # a pure FlightResult → list[FlightResult|tuple] mapping with no
        # mutable shared state.
        candidates = list(flights[:top_n])

        def expand(outbound: FlightResult):
            next_filters = deepcopy(filters)
            next_filters.flight_segments[selected_count].selected_flight = outbound
            sub_flights = self._fetch_flights(
                next_filters,
                currency=currency,
                language=language,
                country=country,
                capture_session=False,
                tracker=tracker,
            )
            if sub_flights is None:
                return outbound, None
            # If more segments remain unselected (multi-city ≥ 3), keep
            # expanding. Otherwise return the flat list of next-leg
            # candidates and let the caller assemble tuples.
            if selected_count + 1 < num_segments - 1:
                return outbound, self._expand_multi_leg(
                    sub_flights,
                    next_filters,
                    top_n=top_n,
                    currency=currency,
                    language=language,
                    country=country,
                    tracker=tracker,
                )
            return outbound, sub_flights

        expansions = parallel_map(expand, candidates)

        combos: list[tuple[FlightResult, ...]] = []
        for outbound, next_results in expansions:
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
        """URL-encode the ``f.req`` body for GetBookingResults.

        Strips the main-filter struct down to the prefix Google's UI sends
        (ends at position 17 — the trailing constant). Google's
        GetBookingResults validates the struct shape and rejects requests
        with the longer 29-element main that GetShoppingResults accepts.

        Raises:
            ValueError: ``filters.format()`` did not yield a main struct.
                Sending ``main=null`` produces an opaque 400 from Google,
                so we fail loudly here instead.

        """
        formatted = filters.format()
        if len(formatted) < 2 or not isinstance(formatted[1], list):
            raise ValueError(
                "filters.format() did not return a main struct at index 1; "
                "cannot construct a booking payload."
            )
        main = formatted[1]
        # The browser sends only main[0..17]; the longer struct used for
        # GetShoppingResults is rejected here. Trim the tail.
        if len(main) > 18:
            main = main[:18]
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
