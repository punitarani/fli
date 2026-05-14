"""End-to-end tests that the parallel search paths actually overlap I/O.

We swap :class:`SearchFlights` / :class:`SearchDates` ``.client`` for a
controlled-latency stub so every test is deterministic and offline. The
stub tracks the peak number of in-flight requests, which lets us assert
that the parallel paths *actually* parallelise (peak > 1) and that the
total request count matches what the search code is expected to issue.
"""

from __future__ import annotations

import json
import threading
import time
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from fli.models import (
    Airline,
    Airport,
    DateSearchFilters,
    FlightLeg,
    FlightResult,
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
    TripType,
)
from fli.search import SearchDates, SearchFlights

FIXTURE_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Controlled-latency HTTP stub
# ---------------------------------------------------------------------------


class _FakeResponse:
    __slots__ = ("text", "status_code")

    def __init__(self, text: str):
        self.text = text
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None


class FakeClient:
    """Records concurrency + simulates per-request latency."""

    def __init__(self, fixture_text: str, latency_ms: float = 50.0):
        """Capture the fixture body and per-request latency budget."""
        self._fixture = fixture_text
        self._latency_s = latency_ms / 1000.0
        self._lock = threading.Lock()
        self.calls = 0
        self.peak_in_flight = 0
        self._in_flight = 0

    def _do(self) -> _FakeResponse:
        with self._lock:
            self.calls += 1
            self._in_flight += 1
            if self._in_flight > self.peak_in_flight:
                self.peak_in_flight = self._in_flight
        try:
            time.sleep(self._latency_s)
        finally:
            with self._lock:
                self._in_flight -= 1
        return _FakeResponse(self._fixture)

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self._do()

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self._do()


def _date_fixture(days: int = 61) -> str:
    """Minimal ``GetCalendarGraph`` body for the date-search parser."""
    base = datetime(2026, 7, 1)
    entries = [
        [
            (base + timedelta(days=i)).strftime("%Y-%m-%d"),
            None,
            [[None, 200.0 + i], "USD0.000"],
        ]
        for i in range(days)
    ]
    inner = json.dumps([None, None, entries])
    return ")]}'\n" + json.dumps([["wrb.fr", None, inner]])


# ---------------------------------------------------------------------------
# Filter builders
# ---------------------------------------------------------------------------


def _round_trip_filters() -> FlightSearchFilters:
    return FlightSearchFilters(
        trip_type=TripType.ROUND_TRIP,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LAX, 0]],
                travel_date="2026-08-01",
            ),
            FlightSegment(
                departure_airport=[[Airport.LAX, 0]],
                arrival_airport=[[Airport.JFK, 0]],
                travel_date="2026-08-08",
            ),
        ],
    )


def _date_filters(days: int) -> DateSearchFilters:
    return DateSearchFilters(
        trip_type=TripType.ONE_WAY,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LAX, 0]],
                travel_date="2026-08-01",
            )
        ],
        from_date="2026-08-01",
        to_date=(datetime(2026, 8, 1) + timedelta(days=days - 1)).strftime("%Y-%m-%d"),
    )


# ---------------------------------------------------------------------------
# Round-trip / multi-leg parallelism
# ---------------------------------------------------------------------------


