"""Tests for the ``top_n`` parameter on :meth:`SearchFlights.search` (issue #142).

Round-trip results "all come from a single airline" because the outbound
options are fetched once, sorted, and only the first ``top_n`` of them are
expanded into return-flight combinations (``_expand_multi_leg`` in
``fli/search/flights.py``). With the default sort that's usually five
outbounds from the same cheap carrier. ``top_n`` was already a library
parameter; these tests pin its contract now that it is also exposed on the
CLI and MCP tools:

* bounds (``1..10`` inclusive) are enforced with a clear ``ValueError``,
  raised before any network call;
* a round trip costs exactly ``1 + top_n`` page fetches — one outbound
  ``GetShoppingResults`` call plus one per expanded candidate;
* one-way searches never expand, regardless of ``top_n``.

Follows the existing mocking convention from ``tests/search/test_expand_multi_leg.py``:
``SearchFlights._fetch_flights`` is patched so no real HTTP call is made.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from fli.models import (
    Airline,
    Airport,
    FlightLeg,
    FlightResult,
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
    TripType,
)
from fli.search.flights import SearchFlights


def _future(days: int) -> str:
    """Return a YYYY-MM-DD date ``days`` from now — never a literal calendar date."""
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


def _result(dep: Airport, arr: Airport, hour: int = 9) -> FlightResult:
    # hour stays well under 24 for every caller below (max 6 + 9 = 15), so a
    # plain ``hour + 3`` arrival never needs to roll over into the next day.
    # Relative to "now" — this is leg metadata for a
    # fabricated FlightResult, not a search filter's travel_date, but the
    # file's own rule (never a literal calendar date) still applies to it.
    departure = (datetime.now() + timedelta(days=35)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    return FlightResult(
        legs=[
            FlightLeg(
                airline=Airline.AA,
                flight_number="100",
                departure_airport=dep,
                arrival_airport=arr,
                departure_datetime=departure,
                arrival_datetime=departure + timedelta(hours=3),
                duration=180,
            )
        ],
        price=300,
        currency="USD",
        duration=180,
        stops=0,
    )


def _round_trip_filters() -> FlightSearchFilters:
    return FlightSearchFilters(
        trip_type=TripType.ROUND_TRIP,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LHR, 0]],
                travel_date=_future(35),
            ),
            FlightSegment(
                departure_airport=[[Airport.LHR, 0]],
                arrival_airport=[[Airport.JFK, 0]],
                travel_date=_future(42),
            ),
        ],
    )


def _one_way_filters() -> FlightSearchFilters:
    return FlightSearchFilters(
        trip_type=TripType.ONE_WAY,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LHR, 0]],
                travel_date=_future(35),
            ),
        ],
    )


class TestTopNBoundsValidation:
    """1 <= top_n <= 10 — a clear ValueError, raised before any network call."""

    @pytest.mark.parametrize("bad_top_n", [0, -1, 11, 100])
    def test_out_of_range_raises_value_error(self, bad_top_n):
        client = SearchFlights()
        with pytest.raises(ValueError, match="top_n"):
            client.search(_round_trip_filters(), top_n=bad_top_n)

    @pytest.mark.parametrize("good_top_n", [1, 5, 10])
    def test_boundary_values_do_not_raise_for_the_bound_check(self, good_top_n, monkeypatch):
        """1 and 10 are valid boundaries — the bound check itself must let them through."""
        client = SearchFlights()
        monkeypatch.setattr(SearchFlights, "_fetch_flights", lambda self, *a, **k: None)
        # None outbound flights short-circuits to None *after* the bound check —
        # reaching that path (instead of the ValueError) proves 1 and 10 passed.
        assert client.search(_round_trip_filters(), top_n=good_top_n) is None

    @pytest.mark.parametrize("bad_top_n", [0, 11])
    def test_out_of_range_never_reaches_the_network(self, bad_top_n, monkeypatch):
        """The bound check must short-circuit before _fetch_flights is ever called."""
        client = SearchFlights()

        def _unexpected_call(*_args, **_kwargs):
            raise AssertionError("_fetch_flights should not be called for an out-of-range top_n")

        monkeypatch.setattr(SearchFlights, "_fetch_flights", _unexpected_call)
        with pytest.raises(ValueError):
            client.search(_round_trip_filters(), top_n=bad_top_n)


class TestTopNTypeValidation:
    """Non-int top_n (and bool) must raise ValueError, not TypeError.

    A bare ``if not 1 <= top_n <= 10:`` comparison against a non-comparable
    type (``"5"``, ``None``) raises ``TypeError`` from Python itself, which
    ``classify_error()`` does NOT map to ``validation_error`` (it only
    matches ``ValidationError | ValueError``) — so it would have surfaced as
    ``unexpected_error`` instead. ``bool`` is an ``int`` subclass in Python
    (``True == 1``), so it silently passed the old bound check too; this
    rejects it explicitly rather than accepting it as 1.
    """

    @pytest.mark.parametrize("bad_top_n", ["5", 5.0, None, True, False])
    def test_non_int_or_bool_raises_value_error_not_type_error(self, bad_top_n):
        client = SearchFlights()
        with pytest.raises(ValueError, match="top_n"):
            client.search(_round_trip_filters(), top_n=bad_top_n)

    @pytest.mark.parametrize("bad_top_n", ["5", 5.0, None, True, False])
    def test_non_int_or_bool_never_reaches_the_network(self, bad_top_n, monkeypatch):
        client = SearchFlights()

        def _unexpected_call(*_args, **_kwargs):
            raise AssertionError("_fetch_flights should not be called for a non-int/bool top_n")

        monkeypatch.setattr(SearchFlights, "_fetch_flights", _unexpected_call)
        with pytest.raises(ValueError):
            client.search(_round_trip_filters(), top_n=bad_top_n)

    @pytest.mark.parametrize("good_top_n", [1, 10])
    def test_valid_edge_ints_still_pass(self, good_top_n, monkeypatch):
        """1 and 10 are valid int boundaries — must not be caught by the new type check."""
        client = SearchFlights()
        monkeypatch.setattr(SearchFlights, "_fetch_flights", lambda self, *a, **k: None)
        assert client.search(_round_trip_filters(), top_n=good_top_n) is None


class TestTopNFetchCount:
    """A round trip costs exactly 1 + top_n page fetches."""

    @pytest.mark.parametrize("top_n", [1, 5, 10])
    def test_fetch_count_is_one_plus_top_n(self, top_n):
        client = SearchFlights()
        # Exactly top_n outbound candidates so every one of them gets expanded
        # (top_n candidates fed into a top_n cap == top_n expansions, never fewer).
        outbound_candidates = [_result(Airport.JFK, Airport.LHR, hour=6 + i) for i in range(top_n)]

        lock = threading.Lock()
        state = {"n": 0}

        def _fake_fetch(filters, **kwargs):
            with lock:
                state["n"] += 1
                call_index = state["n"]
            if call_index == 1:
                return outbound_candidates
            return [_result(Airport.LHR, Airport.JFK, hour=6)]

        with patch.object(SearchFlights, "_fetch_flights", side_effect=_fake_fetch):
            results = client.search(_round_trip_filters(), top_n=top_n)

        assert state["n"] == 1 + top_n
        assert results is not None
        assert len(results) == top_n

    def test_more_outbound_candidates_than_top_n_still_costs_one_plus_top_n(self):
        """Cost model holds even when Google returns more outbounds than top_n."""
        top_n = 3
        client = SearchFlights()
        outbound_candidates = [_result(Airport.JFK, Airport.LHR, hour=6 + i) for i in range(10)]

        lock = threading.Lock()
        state = {"n": 0}

        def _fake_fetch(filters, **kwargs):
            with lock:
                state["n"] += 1
                call_index = state["n"]
            if call_index == 1:
                return outbound_candidates
            return [_result(Airport.LHR, Airport.JFK, hour=6)]

        with patch.object(SearchFlights, "_fetch_flights", side_effect=_fake_fetch):
            client.search(_round_trip_filters(), top_n=top_n)

        assert state["n"] == 1 + top_n


class TestTopNOneWayIgnored:
    """top_n only matters once there is a return leg to expand into."""

    def test_one_way_never_expands_regardless_of_top_n(self):
        client = SearchFlights()
        outbound = [_result(Airport.JFK, Airport.LHR)]

        with patch.object(SearchFlights, "_fetch_flights", return_value=outbound) as mocked_fetch:
            results = client.search(_one_way_filters(), top_n=9)

        # Only the single outbound fetch — no expansion calls at all.
        mocked_fetch.assert_called_once()
        assert results == outbound

    def test_one_way_default_top_n_produces_no_error(self):
        client = SearchFlights()
        with patch.object(SearchFlights, "_fetch_flights", return_value=None):
            assert client.search(_one_way_filters()) is None
