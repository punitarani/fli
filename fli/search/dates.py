"""Date-based flight search implementation for finding the cheapest dates to fly.

This module provides functionality to search for the cheapest flights across a date range.
It uses Google Flights' calendar view API to find the best prices for each date.
It is intended to be used for finding the cheapest dates to fly, not the cheapest flights.
"""

import logging
import threading
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, NamedTuple

from pydantic import BaseModel

from fli.core import extract_currency_from_price_token
from fli.models import DateSearchFilters, FlightResult
from fli.models.google_flights.base import TripType, earliest_searchable_date
from fli.search._concurrency import parallel_map
from fli.search._decoders import parse_flight_row
from fli.search._tfs import (
    apply_client_side_filters,
    build_tfs,
    fetch_payload,
    page_url,
    unsupported_filters,
)
from fli.search.client import get_client
from fli.search.exceptions import SearchClientError, SearchParseError

logger = logging.getLogger(__name__)

# Same wording the flight path uses for the same condition, so a caller who
# sees it on either path gets the same hint about what to check.
_NO_PAYLOAD = (
    "the search page carried no ds:1 payload — Google may have changed the "
    "page shape, or served a consent/blocked page instead"
)

MAX_DATES_PER_SEARCH = 93
"""Most dates a single :meth:`SearchDates.search` call will price.

The public search page carries no calendar grid, so every date in the range
costs its own full page fetch (~2 MB). Ninety-three days is a whole quarter —
comfortably wider than the CLI's 60-day and the MCP prompt's 61-day defaults —
and caps one search at roughly 190 MB of transfer rather than letting a
"2026-01-01 to 2026-12-31" request quietly issue 365 requests.
"""

SWEEP_FAILURE_THRESHOLD = 5
"""Payload-less pages, before any success, that abandon a sweep.

Retries multiply. The client retries a request three times, and
:func:`~fli.search._tfs.fetch_payload` fetches a page up to three times, so one
date can cost nine HTTP requests before it gives up — and a client that is
being blocked (an EU/EEA IP with the consent cookie disabled, say) fails that
way on *every* date. Paying it 93 times to learn one fact is the wrong trade.

Only the payload-less page counts. That failure is deterministic: a consent or
block page is served to every request alike, so the dates not yet tried will
fail the same way. A connection error or timeout says nothing about them, so
counting those would abandon a healthy sweep over a transient wobble — they
keep the ordinary behaviour of costing their own date and nothing more.

The breaker also only looks at the start of a sweep: it arms while no date has
produced a usable page, and disarms permanently the moment one does. A working
sweep therefore keeps the full retry budget for every transient miss in it.
"""


class _SweepHealth:
    """Tracks whether a sweep is failing the one way that is worth quitting over.

    Shared by the worker threads pricing each date, so every read and write is
    under one lock. ``should_stop`` answers "is this sweep failing
    deterministically?", which is only ever true before the first success.
    """

    __slots__ = ("_lock", "_blocked", "_any_success", "_threshold", "_skipped")

    def __init__(self, threshold: int):
        """Arm a breaker that trips after ``threshold`` payload-less pages."""
        self._lock = threading.Lock()
        self._blocked = 0
        self._any_success = False
        self._threshold = threshold
        self._skipped = 0

    def record_success(self) -> None:
        """Note a date whose page arrived; disarms the breaker for good."""
        with self._lock:
            self._any_success = True

    def record_blocked(self) -> None:
        """Note a date whose page arrived without a ``ds:1`` payload.

        Only this failure mode counts towards the threshold — see the module
        constant's docstring for why a network error deliberately does not.
        """
        with self._lock:
            self._blocked += 1

    def record_skip(self) -> None:
        """Note a date abandoned because the breaker had already tripped."""
        with self._lock:
            self._skipped += 1

    @property
    def skipped(self) -> int:
        """How many dates were abandoned without being requested."""
        with self._lock:
            return self._skipped

    def should_stop(self) -> bool:
        """Report whether the sweep has only ever been blocked, and enough times."""
        with self._lock:
            return not self._any_success and self._blocked >= self._threshold


