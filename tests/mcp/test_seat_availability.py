"""Tests for the get_seat_availability MCP tool.

All tests stub ``_execute_flight_search`` so the probe loop is exercised
offline and deterministically, with no calls to the live Google Flights API.
"""

from __future__ import annotations

from typing import Any

import pytest

from fli.mcp import server
from fli.mcp.server import (
    FlightSearchParams,
    _execute_seat_availability,
    _get_seat_availability_from_params,
    _serialized_flight_idents,
)


def _flight(price: float, *legs: tuple[str, str]) -> dict[str, Any]:
    """Build a serialized flight result carrying ``legs`` of (airline, number)."""
    return {
        "price": price,
        "legs": [{"airline_code": code, "flight_number": number} for code, number in legs],
    }


def _params(**overrides: Any) -> FlightSearchParams:
    base = {
        "origin": "MEX",
        "destination": "BCN",
        "departure_date": "2026-09-09",
    }
    base.update(overrides)
    return FlightSearchParams(**base)


def _stub_search(monkeypatch, responses: dict[int, dict[str, Any]], calls: list[int] | None = None):
    """Route ``_execute_flight_search`` to canned responses keyed by party size."""

    def _fake(params: FlightSearchParams) -> dict[str, Any]:
        if calls is not None:
            calls.append(params.passengers)
        return responses.get(params.passengers, {"success": True, "flights": []})

    monkeypatch.setattr(server, "_execute_flight_search", _fake)


class TestSerializedFlightIdents:
    def test_joins_airline_and_number_per_leg(self):
        flight = _flight(100.0, ("AM", "37"), ("UX", "7703"))
        assert _serialized_flight_idents(flight) == ["AM37", "UX7703"]

    def test_uppercases_and_tolerates_missing_fields(self):
        assert _serialized_flight_idents({"legs": [{"airline_code": "am"}]}) == ["AM"]
        assert _serialized_flight_idents({}) == []


class TestFareLadder:
    def test_reports_ladder_and_confirmed_floor(self, monkeypatch):
        # Party sizes 1-3 price; 4 comes back empty, so the floor is 3.
        _stub_search(
            monkeypatch,
            {
                1: {"success": True, "flights": [_flight(2369.0, ("AM", "37"))]},
                2: {"success": True, "flights": [_flight(5489.0, ("AM", "37"))]},
                3: {"success": True, "flights": [_flight(10303.0, ("AM", "37"))]},
            },
        )

        result = _execute_seat_availability(_params(), ["AM37"], 9)

        assert result["success"] is True
        assert result["max_bookable"] == 3
        assert result["capped_by_probe_limit"] is False
        assert [step["passengers"] for step in result["fare_ladder"]] == [1, 2, 3]
        assert result["fare_ladder"][0]["price_per_passenger"] == 2369.0
        assert result["fare_ladder"][1]["price_per_passenger"] == 2744.5
        assert result["fare_ladder"][2]["price_per_passenger"] == pytest.approx(3434.33)

    def test_stops_at_first_confirmed_miss(self, monkeypatch):
        calls: list[int] = []
        _stub_search(
            monkeypatch,
            {1: {"success": True, "flights": [_flight(500.0, ("AM", "37"))]}},
            calls=calls,
        )

        result = _execute_seat_availability(_params(), ["AM37"], 9)

        assert result["max_bookable"] == 1
        # Party size 2 is retried once, then the loop stops rather than
        # walking all the way to 9.
        assert calls == [1, 2, 2]

    def test_flags_when_probe_limit_is_the_binding_constraint(self, monkeypatch):
        _stub_search(
            monkeypatch,
            {n: {"success": True, "flights": [_flight(100.0 * n, ("IB", "308"))]} for n in (1, 2)},
        )

        result = _execute_seat_availability(_params(), ["IB308"], 2)

        assert result["max_bookable"] == 2
        assert result["capped_by_probe_limit"] is True


class TestRateLimitRetry:
    def test_empty_response_is_confirmed_before_being_believed(self, monkeypatch):
        """A single empty response must not be read as sold-out inventory."""
        seen: list[int] = []

        def _fake(params: FlightSearchParams) -> dict[str, Any]:
            seen.append(params.passengers)
            # Party size 2 comes back empty the first time (as a rate-limited
            # response does) but succeeds on the confirming retry.
            if params.passengers == 2 and seen.count(2) == 1:
                return {"success": True, "flights": []}
            if params.passengers <= 2:
                return {
                    "success": True,
                    "flights": [_flight(100.0 * params.passengers, ("AM", "37"))],
                }
            return {"success": True, "flights": []}

        monkeypatch.setattr(server, "_execute_flight_search", _fake)

        result = _execute_seat_availability(_params(), ["AM37"], 3)

        assert result["max_bookable"] == 2, "retry should have recovered party size 2"
        assert seen.count(2) == 2


class TestFlightSelection:
    def test_locks_onto_top_result_when_no_flight_numbers_given(self, monkeypatch):
        _stub_search(
            monkeypatch,
            {
                1: {
                    "success": True,
                    "flights": [_flight(300.0, ("AM", "37")), _flight(400.0, ("IB", "308"))],
                },
                # At party size 2 the cheaper flight is gone; the probe must
                # not silently drift onto the other itinerary.
                2: {"success": True, "flights": [_flight(800.0, ("IB", "308"))]},
            },
        )

        result = _execute_seat_availability(_params(), None, 9)

        assert result["flight"] == ["AM37"]
        assert result["max_bookable"] == 1

    def test_matches_multi_leg_itinerary(self, monkeypatch):
        _stub_search(
            monkeypatch,
            {1: {"success": True, "flights": [_flight(4344.0, ("AM", "1"), ("UX", "7703"))]}},
        )

        result = _execute_seat_availability(_params(), ["am1", "UX 7703"], 1)

        assert result["max_bookable"] == 1
        assert result["flight"] == ["AM1", "UX7703"]


class TestErrorPropagation:
    def test_search_failure_is_surfaced_not_read_as_sold_out(self, monkeypatch):
        _stub_search(
            monkeypatch,
            {
                1: {"success": True, "flights": [_flight(100.0, ("AM", "37"))]},
                2: {"success": False, "error": "Search failed: rate limited"},
            },
        )

        result = _execute_seat_availability(_params(), ["AM37"], 9)

        assert result["success"] is False
        assert "rate limited" in result["error"]
        # Partial findings are kept so the caller still learns 1 seat priced.
        assert len(result["fare_ladder"]) == 1


class TestParamsEntryPoint:
    def test_from_params_helper_matches_direct_call(self, monkeypatch):
        _stub_search(
            monkeypatch,
            {1: {"success": True, "flights": [_flight(2369.0, ("AM", "37"))]}},
        )

        result = _get_seat_availability_from_params(_params(), ["AM37"], 1)

        assert result["success"] is True
        assert result["max_bookable"] == 1