class TestRoundTripParallel:
    """Round-trip expansion fires all ``top_n`` follow-ups concurrently."""

    @pytest.fixture
    def fixture_text(self) -> str:
        return (FIXTURE_DIR / "flight_search_jfk_lax_oneway_usd.bin").read_text()

    def test_peak_in_flight_matches_top_n(self, fixture_text):
        fake = FakeClient(fixture_text, latency_ms=60.0)
        search = SearchFlights()
        search.client = fake

        results = search.search(_round_trip_filters(), top_n=5)

        assert results is not None and len(results) > 0
        # 1 initial outbound + 5 parallel expansions = 6 total requests.
        assert fake.calls == 6
        # The 5 expansions must overlap (≥ 2 concurrent at some point).
        assert fake.peak_in_flight >= 2, (
            f"Round-trip expansion did not parallelise (peak={fake.peak_in_flight})"
        )

    def test_wall_time_under_sequential_bound(self, fixture_text):
        latency = 60
        fake = FakeClient(fixture_text, latency_ms=latency)
        search = SearchFlights()
        search.client = fake

        t0 = time.perf_counter()
        search.search(_round_trip_filters(), top_n=5)
        wall_ms = (time.perf_counter() - t0) * 1000

        # Sequential would be 6 × 60ms = 360ms. Parallel target ≈ 120ms.
        sequential_floor = 6 * latency
        assert wall_ms < sequential_floor * 0.7, (
            f"Round-trip wall={wall_ms:.0f}ms not significantly under "
            f"sequential floor {sequential_floor}ms"
        )

    def test_only_outbound_call_captures_session_id(self):
        """Parallel expansion workers must not write ``_last_session_id``.

        Regression test for the data race Greptile caught: previously,
        every expansion worker called ``self.search()`` recursively and
        each captured a session id, so ``_last_session_id`` ended up
        holding whichever expansion finished last (non-deterministic).
        After the fix only the top-level outbound search captures.
        """
        outbound_session = "SESSION_OUTBOUND"
        expansion_session = "SESSION_EXPANSION"
        captures: list[bool] = []
        lock = threading.Lock()

        def _make_result(tag: str) -> FlightResult:
            return FlightResult(
                legs=[
                    FlightLeg(
                        airline=Airline.AA,
                        flight_number=tag,
                        departure_airport=Airport.JFK,
                        arrival_airport=Airport.LAX,
                        departure_datetime=datetime(2026, 7, 15, 9, 0),
                        arrival_datetime=datetime(2026, 7, 15, 12, 0),
                        duration=180,
                    )
                ],
                price=300,
                currency="USD",
                duration=180,
                stops=0,
            )

        def _capturing_fetch(_self, filters, **kwargs):
            with lock:
                captures.append(kwargs["capture_session"])
            if kwargs["capture_session"]:
                _self._last_session_id = outbound_session
                # Outbound: return 5 candidates so the expansion fans out.
                return [_make_result(f"out-{i}") for i in range(5)]
            # Expansion: a well-behaved version of this code path must NOT
            # touch ``_last_session_id``. Assert it stayed as the outbound's.
            assert _self._last_session_id == outbound_session, (
                "Expansion worker observed _last_session_id != outbound — "
                "a previous expansion clobbered it."
            )
            # Returning a single return-leg candidate; the assembler will
            # produce one (outbound, return) tuple per expansion.
            return [_make_result(f"ret-{expansion_session}")]

        with patch.object(
            SearchFlights, "_fetch_flights", autospec=True, side_effect=_capturing_fetch
        ):
            search = SearchFlights()
            results = search.search(_round_trip_filters(), top_n=5)

        assert results is not None and len(results) == 5
        # Outbound call (capture=True) + 5 expansion workers (capture=False).
        assert captures.count(True) == 1, f"captures: {captures}"
        assert captures.count(False) == 5, f"captures: {captures}"
        # The cache must still hold the OUTBOUND session id — not whichever
        # expansion worker finished last.
        assert search._last_session_id == outbound_session, (
            f"Expected outbound session cached, got {search._last_session_id!r}"
        )


# ---------------------------------------------------------------------------
# Date-range chunking
# ---------------------------------------------------------------------------


class TestDateChunkParallel:
    def test_three_chunks_overlap(self):
        fake = FakeClient(_date_fixture(days=61), latency_ms=60.0)
        search = SearchDates()
        search.client = fake

        # 180 days / 61 = 3 chunks.
        results = search.search(_date_filters(days=180))

        assert results is not None and len(results) > 0
        assert fake.calls == 3
        assert fake.peak_in_flight >= 2, (
            f"Date chunks did not parallelise (peak={fake.peak_in_flight})"
        )

    def test_single_chunk_skips_executor(self):
        """Sub-61-day ranges still take the synchronous fast path."""
        fake = FakeClient(_date_fixture(days=30), latency_ms=10.0)
        search = SearchDates()
        search.client = fake

        results = search.search(_date_filters(days=30))

        assert results is not None
        assert fake.calls == 1
        assert fake.peak_in_flight == 1

    def test_chunk_filters_advance_segment_dates(self):
        """Each chunk's segment ``travel_date`` is offset by N×61 days."""
        search = SearchDates()
        filters = _date_filters(days=180)
        chunks = search._build_chunk_filters(
            deepcopy(filters),
            datetime.strptime(filters.from_date, "%Y-%m-%d"),
            datetime.strptime(filters.to_date, "%Y-%m-%d"),
        )
        assert len(chunks) == 3
        first = chunks[0].flight_segments[0].travel_date
        second = chunks[1].flight_segments[0].travel_date
        third = chunks[2].flight_segments[0].travel_date
        assert first == "2026-08-01"
        # Shifted by exactly 61 and 122 days.
        assert datetime.strptime(second, "%Y-%m-%d") - datetime.strptime(
            first, "%Y-%m-%d"
        ) == timedelta(days=61)
        assert datetime.strptime(third, "%Y-%m-%d") - datetime.strptime(
            first, "%Y-%m-%d"
        ) == timedelta(days=122)

    def test_chunk_filters_do_not_mutate_source(self):
        """``_build_chunk_filters`` must not mutate the caller's filters."""
        search = SearchDates()
        filters = _date_filters(days=180)
        original_date = filters.flight_segments[0].travel_date
        search._build_chunk_filters(
            filters,
            datetime.strptime(filters.from_date, "%Y-%m-%d"),
            datetime.strptime(filters.to_date, "%Y-%m-%d"),
        )
        assert filters.flight_segments[0].travel_date == original_date