class DatePrice(BaseModel):
    """Flight price for a specific date."""

    date: tuple[datetime] | tuple[datetime, datetime]
    price: float
    currency: str | None = None


class _DateOutcome(NamedTuple):
    """What pricing one date produced.

    Attributes:
        price: The cheapest itinerary for the date, or ``None`` when the date
            was skipped, failed, or genuinely had no flights.
        failure: Human-readable reason the date could not be priced, or
            ``None`` when the fetch succeeded (even if it found nothing).
        error: The exception behind ``failure``, kept for chaining.
        attempted: ``False`` for dates skipped before any request (past
            dates), so they don't count towards the "everything failed" check.

    """  # noqa: D413

    price: DatePrice | None = None
    failure: str | None = None
    error: BaseException | None = None
    attempted: bool = True


def _reasons(failed: list[_DateOutcome]) -> list[str]:
    """Up to 3 distinct failure messages, in the order they were first seen.

    Shared by every ``_collect`` branch that raises or warns about failed
    dates, so the same range always gets the same short list however it is
    reported.
    """
    reasons: list[str] = []
    for outcome in failed:
        if outcome.failure not in reasons and len(reasons) < 3:
            reasons.append(outcome.failure)
    return reasons


def _flights_in(payload: Any) -> list[FlightResult]:
    """Decode every flight row in a ``ds:1`` payload.

    Total by construction: a payload whose ``[2]`` / ``[3]`` slots are absent,
    empty, or not the nested list we expect yields no flights instead of an
    ``IndexError`` that would abort the whole sweep. Individual unparseable
    rows are skipped the same way the flight search skips them.
    """
    flights: list[FlightResult] = []
    if not isinstance(payload, list):
        return flights
    for index in (2, 3):
        block = payload[index] if index < len(payload) else None
        if not isinstance(block, list) or not block:
            continue
        rows = block[0]
        if not isinstance(rows, list):
            continue
        for row in rows:
            try:
                flights.append(parse_flight_row(row))
            except (AttributeError, IndexError, KeyError, TypeError, ValueError):
                continue
    return flights


