"""Tests for the ``top_n`` parameter on the MCP tools (issue #142).

``top_n`` controls how many outbound options a round-trip search expands
into return-flight combinations (``SearchFlights.search`` in
``fli/search/flights.py``); the default sort otherwise only ever expands
the cheapest 5 outbounds, which are often all the same carrier. Cost is
``1 + top_n`` page fetches, which is why it is capped at 10.

Unlike the CLI, the MCP tools do not reject an explicitly-set ``top_n`` on
a one-way search — see the CLI's ``--top-n`` docstring in
``fli/cli/commands/flights.py`` for that UX decision, which is deliberately
CLI-only. ``SearchFlights.search`` itself simply ignores ``top_n`` for
one-way trips (it never reaches the expansion step), so passing it through
unconditionally for MCP callers is enough.

``get_booking_options`` re-runs the search to locate the itinerary it is
about to price; ``top_n`` must reach that re-run search too, or a flight
only discoverable with a raised ``top_n`` could never be matched.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from fli.mcp.server import (
    FlightSearchParams,
    _execute_booking_options,
    _execute_flight_search,
)


def _future(days: int) -> str:
    """Return a YYYY-MM-DD date ``days`` from now — never a literal calendar date."""
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


def _round_trip_params(**overrides) -> FlightSearchParams:
    fields = {
        "origin": "JFK",
        "destination": "LHR",
        "departure_date": _future(35),
        "return_date": _future(42),
    }
    fields.update(overrides)
    return FlightSearchParams(**fields)


def _one_way_params(**overrides) -> FlightSearchParams:
    fields = {
        "origin": "JFK",
        "destination": "LHR",
        "departure_date": _future(35),
    }
    fields.update(overrides)
    return FlightSearchParams(**fields)


def _capturing_stub(calls: list[dict]):
    """Return a ``SearchFlights.search`` stand-in that records its kwargs and no-ops."""

    def _stub(self, filters, **kwargs):
        calls.append(kwargs)
        return None

    return _stub


class TestTopNDefaultsAndForwarding:
    def test_default_top_n_is_5(self):
        assert (
            FlightSearchParams(origin="JFK", destination="LHR", departure_date=_future(35)).top_n
            == 5
        )

    def test_round_trip_forwards_top_n_to_search(self, monkeypatch):
        calls: list[dict] = []
        monkeypatch.setattr("fli.mcp.server.SearchFlights.search", _capturing_stub(calls))

        _execute_flight_search(_round_trip_params(top_n=8))

        assert calls, "SearchFlights.search was not called"
        assert calls[-1]["top_n"] == 8

    def test_round_trip_default_top_n_forwarded_too(self, monkeypatch):
        calls: list[dict] = []
        monkeypatch.setattr("fli.mcp.server.SearchFlights.search", _capturing_stub(calls))

        _execute_flight_search(_round_trip_params())

        assert calls[-1]["top_n"] == 5

    def test_one_way_top_n_still_forwarded_and_causes_no_error(self, monkeypatch):
        """MCP does not reject an explicit top_n on a one-way search (unlike the CLI)."""
        calls: list[dict] = []
        monkeypatch.setattr("fli.mcp.server.SearchFlights.search", _capturing_stub(calls))

        result = _execute_flight_search(_one_way_params(top_n=9))

        assert result["success"] is True
        assert calls[-1]["top_n"] == 9


class TestTopNForwardedToBookingOptionsRerunSearch:
    """get_booking_options re-runs the search; the same top_n must reach it."""

    def test_top_n_reaches_the_rerun_search(self, monkeypatch):
        calls: list[dict] = []
        monkeypatch.setattr("fli.mcp.server.SearchFlights.search", _capturing_stub(calls))

        _execute_booking_options(_round_trip_params(top_n=10), flight_numbers=None)

        assert calls, "SearchFlights.search was not called"
        assert calls[-1]["top_n"] == 10

    def test_default_top_n_reaches_the_rerun_search(self, monkeypatch):
        calls: list[dict] = []
        monkeypatch.setattr("fli.mcp.server.SearchFlights.search", _capturing_stub(calls))

        _execute_booking_options(_round_trip_params(), flight_numbers=None)

        assert calls[-1]["top_n"] == 5


class TestTopNBoundsRejectedByMcpTools:
    """Out-of-range top_n surfaces as error_type: validation_error.

    Uses the real ``SearchFlights.search`` (not a mock) so the assertion
    actually exercises the library's own bound-check ``ValueError`` — see
    ``fli/search/flights.py`` — flowing through the shared
    ``fli.core.errors.classify_error``, the same path the CLI's
    ``--format json`` output goes through. No mocking means no accidental
    network call either: the bound check raises before ``_fetch_flights``
    is ever reached.
    """

    @pytest.mark.parametrize("bad_top_n", [0, 11])
    def test_search_flights_rejects_out_of_range_top_n(self, bad_top_n):
        result = _execute_flight_search(_round_trip_params(top_n=bad_top_n))

        assert result["success"] is False
        assert result["error_type"] == "validation_error"
        assert result["retryable"] is False
        assert "top_n" in result["error"]

    @pytest.mark.parametrize("bad_top_n", [0, 11])
    def test_get_booking_options_rejects_out_of_range_top_n(self, bad_top_n):
        result = _execute_booking_options(_round_trip_params(top_n=bad_top_n), flight_numbers=None)

        assert result["success"] is False
        assert result["error_type"] == "validation_error"
        assert result["retryable"] is False
        assert "top_n" in result["error"]
