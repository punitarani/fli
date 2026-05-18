"""Unit tests for MCP server serialization helpers and error propagation.

Targets functions that are only reached via integration tests in the existing
suite: _airline_code, _serialize_flight_leg, _serialize_layover,
_flight_extras, and the bare-except error path in _execute_flight_search.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from fli.mcp.server import (
    FlightSearchParams,
    _airline_code,
    _execute_flight_search,
    _flight_extras,
    _serialize_flight_leg,
    _serialize_layover,
)


def _make_raiser(exc: BaseException):
    """Return a callable that unconditionally raises ``exc``."""

    def _raiser(*args, **kwargs):
        raise exc

    return _raiser


class TestAirlineCode:
    def test_enum_with_leading_underscore_stripped(self):
        airline = MagicMock()
        airline.name = "_2B"
        assert _airline_code(airline) == "2B"

    def test_plain_enum_name_unchanged(self):
        airline = MagicMock()
        airline.name = "DL"
        assert _airline_code(airline) == "DL"

    def test_plain_string_passthrough(self):
        # Strings have no `.name` attribute, so str(airline) is used.
        assert _airline_code("AA") == "AA"


class TestSerializeFlightLeg:
    def _make_leg(self, **overrides):
        leg = MagicMock()
        leg.departure_airport = "JFK"
        leg.arrival_airport = "LHR"
        leg.departure_datetime = None
        leg.arrival_datetime = None
        leg.duration = 420
        leg.airline = "AA"
        leg.flight_number = "100"
        leg.departure_airport_name = None
        leg.arrival_airport_name = None
        leg.operating_airline = None
        leg.aircraft = None
        leg.legroom = None
        leg.overnight = False
        leg.amenities = None
        for k, v in overrides.items():
            setattr(leg, k, v)
        return leg

    def test_required_fields_always_present(self):
        leg = self._make_leg()
        result = _serialize_flight_leg(leg)
        for key in (
            "departure_airport",
            "arrival_airport",
            "departure_time",
            "arrival_time",
            "duration",
            "airline",
            "airline_code",
            "flight_number",
        ):
            assert key in result

    def test_none_optional_fields_excluded(self):
        leg = self._make_leg()
        result = _serialize_flight_leg(leg)
        assert "departure_airport_name" not in result
        assert "arrival_airport_name" not in result
        assert "operating_airline" not in result
        assert "aircraft" not in result
        assert "legroom" not in result

    def test_overnight_true_included(self):
        leg = self._make_leg(overnight=True)
        result = _serialize_flight_leg(leg)
        assert result.get("overnight") is True

    def test_overnight_false_excluded(self):
        leg = self._make_leg(overnight=False)
        result = _serialize_flight_leg(leg)
        assert "overnight" not in result

    def test_operating_airline_included_when_set(self):
        op = MagicMock()
        op.name = "B6"
        leg = self._make_leg(operating_airline=op)
        result = _serialize_flight_leg(leg)
        assert result["operating_airline"] == "B6"

    def test_amenities_included_with_truthy_fields(self):
        from fli.models import Amenities

        leg = self._make_leg(amenities=Amenities(wifi=True))
        result = _serialize_flight_leg(leg)
        assert "amenities" in result
        assert result["amenities"]["wifi"] is True

    def test_amenities_excluded_when_none(self):
        leg = self._make_leg(amenities=None)
        result = _serialize_flight_leg(leg)
        assert "amenities" not in result

    def test_amenities_excluded_when_all_fields_are_none(self):
        from fli.models import Amenities

        leg = self._make_leg(amenities=Amenities())
        result = _serialize_flight_leg(leg)
        # model_dump(exclude_none=True) on an all-None Amenities → empty dict → not included
        assert "amenities" not in result


class TestSerializeLayover:
    def _make_layover(self, **overrides):
        lo = MagicMock()
        lo.airport = "FRA"
        lo.duration = 90
        lo.overnight = False
        lo.change_of_airport = False
        for k, v in overrides.items():
            setattr(lo, k, v)
        return lo

    def test_airport_and_duration_always_present(self):
        lo = self._make_layover()
        result = _serialize_layover(lo)
        assert "airport" in result
        assert result["duration"] == 90

    def test_overnight_true_included(self):
        lo = self._make_layover(overnight=True)
        result = _serialize_layover(lo)
        assert result.get("overnight") is True

    def test_overnight_false_excluded(self):
        lo = self._make_layover(overnight=False)
        result = _serialize_layover(lo)
        assert "overnight" not in result

    def test_change_of_airport_true_included(self):
        lo = self._make_layover(change_of_airport=True)
        result = _serialize_layover(lo)
        assert result.get("change_of_airport") is True

    def test_change_of_airport_false_excluded(self):
        lo = self._make_layover(change_of_airport=False)
        result = _serialize_layover(lo)
        assert "change_of_airport" not in result


class TestFlightExtras:
    def _make_flight(self, **overrides):
        f = MagicMock()
        f.primary_airline_name = None
        f.self_transfer = None
        f.mixed_cabin = None
        f.booking_token = None
        f.primary_airline = None
        f.layovers = None
        for k, v in overrides.items():
            setattr(f, k, v)
        return f

    def test_booking_token_included_when_set(self):
        f = self._make_flight(booking_token="tok123")
        result = _flight_extras(f)
        assert result["booking_token"] == "tok123"

    def test_booking_token_excluded_when_empty_string(self):
        f = self._make_flight(booking_token="")
        result = _flight_extras(f)
        assert "booking_token" not in result

    def test_booking_token_excluded_when_none(self):
        f = self._make_flight(booking_token=None)
        result = _flight_extras(f)
        assert "booking_token" not in result

    def test_self_transfer_true_included(self):
        f = self._make_flight(self_transfer=True)
        result = _flight_extras(f)
        assert result.get("self_transfer") is True

    def test_layovers_serialized(self):
        lo = MagicMock()
        lo.airport = "CDG"
        lo.duration = 60
        lo.overnight = False
        lo.change_of_airport = False
        f = self._make_flight(layovers=[lo])
        result = _flight_extras(f)
        assert "layovers" in result
        assert len(result["layovers"]) == 1


class TestExecuteFlightSearchNetworkError:
    """The bare-except in _execute_flight_search must produce a clean error dict."""

    @pytest.fixture
    def valid_params(self):
        return FlightSearchParams(
            origin="JFK",
            destination="LHR",
            departure_date="2026-12-01",
        )

    def test_search_client_error_returns_success_false(self, monkeypatch, valid_params):
        from fli.search.exceptions import SearchClientError

        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.search",
            _make_raiser(SearchClientError("network down")),
        )
        result = _execute_flight_search(valid_params)
        assert result["success"] is False

    def test_exception_message_in_error_field(self, monkeypatch, valid_params):
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.search",
            _make_raiser(RuntimeError("proxy timeout")),
        )
        result = _execute_flight_search(valid_params)
        assert result["error"] == "Search failed: proxy timeout"

    def test_flights_key_is_empty_list_on_error(self, monkeypatch, valid_params):
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.search",
            _make_raiser(RuntimeError("fail")),
        )
        result = _execute_flight_search(valid_params)
        assert result["flights"] == []
