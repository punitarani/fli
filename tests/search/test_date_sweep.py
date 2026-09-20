"""Offline tests for the per-date sweep in :class:`fli.search.SearchDates`.

The page transport has no calendar grid, so a date search prices every date
with its own page fetch. These tests feed synthetic ``ds:1`` payloads through
a stub client and cover the failure, cost and filtering behaviour of that
sweep — none of them touch the network.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Any

import pytest

from fli.models import (
    Airline,
    Airport,
    DateSearchFilters,
    FlightSegment,
    PassengerInfo,
    TimeRestrictions,
    TripType,
)
from fli.search import _tfs as tfs_module
from fli.search import dates as dates_module
from fli.search._concurrency import get_executor
from fli.search.exceptions import (
    SearchClientError,
    SearchConnectionError,
    SearchParseError,
)
from tests.search._pages import as_search_page

# Far enough out that every date in the widest range below is bookable.
FIRST_DAY = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=30)


# ---------------------------------------------------------------------------
# Synthetic payload builders (positions mirror .reverse-eng/notes/response_map.md)
# ---------------------------------------------------------------------------


def _leg(airline: str = "AA", flight_number: str = "100", hour: int = 9) -> list:
    leg = [None] * 33
    leg[3] = "JFK"
    leg[6] = "LAX"
    leg[8] = [hour, 0]
    leg[10] = [hour + 3, 0]
    leg[11] = 180
    leg[20] = [2026, 7, 15]
    leg[21] = [2026, 7, 15]
    leg[22] = [airline, flight_number, None, "Carrier"]
    return leg


def _row(price: float, airline: str = "AA", hour: int = 9) -> list:
    legs = [_leg(airline=airline, hour=hour)]
    detail = [None] * 25
    detail[0] = airline
    detail[1] = ["Carrier"]
    detail[2] = legs
    detail[9] = 180
    row = [None] * 11
    row[0] = detail
    row[1] = [[None, price], None]
    return row


def _page(rows: list) -> str:
    """Wrap flight rows as the ``ds:1`` payload of a rendered search page."""
    return as_search_page([None, None, [rows], None])


class _Response:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None


class StubClient:
    """Serves a canned page (or raises) for every request, counting calls."""

    def __init__(self, body: str | None = None, error: BaseException | None = None):
        """Serve ``body`` for every request, or raise ``error`` instead."""
        self.body = body
        self.error = error
        self.calls = 0
        self._lock = threading.Lock()

    def get(self, url: str, **kwargs: Any) -> _Response:
        with self._lock:
            self.calls += 1
        if self.error is not None:
            raise self.error
        return _Response(self.body or "")


def _filters(days: int, **kwargs) -> DateSearchFilters:
    """One-way date filters spanning ``days`` dates starting at FIRST_DAY."""
    return DateSearchFilters(
        trip_type=TripType.ONE_WAY,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LAX, 0]],
                travel_date=FIRST_DAY.strftime("%Y-%m-%d"),
                time_restrictions=kwargs.pop("time_restrictions", None),
            )
        ],
        from_date=FIRST_DAY.strftime("%Y-%m-%d"),
        to_date=(FIRST_DAY + timedelta(days=days - 1)).strftime("%Y-%m-%d"),
        **kwargs,
    )


def _search_with(client: StubClient) -> dates_module.SearchDates:
    search = dates_module.SearchDates()
    search.client = client
    return search


# ---------------------------------------------------------------------------
# 1. A total transport failure must not read as "no dates"
# ---------------------------------------------------------------------------


class TestTotalFailureIsLoud:
    def test_every_date_raising_surfaces_an_error(self):
        """A dead transport used to return None — indistinguishable from "no flights"."""
        client = StubClient(error=SearchConnectionError("connection refused"))
        with pytest.raises(SearchClientError) as excinfo:
            _search_with(client).search(_filters(days=5))
        message = str(excinfo.value)
        assert "5" in message, f"error should say how many dates failed: {message}"
        assert "connection refused" in message, f"error should say why: {message}"

    def test_every_date_missing_the_payload_surfaces_an_error(self):
        """A consent/blocked page carries no ds:1 blob — that is a failure, not emptiness."""
        client = StubClient(body="<html>no data callback here</html>")
        with pytest.raises(SearchClientError) as excinfo:
            _search_with(client).search(_filters(days=4))
        message = str(excinfo.value)
        assert "4" in message
        assert "ds:1" in message

    def test_one_bad_date_is_skipped_not_fatal(self):
        """Individual failures stay warnings as long as some date priced."""
        good = _page([_row(120.0)])

        class _Flaky(StubClient):
            def get(self, url: str, **kwargs: Any) -> _Response:
                with self._lock:
                    self.calls += 1
                    n = self.calls
                if n == 2:
                    raise SearchConnectionError("transient")
                return _Response(good)

        results = _search_with(_Flaky()).search(_filters(days=3))
        assert results is not None
        assert len(results) == 2, "the two healthy dates should still be priced"

    def test_dates_without_flights_are_not_failures(self):
        """A page that parses but has no rows means "no flights", not a broken transport."""
        results = _search_with(StubClient(_page([]))).search(_filters(days=3))
        assert results is None


# ---------------------------------------------------------------------------
# 2. Row extraction must be total
# ---------------------------------------------------------------------------


class TestRowExtractionIsTotal:
    @pytest.mark.parametrize(
        "payload",
        [
            [None, None, [], None],  # empty container — payload[2][0] used to IndexError
            [None, None, None, None],
            [None, None, ["not-a-row-list"], None],
            [None, None],  # short payload
        ],
        ids=["empty-container", "null-slots", "rows-not-a-list", "short-payload"],
    )
    def test_odd_payload_shapes_yield_no_results_without_raising(self, payload):
        client = StubClient(as_search_page(payload))
        assert _search_with(client).search(_filters(days=3)) is None


# ---------------------------------------------------------------------------
# 3. One level of parallelism — nested pools deadlock
# ---------------------------------------------------------------------------


class TestSingleLevelParallelism:
    """The sweep must map the whole range once, never once per chunk again.

    Nesting ``parallel_map`` inside a ``parallel_map`` worker deadlocks: both
    levels share one bounded pool, so outer tasks can hold every worker while
    blocking on inner tasks that can never be scheduled.

    These are structural assertions rather than a "does it hang?" test on
    purpose. A real deadlock parks non-daemon pool workers inside a task, and
    the interpreter then hangs in ``threading._shutdown`` joining them — so a
    behavioural test would hang CI on regression no matter how its own timeout
    is written, and detaching the workers from
    ``concurrent.futures.thread._threads_queues`` does not prevent it. The
    assertions below catch the same regression in milliseconds.
    """

    def _counted_map(self, mp, sizes: list[int]):
        real = dates_module.parallel_map

        def _counting(fn, items, **kwargs):
            materialised = list(items)
            sizes.append(len(materialised))
            return real(fn, materialised, **kwargs)

        mp.setattr(dates_module, "parallel_map", _counting)

    def test_sweep_submits_one_batch_of_work(self):
        """70 dates spanning two chunks are mapped by a single call."""
        sizes: list[int] = []
        client = StubClient(_page([_row(150.0)]))
        search = _search_with(client)
        with pytest.MonkeyPatch.context() as mp:
            self._counted_map(mp, sizes)
            search.search(_filters(days=70))
        assert sizes == [70], f"expected one flat map over 70 dates, got {sizes}"

    def test_no_parallel_map_runs_inside_a_worker(self):
        """Pin the property that actually causes the deadlock: no nesting.

        Fails on the old shape, where the per-chunk worker called
        ``parallel_map`` again while running on a pool thread.
        """
        depth = threading.local()
        nested: list[str] = []
        real = dates_module.parallel_map

        def _tracking(fn, items, **kwargs):
            if getattr(depth, "inside", False):
                nested.append(threading.current_thread().name)

            def _wrapped(item):
                depth.inside = True
                try:
                    return fn(item)
                finally:
                    depth.inside = False

            return real(_wrapped, list(items), **kwargs)

        client = StubClient(_page([_row(150.0)]))
        search = _search_with(client)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(dates_module, "parallel_map", _tracking)
            results = search.search(_filters(days=70))
        assert results is not None and len(results) == 70
        assert nested == [], f"parallel_map was called from inside a worker: {nested}"


# ---------------------------------------------------------------------------
# 4. Bounded cost
# ---------------------------------------------------------------------------


class TestDateCountCap:
    def test_range_over_the_cap_is_refused(self):
        client = StubClient(_page([_row(150.0)]))
        with pytest.raises(ValueError) as excinfo:
            _search_with(client).search(_filters(days=dates_module.MAX_DATES_PER_SEARCH + 1))
        message = str(excinfo.value)
        assert str(dates_module.MAX_DATES_PER_SEARCH) in message
        assert "narrow" in message.lower()
        assert client.calls == 0, "the cap must be checked before any fetch"

    def test_range_at_the_cap_is_allowed(self):
        client = StubClient(_page([_row(150.0)]))
        results = _search_with(client).search(_filters(days=dates_module.MAX_DATES_PER_SEARCH))
        assert results is not None and len(results) == dates_module.MAX_DATES_PER_SEARCH

    def test_default_cap_is_93(self):
        assert dates_module.MAX_DATES_PER_SEARCH == 93

    def test_cli_default_range_fits_under_the_cap(self):
        import inspect

        from fli.cli.commands.dates import dates as dates_command

        params = inspect.signature(dates_command).parameters
        start = datetime.strptime(params["start_date"].default, "%Y-%m-%d")
        end = datetime.strptime(params["end_date"].default, "%Y-%m-%d")
        assert (end - start).days + 1 <= dates_module.MAX_DATES_PER_SEARCH


# ---------------------------------------------------------------------------
# 5. Client-side filters apply to the sweep too
# ---------------------------------------------------------------------------


class TestClientSideFiltersApplyToDates:
    """``tfs`` has no field for these, so the sweep must filter after fetching.

    Without it, the cheapest date price is taken over rows the caller asked
    to exclude — the filter is reported as applied and silently is not.
    """

    def _mixed_page(self) -> str:
        return _page(
            [
                _row(100.0, airline="AA", hour=6),
                _row(500.0, airline="DL", hour=20),
            ]
        )

    def test_airline_include_filters_before_taking_the_minimum(self):
        client = StubClient(self._mixed_page())
        results = _search_with(client).search(_filters(days=2, airlines=[Airline.DL]))
        assert results is not None
        assert [r.price for r in results] == [500.0, 500.0]

    def test_airline_exclude_filters_before_taking_the_minimum(self):
        client = StubClient(self._mixed_page())
        results = _search_with(client).search(_filters(days=2, airlines_exclude=[Airline.AA]))
        assert results is not None
        assert [r.price for r in results] == [500.0, 500.0]

    def test_departure_window_filters_before_taking_the_minimum(self):
        client = StubClient(self._mixed_page())
        results = _search_with(client).search(
            _filters(
                days=2,
                time_restrictions=TimeRestrictions(earliest_departure=8, latest_departure=23),
            )
        )
        assert results is not None
        assert [r.price for r in results] == [500.0, 500.0]

    def test_max_duration_filters_before_taking_the_minimum(self):
        page = _page([_row(100.0, airline="AA"), _row(500.0, airline="DL")])
        client = StubClient(page)
        # Both synthetic rows last 180 minutes, so a 60-minute ceiling drops
        # every row and the date prices to nothing rather than to $100.
        results = _search_with(client).search(_filters(days=2, max_duration=60))
        assert results is None

    def test_filters_survive_the_chunk_split(self):
        """Chunk copies must carry every filter, not just the ones re-listed."""
        client = StubClient(self._mixed_page())
        results = _search_with(client).search(_filters(days=70, airlines_exclude=[Airline.AA]))
        assert results is not None
        assert {r.price for r in results} == {500.0}


# ---------------------------------------------------------------------------
# Transient pages without a ds:1 payload (fix round 1, F2)
# ---------------------------------------------------------------------------


class _Sequence(StubClient):
    """Serves a scripted list of bodies, one per call, repeating the last."""

    def __init__(self, bodies: list[str]):
        """Record the scripted bodies."""
        super().__init__()
        self.bodies = bodies

    def get(self, url: str, **kwargs: Any) -> _Response:
        with self._lock:
            index = min(self.calls, len(self.bodies) - 1)
            self.calls += 1
        return _Response(self.bodies[index])


@pytest.fixture
def no_backoff(monkeypatch):
    """Record retry delays instead of sleeping them."""
    slept: list[float] = []
    monkeypatch.setattr(tfs_module, "_sleep", slept.append)
    return slept


class TestTransientPageRetry:
    """One page in ~60 comes back 200 with no ds:1 blob; retry just that case."""

    BLANK = "<html>no data callback here</html>"

    def test_healthy_sweep_stays_one_request_per_date(self, no_backoff):
        client = StubClient(_page([_row(150.0)]))
        results = _search_with(client).search(_filters(days=5))
        assert results is not None and len(results) == 5
        assert client.calls == 5, "a healthy sweep must not pay for the retry"
        assert no_backoff == []

    def test_missing_once_then_present_succeeds_in_two_fetches(self, no_backoff):
        client = _Sequence([self.BLANK, _page([_row(150.0)])])
        results = _search_with(client).search(_filters(days=1))
        assert results is not None and len(results) == 1
        assert client.calls == 2
        assert no_backoff == [0.5]

    def test_missing_three_times_gives_up_after_exactly_three_fetches(self, no_backoff):
        client = _Sequence([self.BLANK])
        with pytest.raises(SearchClientError) as excinfo:
            _search_with(client).search(_filters(days=1))
        assert client.calls == 3
        assert no_backoff == [0.5, 1.5]
        assert "ds:1" in str(excinfo.value)

    def test_total_failure_message_carries_the_consent_hint(self, no_backoff):
        client = _Sequence([self.BLANK])
        with pytest.raises(SearchClientError) as excinfo:
            _search_with(client).search(_filters(days=2))
        assert "consent/blocked page" in str(excinfo.value)

    def test_http_errors_are_not_retried(self, no_backoff):
        """Only a 200-with-no-payload is transient; a raised error is not."""
        client = StubClient(error=SearchConnectionError("connection refused"))
        with pytest.raises(SearchClientError):
            _search_with(client).search(_filters(days=1))
        assert client.calls == 1
        assert no_backoff == []


# ---------------------------------------------------------------------------
# Per-date processing must be total (fix round 1, R5)
# ---------------------------------------------------------------------------


class TestPerDateProcessingIsTotal:
    def test_zero_leg_row_with_a_window_does_not_sink_the_sweep(self):
        """A decoded row with no legs used to raise IndexError out of the sweep.

        ``_within_window`` reaches for ``legs[0]``; ``FlightResult.legs`` has
        no minimum length and Google's rows occasionally decode to none.
        """
        legless = _row(100.0)
        legless[0][2] = []  # detail[2] — the leg array
        client = StubClient(_page([legless, _row(500.0, hour=20)]))
        results = _search_with(client).search(
            _filters(
                days=2,
                time_restrictions=TimeRestrictions(earliest_departure=8, latest_departure=23),
            )
        )
        assert results is not None
        assert [r.price for r in results] == [500.0, 500.0]

    def test_failure_is_logged_without_a_traceback(self, caplog):
        """A 93-date sweep must not print 93 tracebacks; keep those at DEBUG."""
        client = StubClient(error=SearchConnectionError("connection refused"))
        with caplog.at_level(logging.WARNING, logger="fli.search.dates"):
            with pytest.raises(SearchClientError):
                _search_with(client).search(_filters(days=2))
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings, "each bad date should still warn"
        assert all(r.exc_info is None for r in warnings), (
            "warnings must not carry exc_info — logging.lastResort prints the full traceback"
        )
        assert any("connection refused" in r.getMessage() for r in warnings)


# ---------------------------------------------------------------------------
# Circuit breaker for a sweep that is failing deterministically (round 2, N4)
# ---------------------------------------------------------------------------


class TestSweepCircuitBreaker:
    """A consent-blocked client fails identically on every date.

    `fetch_payload`'s retry and the client's own tenacity retries multiply, so
    paying three page fetches per date for a certain failure costs hundreds of
    requests to learn one thing. Once enough dates have come back payload-less
    and none has succeeded, stop.
    """

    BLANK = "<html>no data callback here</html>"

    @staticmethod
    def _ceiling() -> int:
        """Most fetches a fully blocked sweep can cost, whatever its length.

        The breaker trips after ``SWEEP_FAILURE_THRESHOLD`` failures, and every
        date already in flight at that moment still finishes its own retries —
        so the bound is (threshold + pool size) x attempts per page, with no
        term for the number of dates requested.
        """
        workers = get_executor()._max_workers
        return (dates_module.SWEEP_FAILURE_THRESHOLD + workers) * tfs_module.PAGE_FETCH_ATTEMPTS

    def test_always_blank_sweep_stops_early(self, no_backoff):
        client = StubClient(self.BLANK)
        with pytest.raises(SearchParseError) as excinfo:
            _search_with(client).search(_filters(days=30))

        # Without the breaker this is 30 dates x 3 attempts = 90 fetches.
        assert client.calls < 90, "the breaker did not stop the sweep"
        assert client.calls <= self._ceiling(), f"stopped, but late: {client.calls} fetches"
        message = str(excinfo.value)
        assert "consent/blocked page" in message
        assert "FLI_SOCS_COOKIE" in message

    def test_breaker_does_not_trip_once_any_date_succeeds(self, no_backoff):
        """A healthy first date means later misses are transient, not systemic."""
        good = _page([_row(150.0)])
        blank = self.BLANK

        class _FirstOneWorks(StubClient):
            def get(self, url: str, **kwargs: Any) -> _Response:
                with self._lock:
                    self.calls += 1
                    n = self.calls
                return _Response(good if n == 1 else blank)

        client = _FirstOneWorks()
        results = _search_with(client).search(_filters(days=12))

        # One date priced; every other date still got its full retry budget.
        assert results is not None and len(results) == 1
        assert client.calls == 1 + (12 - 1) * tfs_module.PAGE_FETCH_ATTEMPTS

    def test_healthy_sweep_is_unaffected(self, no_backoff):
        client = StubClient(_page([_row(150.0)]))
        results = _search_with(client).search(_filters(days=20))
        assert results is not None and len(results) == 20
        assert client.calls == 20

    def test_scattered_misses_below_the_threshold_do_not_trip(self, no_backoff):
        """Fewer payload-less dates than the threshold must all be retried."""
        good = _page([_row(150.0)])
        blank = self.BLANK
        misses = dates_module.SWEEP_FAILURE_THRESHOLD - 1

        class _FewMisses(StubClient):
            def __init__(self):
                super().__init__()
                self.seen: set[str] = set()

            def get(self, url: str, **kwargs: Any) -> _Response:
                with self._lock:
                    self.calls += 1
                    self.seen.add(url)
                    bad = len(self.seen) <= misses
                return _Response(blank if bad else good)

        client = _FewMisses()
        results = _search_with(client).search(_filters(days=10))
        assert results is not None and len(results) == 10 - misses
        assert client.calls == misses * tfs_module.PAGE_FETCH_ATTEMPTS + (10 - misses)

    def test_generic_exceptions_do_not_trip_the_breaker(self, no_backoff):
        """Only the payload-less page is deterministic; a network blip is not.

        A blocked client fails identically on every date, which is what makes
        abandoning the sweep safe. A burst of connection errors says nothing
        about the dates that have not been tried yet, so counting those toward
        the threshold would abort a healthy sweep over a transient wobble.
        """
        good = _page([_row(150.0)])
        failures = dates_module.SWEEP_FAILURE_THRESHOLD

        class _EarlyBlips(StubClient):
            def get(self, url: str, **kwargs: Any) -> _Response:
                with self._lock:
                    self.calls += 1
                    n = self.calls
                if n <= failures:
                    raise SearchConnectionError("connection refused")
                return _Response(good)

        client = _EarlyBlips()
        results = _search_with(client).search(_filters(days=20))

        # Nothing aborted: the five blips cost their own dates, everything else
        # priced normally.
        assert results is not None
        assert len(results) == 20 - failures
        assert client.calls == 20

    def test_a_wholly_dead_network_still_raises_at_the_end(self, no_backoff):
        """Not tripping is not the same as going quiet — the sweep still errors."""
        client = StubClient(error=SearchConnectionError("connection refused"))
        with pytest.raises(SearchClientError) as excinfo:
            _search_with(client).search(_filters(days=8))
        assert "every date in the range failed" in str(excinfo.value)
        # Every date was tried, because nothing here is known to be deterministic.
        assert client.calls == 8

    def test_tripped_sweep_that_still_returns_prices_warns_once(self, caplog):
        """A truncated answer must never be silent — that is this PR's whole point.

        Driven through ``_collect`` directly rather than through a sweep: after
        P1 the only way a success lands *after* a trip is a real race between
        worker threads, which cannot be staged deterministically. The contract
        being pinned is ``_collect``'s, so this exercises it head-on.
        """
        priced = dates_module.DatePrice(date=(FIRST_DAY,), price=150.0, currency="USD")
        outcomes = [
            dates_module._DateOutcome(price=priced),
            *[dates_module._DateOutcome(failure="the search page carried no ds:1 payload")] * 5,
            *[dates_module._DateOutcome(attempted=False)] * 24,
        ]

        with caplog.at_level(logging.WARNING, logger="fli.search.dates"):
            results = dates_module.SearchDates._collect(outcomes, 30, skipped=24)

        assert results == [priced]
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1, f"expected exactly one warning, got {len(warnings)}"
        message = warnings[0].getMessage()
        assert "1 of 30" in message, message
        assert "24 were skipped" in message, message
        assert "FLI_SOCS_COOKIE" in message, message
        assert warnings[0].exc_info is None, "no traceback on the truncation warning"
        assert "\n" not in message, "the warning must be a single line"

    def test_tripped_sweep_with_no_prices_reports_once_as_an_error(self, caplog):
        """Nothing priced is already an exception; don't also warn about truncation."""
        outcomes = [
            *[dates_module._DateOutcome(failure=dates_module._NO_PAYLOAD)] * 5,
            *[dates_module._DateOutcome(attempted=False)] * 25,
        ]
        with caplog.at_level(logging.WARNING, logger="fli.search.dates"):
            with pytest.raises(SearchParseError):
                dates_module.SearchDates._collect(outcomes, 30, skipped=25)
        assert not [r for r in caplog.records if "skipped" in r.getMessage()]

    def test_tripped_sweep_with_no_prices_never_ends_quietly(self, caplog):
        """Tripped + a date that loaded but had no flights + nothing priced.

        The truncation warning was guarded on there being prices, and the
        "everything failed" error needs *every* attempted date to have failed —
        so a single loaded-but-empty date fell between the two and the sweep
        returned ``None`` with 24 dates abandoned and not a word about it.
        With no prices at all this is a blocked sweep, so it raises.
        """
        outcomes = [
            dates_module._DateOutcome(),  # page loaded fine, route has no flights
            *[dates_module._DateOutcome(failure=dates_module._NO_PAYLOAD)] * 5,
            *[dates_module._DateOutcome(attempted=False)] * 24,
        ]
        with caplog.at_level(logging.WARNING, logger="fli.search.dates"):
            with pytest.raises(SearchParseError) as excinfo:
                dates_module.SearchDates._collect(outcomes, 30, skipped=24)
        message = str(excinfo.value)
        assert "24 skipped" in message, message
        assert "FLI_SOCS_COOKIE" in message, message
        assert "consent/blocked page" in message, message

    def test_tripped_breaker_always_gives_the_blocked_page_error(self):
        """Blank pages interleaved with connection errors is still a blocked sweep.

        The hint used to be all-or-nothing: one connection error alongside the
        blank pages downgraded the error to `SearchClientError` and dropped the
        `FLI_SOCS_COOKIE` pointer — even though the breaker only ever trips on
        blank pages, so a trip means the blocked page is the dominant cause.
        """
        outcomes = [
            *[dates_module._DateOutcome(failure=dates_module._NO_PAYLOAD)] * 5,
            *[
                dates_module._DateOutcome(
                    failure="SearchConnectionError: connection refused",
                    error=SearchConnectionError("connection refused"),
                )
            ]
            * 4,
            *[dates_module._DateOutcome(attempted=False)] * 21,
        ]
        with pytest.raises(SearchParseError) as excinfo:
            dates_module.SearchDates._collect(outcomes, 30, skipped=21)
        message = str(excinfo.value)
        assert "FLI_SOCS_COOKIE" in message, message
        # Both causes are still reported, not just the dominant one.
        assert "ds:1" in message and "connection refused" in message, message

    def test_untripped_mixed_failures_keep_the_general_error(self):
        """Without a trip the error type still follows what actually failed."""
        outcomes = [
            dates_module._DateOutcome(failure=dates_module._NO_PAYLOAD),
            dates_module._DateOutcome(
                failure="SearchConnectionError: connection refused",
                error=SearchConnectionError("connection refused"),
            ),
        ]
        with pytest.raises(SearchClientError) as excinfo:
            dates_module.SearchDates._collect(outcomes, 2)
        assert not isinstance(excinfo.value, SearchParseError)
        assert "FLI_SOCS_COOKIE" not in str(excinfo.value)

    def test_untripped_sweep_does_not_warn_about_truncation(self, no_backoff, caplog):
        """A healthy sweep prices every date, so there is nothing to announce."""
        client = StubClient(_page([_row(150.0)]))
        with caplog.at_level(logging.WARNING, logger="fli.search.dates"):
            results = _search_with(client).search(_filters(days=12))
        assert results is not None and len(results) == 12
        assert not [r for r in caplog.records if "skipped" in r.getMessage()]

    @pytest.mark.parametrize("days", [30, 61, 93])
    def test_blocked_sweep_costs_the_same_at_any_range(self, days, no_backoff):
        """The cost of learning "this client is blocked" must not scale with the range.

        Before the breaker it was 3 fetches per date — 279 for a quarter, and
        up to 837 once the client's own three retries multiplied in.
        """
        client = StubClient(self.BLANK)
        with pytest.raises(SearchParseError):
            _search_with(client).search(_filters(days=days))
        assert client.calls <= self._ceiling(), (
            f"{days}-date blocked sweep cost {client.calls} fetches"
        )

    def test_error_says_it_gave_up_early(self, no_backoff):
        client = StubClient(self.BLANK)
        with pytest.raises(SearchParseError) as excinfo:
            _search_with(client).search(_filters(days=40))
        assert "of 40 dates" in str(excinfo.value)