class SearchDates:
    """Date-based flight search implementation.

    This class provides methods to search for flight prices across a date range,
    useful for finding the cheapest dates to fly.
    """

    # Dates are swept one page fetch each (see ``_price_one_date``); the
    # GetCalendarGraph RPC this class used to POST to is gated and no longer
    # reachable, so its URL and headers are gone rather than left as dead
    # constants that imply the class still speaks that protocol.

    # Range size at which the sweep splits into independent chunk filters.
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
            ValueError: The range covers more than :data:`MAX_DATES_PER_SEARCH`
                dates, which would cost one page fetch each.
            SearchClientError: Every date in the range failed to load, or
                nothing priced because at least half the attempted dates
                never loaded — see :meth:`_collect`.

        Notes:
            Every date in the range costs its own search-page fetch — the page
            serves no calendar grid — so the range is capped at
            :data:`MAX_DATES_PER_SEARCH` dates. Internally it is still split
            into ``MAX_DAYS_PER_SEARCH``-day chunk filters, but all dates are
            priced by a single flat parallel map.

        """
        dropped = unsupported_filters(filters)
        if dropped:
            logger.warning(
                "Filters not supported by the search-page transport, ignored: %s",
                ", ".join(dropped),
            )

        from_date = datetime.strptime(filters.from_date, "%Y-%m-%d")
        to_date = datetime.strptime(filters.to_date, "%Y-%m-%d")

        # Build every chunk descriptor up front so the per-date requests share
        # no mutable state. This both enables parallel execution and fixes a
        # latent bug in the previous sequential version: each chunk rewrote
        # ``filters.flight_segments[*].travel_date`` in place, so the
        # second-and-later chunks had segment dates that no longer matched
        # ``current_from``.
        tasks = [
            (chunk, day)
            for chunk in self._build_chunk_filters(filters, from_date, to_date)
            for day in self._days_in(chunk)
        ]

        if len(tasks) > MAX_DATES_PER_SEARCH:
            raise ValueError(
                f"This date search covers {len(tasks)} dates, above the "
                f"{MAX_DATES_PER_SEARCH}-date limit. Google's search page serves no "
                "calendar grid, so every date costs its own full page fetch. "
                "Narrow the range (or run several smaller searches)."
            )

        # One flat map over every date. Nesting a second ``parallel_map``
        # inside each chunk's worker deadlocks: both levels share one bounded
        # pool, so the outer tasks can occupy every worker while blocking on
        # inner tasks that can never be scheduled.
        #
        # ``health`` is the sweep's circuit breaker: a client that is being
        # blocked fails identically on every date, and each failed date costs
        # up to nine HTTP requests once the client's retries and the page
        # retry multiply. Queued dates check it before spending anything.
        health = _SweepHealth(SWEEP_FAILURE_THRESHOLD)
        outcomes = parallel_map(
            lambda task: self._price_one_date(
                task[0],
                task[1],
                currency=currency,
                language=language,
                country=country,
                health=health,
            ),
            tasks,
        )
        return self._collect(outcomes, len(tasks), skipped=health.skipped)

    def _days_in(self, filters: DateSearchFilters) -> list[datetime]:
        """List every date in one chunk's ``from_date``..``to_date`` range."""
        from_date = filters.parsed_from_date
        to_date = filters.parsed_to_date
        return [
            from_date + timedelta(days=offset) for offset in range((to_date - from_date).days + 1)
        ]

    @staticmethod
    def _collect(
        outcomes: list[_DateOutcome],
        total: int,
        *,
        skipped: int = 0,
    ) -> list[DatePrice] | None:
        """Assemble priced dates, raising when nothing could be fetched at all.

        A date with no flights is a legitimate answer; a date whose page never
        arrived is not. When *every* attempted date failed, returning an empty
        list would report a dead transport as "this route has no flights" —
        exactly the silent failure this client exists to avoid.

        The error type mirrors the flight path: a range where every page came
        back without a ``ds:1`` blob raises :class:`SearchParseError`, the same
        class (and hint) a single unreadable page raises there. Anything else
        raises the more general :class:`SearchClientError`.

        A sweep that tripped the circuit breaker must never end quietly either.
        With prices to show, the answer is real but incomplete, so it comes with
        one warning naming the count. With none at all the sweep is simply
        blocked — and the tripped breaker is the evidence for that, not the
        exact mix of what each attempted date happened to do.

        The breaker is not the only way a sweep can go quietly wrong, though:
        it disarms for good the instant any page loads, empty or not, so "1
        loaded, 29 timeouts" sails straight past it — one date out of thirty
        is not enough evidence that a route has no flights. When nothing
        priced and at least half the attempted dates never loaded (``failed
        >= loaded``), that is raised too. A page did load in that case, which
        rules out an EU/EEA consent wall — those block every request alike —
        so this path never adds the ``FLI_SOCS_COOKIE`` hint the branch above
        does.

        Short of either raise, a sweep that lost some dates but not enough to
        doubt the rest still owes the caller exactly one line saying so,
        whether or not it ends up with anything to return.

        Args:
            outcomes: One entry per date in the range, in date order.
            total: Dates the sweep set out to price, so the error can say how
                many were abandoned when the circuit breaker stopped it.
            skipped: Dates the breaker abandoned without requesting them.
                Non-zero exactly when the breaker tripped.

        """
        results = [o.price for o in outcomes if o.price is not None]
        attempted = [o for o in outcomes if o.attempted]
        failed = [o for o in attempted if o.failure]
        # "loaded" counts every attempted date whose page actually arrived,
        # priced or not — it does not distinguish the two, because when
        # ``results`` is empty (the only time this number matters below)
        # every loaded date is by definition one with no flights.
        loaded = len(attempted) - len(failed)
        # The breaker only ever trips on payload-less pages, so a non-zero skip
        # count *is* the blocked-page diagnosis, whatever else failed alongside.
        tripped = skipped > 0
        everything_failed = bool(attempted) and len(failed) == len(attempted)

        if not results and (everything_failed or tripped):
            reasons = _reasons(failed)
            cause = next((o.error for o in failed if o.error is not None), None)
            blocked = tripped or (bool(failed) and all(o.failure == _NO_PAYLOAD for o in failed))
            error_type = SearchParseError if blocked else SearchClientError

            if everything_failed:
                message = (
                    f"Priced 0 of {total} dates — every date in the range failed. "
                    f"Reasons: {'; '.join(reasons)}"
                )
            else:
                # Some attempted date loaded and simply had no flights, which is
                # not a failure on its own — but with nothing priced anywhere and
                # the breaker tripped, the sweep still has no usable answer.
                message = (
                    f"Priced 0 of {total} dates — no date in the range could be priced. "
                    f"Reasons: {'; '.join(reasons) or 'no flights on the dates that loaded'}"
                )
            if tripped:
                message += (
                    f". Gave up after {len(attempted)} of {total} dates ({skipped} skipped): "
                    "a sweep that has not loaded a single page is failing for the same "
                    "reason on every date, and each one costs several requests"
                )
            if blocked:
                message += (
                    ". If you are on an EU/EEA IP, Google's consent interstitial serves no "
                    "results — the client sends a pre-accepted SOCS cookie by default, so "
                    "check FLI_SOCS_COOKIE has not been set to an empty value"
                )
            raise error_type(message) from cause

        if not results and failed and len(failed) >= loaded:
            # The breaker never saw this coming: one loaded page (even an
            # empty one) disarms it for good, so a sweep that is mostly
            # timeouts around a single lucky date never trips it. Half the
            # attempted dates never loading is its own signal that "no
            # flights" cannot be concluded from the handful that did.
            reasons = _reasons(failed)
            cause = next((o.error for o in failed if o.error is not None), None)
            blocked = bool(failed) and all(o.failure == _NO_PAYLOAD for o in failed)
            error_type = SearchParseError if blocked else SearchClientError
            message = (
                f"Priced 0 of {total} dates — {len(failed)} of the {len(attempted)} dates "
                f'tried failed to load, so "no flights" cannot be concluded from the '
                f"{loaded} that did. Reasons: {'; '.join(reasons)}"
            )
            # Unlike the branch above, a page did load here — that rules out a
            # consent wall, which blocks every request identically. Adding the
            # FLI_SOCS_COOKIE hint would point at a diagnosis this sweep just
            # disproved, so it is deliberately left off.
            raise error_type(message) from cause

        if tripped:
            # Exactly one line, whatever the sweep's size: the caller is about
            # to act on a partial answer and has no other way to know it.
            logger.warning(
                "Date sweep returned %d of %d dates: %d were skipped after %d pages came "
                "back without a ds:1 payload and none had loaded yet. The prices below are "
                "real but incomplete — retry, or check FLI_SOCS_COOKIE if you are in the "
                "EU/EEA.",
                len(results),
                total,
                skipped,
                SWEEP_FAILURE_THRESHOLD,
            )
        elif failed and results:
            # Neither raise fired — most dates loaded fine — but the caller
            # still can't tell a complete sweep from this one just by looking
            # at the list, so it gets the same "exactly one line" treatment.
            logger.warning(
                "Date sweep priced %d of %d dates: %d failed to load. The prices below "
                "are real but incomplete.",
                len(results),
                total,
                len(failed),
            )
        elif failed:
            # No results, but too few dates failed to raise: most of the
            # sweep loaded fine and simply found nothing. Still worth a line —
            # otherwise a caller sees only `None`, indistinguishable from a
            # sweep where every date loaded and truly had no flights.
            logger.warning(
                "Date sweep found no flights on the %d dates that loaded; %d of %d dates "
                "failed to load, so treat this as provisional rather than a confirmed "
                "empty range. Reasons: %s",
                loaded,
                len(failed),
                len(attempted),
                "; ".join(_reasons(failed)),
            )
        return results or None

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

        Copies are made with ``model_copy`` rather than by re-listing fields
        in a fresh ``DateSearchFilters``: the hand-written list silently
        dropped ``airlines_exclude``, ``alliances`` and ``alliances_exclude``,
        so any search wide enough to be chunked ignored those filters.
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
                filters.model_copy(
                    update={
                        "flight_segments": segments,
                        "from_date": current_from.strftime("%Y-%m-%d"),
                        "to_date": current_to.strftime("%Y-%m-%d"),
                    }
                )
            )
            current_from = current_to + timedelta(days=1)
            chunk_index += 1
        return chunks

    def _price_one_date(
        self,
        filters: DateSearchFilters,
        day: datetime,
        *,
        currency: str | None,
        language: str | None,
        country: str | None,
        health: "_SweepHealth | None" = None,
    ) -> _DateOutcome:
        """Price one departure date through its own search-page fetch.

        Google's ``GetCalendarGraph`` RPC used to hand back a whole date grid
        in one call, but it now requires a browser-signed
        ``x-goog-batchexecute-bgr`` header (see :mod:`fli.search._tfs`). The
        public search page has no such grid, so each date costs its own page
        fetch. Those run concurrently under the shared rate limiter.

        Returns an outcome rather than a bare ``DatePrice | None`` so the
        caller can tell "this date had no flights" apart from "this date never
        loaded" — see :meth:`_collect`.

        ``health`` is the sweep's circuit breaker. It is consulted before any
        request, so a date still queued when the sweep is already known to be
        failing deterministically costs nothing at all.
        """
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
        # abort the whole chunk. The floor is the same one the filter models
        # validate against, so a date the models accept is never silently
        # dropped here.
        if day.date() < earliest_searchable_date():
            return _DateOutcome(attempted=False)

        # Nothing in this sweep has loaded and enough dates have failed, so
        # this one will fail too. Skip it rather than spend its retry budget;
        # ``attempted=False`` keeps it out of the "everything failed" tally,
        # which the already-failed dates satisfy on their own.
        if health is not None and health.should_stop():
            health.record_skip()
            return _DateOutcome(attempted=False)

        url = page_url(build_tfs(filters, travel_dates=travel_dates), currency, language, country)
        try:
            payload = fetch_payload(self.client, url)
            if payload is None:
                # Logged here rather than raised: one bad date is a warning,
                # and ``_collect`` decides whether *every* date failing is fatal.
                logger.warning(
                    "Pricing %s failed: the search page carried no ds:1 payload",
                    travel_dates[0],
                )
                if health is not None:
                    health.record_blocked()
                return _DateOutcome(failure=_NO_PAYLOAD)

            if health is not None:
                # The page arrived and decoded; from here on the sweep is
                # healthy and later misses get their full retry budget.
                health.record_success()

            # The filters Google has no ``tfs`` field for (airlines, price cap,
            # duration, departure window) are applied to the decoded rows,
            # exactly as the flight search applies them — otherwise the
            # cheapest price for a date is taken over itineraries the caller
            # asked to exclude.
            #
            # Decoding and filtering sit inside the ``try`` on purpose: they
            # walk attacker-shaped data from the wire, and letting one odd row
            # raise out of here would sink the whole sweep, which is the class
            # of bug this method exists to avoid.
            flights = apply_client_side_filters(_flights_in(payload), filters)
            prices = [flight.price for flight in flights if flight.price]
        except Exception as exc:  # noqa: BLE001 — one bad date must not sink the sweep
            # One concise line per bad date. A 93-date sweep against a blocked
            # client would otherwise print 93 full tracebacks through
            # ``logging.lastResort``, which is exactly what fli.cli.errors
            # exists to prevent. The traceback stays available at DEBUG.
            logger.warning("Pricing %s failed: %s: %s", travel_dates[0], type(exc).__name__, exc)
            logger.debug("Pricing %s failed", travel_dates[0], exc_info=True)
            # Deliberately not fed to the breaker: an exception here (a
            # timeout, a reset connection) tells us nothing about the dates
            # that have not been tried, unlike a page served without its
            # payload. See SWEEP_FAILURE_THRESHOLD.
            return _DateOutcome(failure=f"{type(exc).__name__}: {exc}", error=exc)

        if not prices:
            return _DateOutcome()

        return _DateOutcome(
            price=DatePrice(
                date=tuple(dates),
                price=min(prices),
                currency=currency,
            )
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