# ---------------------------------------------------------------------------
# A sweep that mostly failed to load must not read as "no flights" (T20)
# ---------------------------------------------------------------------------


class TestMostlyFailedSweepIsLoud:
    """The breaker cannot catch "1 loaded, 29 timeouts" — it disarms for good
    the moment any page loads, empty or not. If nothing priced and at least
    half the attempted dates never made it to a page, that is raised too.
    """  # noqa: D205

    def _timeout(self) -> dates_module._DateOutcome:
        return dates_module._DateOutcome(
            failure="SearchConnectionError: connection refused",
            error=SearchConnectionError("connection refused"),
        )

    def test_mostly_timeouts_around_one_loaded_empty_date_raises(self):
        outcomes = [dates_module._DateOutcome(), *[self._timeout() for _ in range(29)]]
        with pytest.raises(SearchClientError) as excinfo:
            dates_module.SearchDates._collect(outcomes, 30, skipped=0)
        assert not isinstance(excinfo.value, SearchParseError)
        message = str(excinfo.value)
        assert "Priced 0 of 30" in message, message
        assert "29 of the 30" in message, message
        assert "FLI_SOCS_COOKIE" not in message, message
        assert isinstance(excinfo.value.__cause__, SearchConnectionError)

    def test_mostly_no_payload_failures_raise_search_parse_error(self):
        outcomes = [
            dates_module._DateOutcome(),
            *[dates_module._DateOutcome(failure=dates_module._NO_PAYLOAD) for _ in range(3)],
        ]
        with pytest.raises(SearchParseError) as excinfo:
            dates_module.SearchDates._collect(outcomes, 4, skipped=0)
        assert "FLI_SOCS_COOKIE" not in str(excinfo.value)

    def test_tie_between_loaded_and_failed_raises(self):
        outcomes = [dates_module._DateOutcome(), self._timeout()]
        with pytest.raises(SearchClientError):
            dates_module.SearchDates._collect(outcomes, 2, skipped=0)

    def test_minority_failures_with_no_results_return_none_and_warn_once(self, caplog):
        outcomes = [
            dates_module._DateOutcome(),
            dates_module._DateOutcome(),
            dates_module._DateOutcome(),
            self._timeout(),
        ]
        with caplog.at_level(logging.WARNING, logger="fli.search.dates"):
            results = dates_module.SearchDates._collect(outcomes, 4, skipped=0)
        assert results is None
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1, f"expected exactly one warning, got {len(warnings)}"
        message = warnings[0].getMessage()
        assert "3" in message and "loaded" in message, message
        assert "1 of 4" in message, message

    def test_partial_results_with_a_minority_failure_warns_once(self, caplog):
        priced_a = dates_module.DatePrice(date=(FIRST_DAY,), price=100.0, currency="USD")
        priced_b = dates_module.DatePrice(
            date=(FIRST_DAY + timedelta(days=1),), price=200.0, currency="USD"
        )
        outcomes = [
            dates_module._DateOutcome(price=priced_a),
            dates_module._DateOutcome(price=priced_b),
            self._timeout(),
        ]
        with caplog.at_level(logging.WARNING, logger="fli.search.dates"):
            results = dates_module.SearchDates._collect(outcomes, 3, skipped=0)
        assert results == [priced_a, priced_b]
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1, f"expected exactly one warning, got {len(warnings)}"
        assert "2 of 3" in warnings[0].getMessage(), warnings[0].getMessage()

    def test_partial_results_with_a_tripped_breaker_still_warns_once(self, caplog):
        priced = dates_module.DatePrice(date=(FIRST_DAY,), price=100.0, currency="USD")
        outcomes = [
            dates_module._DateOutcome(price=priced),
            *[dates_module._DateOutcome(failure=dates_module._NO_PAYLOAD) for _ in range(5)],
            *[dates_module._DateOutcome(attempted=False) for _ in range(24)],
        ]
        with caplog.at_level(logging.WARNING, logger="fli.search.dates"):
            results = dates_module.SearchDates._collect(outcomes, 30, skipped=24)
        assert results == [priced]
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1, f"expected exactly one warning, got {len(warnings)}"

    def test_all_loaded_empty_returns_none_with_no_warnings(self, caplog):
        outcomes = [dates_module._DateOutcome() for _ in range(5)]
        with caplog.at_level(logging.WARNING, logger="fli.search.dates"):
            results = dates_module.SearchDates._collect(outcomes, 5, skipped=0)
        assert results is None
        assert not [r for r in caplog.records if r.levelno == logging.WARNING]

    def test_all_priced_returns_list_with_no_warnings(self, caplog):
        prices = [
            dates_module.DatePrice(date=(FIRST_DAY + timedelta(days=i),), price=100.0 + i)
            for i in range(5)
        ]
        outcomes = [dates_module._DateOutcome(price=p) for p in prices]
        with caplog.at_level(logging.WARNING, logger="fli.search.dates"):
            results = dates_module.SearchDates._collect(outcomes, 5, skipped=0)
        assert results == prices
        assert not [r for r in caplog.records if r.levelno == logging.WARNING]

    def test_not_attempted_dates_do_not_count_towards_the_arithmetic(self):
        """5 past dates + 1 loaded-empty + 1 failed must behave as the tie case."""
        outcomes = [
            *[dates_module._DateOutcome(attempted=False) for _ in range(5)],
            dates_module._DateOutcome(),
            self._timeout(),
        ]
        with pytest.raises(SearchClientError):
            dates_module.SearchDates._collect(outcomes, 7, skipped=0)
