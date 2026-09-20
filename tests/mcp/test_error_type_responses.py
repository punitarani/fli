"""Every MCP error response carries error_type + retryable (issue #234 follow-up).

Additive contract: `success`, `error`, and the tool's existing empty-result
key (`flights` / `dates` / `options`) must be byte-identical to what they
were before this change — these tests assert the new keys are *added*, not
that the old ones changed.
"""

from __future__ import annotations

import pytest

from fli.mcp.server import (
    DateSearchParams,
    FlightSearchParams,
    _execute_booking_options,
    _execute_date_search,
    _execute_flight_search,
    _find_airports_impl,
)
from fli.search.exceptions import (
    SearchClientError,
    SearchConnectionError,
    SearchHTTPError,
    SearchParseError,
    SearchRejectedError,
    SearchTimeoutError,
    SearchUnsupportedError,
)

PINNED_TODAY = "2026-01-01"


@pytest.fixture(autouse=True)
def _pinned_clock(pin_today):
    """Freeze "today" well before every date literal in this module."""
    pin_today(PINNED_TODAY)


def _raiser(exc: BaseException):
    def _fn(*args, **kwargs):
        raise exc

    return _fn


# (exception instance, expected error_type, expected retryable)
_SEARCH_CLIENT_ERROR_CASES = [
    pytest.param(SearchTimeoutError("slow"), "timeout_error", True, id="timeout"),
    pytest.param(SearchConnectionError("no route"), "connection_error", True, id="connection"),
    pytest.param(
        SearchHTTPError("bad gateway", status_code=502), "http_error", True, id="http-5xx"
    ),
    pytest.param(SearchHTTPError("forbidden", status_code=403), "http_error", False, id="http-4xx"),
    pytest.param(SearchRejectedError(13), "rejected_error", False, id="rejected"),
    pytest.param(
        SearchUnsupportedError("multi-city unsupported"),
        "unsupported_error",
        False,
        id="unsupported",
    ),
    pytest.param(SearchParseError("no ds:1 payload"), "blocked_error", False, id="blocked"),
    pytest.param(SearchClientError("generic failure"), "search_error", False, id="generic"),
    pytest.param(RuntimeError("bug"), "unexpected_error", False, id="unexpected"),
]


class TestSearchFlightsErrorType:
    @pytest.fixture
    def params(self):
        return FlightSearchParams(origin="JFK", destination="LHR", departure_date="2026-12-01")

    @pytest.mark.parametrize("exc,expected_type,expected_retryable", _SEARCH_CLIENT_ERROR_CASES)
    def test_search_error_types(self, monkeypatch, params, exc, expected_type, expected_retryable):
        monkeypatch.setattr("fli.mcp.server.SearchFlights.search", _raiser(exc))
        result = _execute_flight_search(params)
        assert result["success"] is False
        assert result["error_type"] == expected_type
        assert result["retryable"] is expected_retryable
        assert result["flights"] == []  # existing field untouched

    def test_http_error_carries_http_status(self, monkeypatch, params):
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.search",
            _raiser(SearchHTTPError("rate limited", status_code=429)),
        )
        result = _execute_flight_search(params)
        assert result["error_type"] == "http_error"
        assert result["retryable"] is True
        assert result["http_status"] == 429

    def test_http_error_omits_http_status_when_unknown(self, monkeypatch, params):
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.search",
            _raiser(SearchHTTPError("mystery failure", status_code=None)),
        )
        result = _execute_flight_search(params)
        assert result["error_type"] == "http_error"
        assert "http_status" not in result

    def test_bad_airport_code_is_validation_error(self):
        """An unresolvable origin raises fli.core.parsers.ParseError -> validation_error."""
        params = FlightSearchParams(origin="ZZZZ", destination="LHR", departure_date="2026-12-01")
        result = _execute_flight_search(params)
        assert result["success"] is False
        assert result["error_type"] == "validation_error"
        assert result["retryable"] is False

    def test_too_many_travelers_is_validation_error(self):
        """9 adults + 5 children exceeds the 1-9 total-traveler cap -> pydantic ValidationError."""
        params = FlightSearchParams(
            origin="JFK",
            destination="LHR",
            departure_date="2026-12-01",
            passengers=9,
            children=5,
        )
        result = _execute_flight_search(params)
        assert result["success"] is False
        assert result["error_type"] == "validation_error"
        assert result["retryable"] is False

    def test_successful_response_has_no_error_type(self, monkeypatch, params):
        monkeypatch.setattr("fli.mcp.server.SearchFlights.search", lambda self, *a, **k: None)
        result = _execute_flight_search(params)
        assert result["success"] is True
        assert "error_type" not in result
        assert "retryable" not in result


class TestSearchDatesErrorType:
    @pytest.fixture
    def params(self):
        return DateSearchParams(
            origin="JFK", destination="LHR", start_date="2026-03-01", end_date="2026-03-10"
        )

    @pytest.mark.parametrize("exc,expected_type,expected_retryable", _SEARCH_CLIENT_ERROR_CASES)
    def test_date_search_error_types(
        self, monkeypatch, params, exc, expected_type, expected_retryable
    ):
        monkeypatch.setattr("fli.mcp.server.SearchDates.search", _raiser(exc))
        result = _execute_date_search(params)
        assert result["success"] is False
        assert result["error_type"] == expected_type
        assert result["retryable"] is expected_retryable
        assert result["dates"] == []

    def test_over_93_date_cap_is_validation_error(self):
        """SearchDates.search() raises a bare ValueError for >93-date ranges — no mocking needed."""
        params = DateSearchParams(
            origin="JFK", destination="LHR", start_date="2026-02-01", end_date="2026-12-01"
        )
        result = _execute_date_search(params)
        assert result["success"] is False
        assert "93-date limit" in result["error"]  # existing message untouched
        assert result["error_type"] == "validation_error"
        assert result["retryable"] is False

    def test_bad_airport_code_is_validation_error(self):
        params = DateSearchParams(
            origin="ZZZZ", destination="LHR", start_date="2026-03-01", end_date="2026-03-10"
        )
        result = _execute_date_search(params)
        assert result["error_type"] == "validation_error"
        assert result["retryable"] is False

    def test_successful_response_has_no_error_type(self, monkeypatch, params):
        monkeypatch.setattr("fli.mcp.server.SearchDates.search", lambda self, *a, **k: None)
        result = _execute_date_search(params)
        assert result["success"] is True
        assert "error_type" not in result


class TestBookingOptionsErrorType:
    @pytest.fixture
    def params(self):
        return FlightSearchParams(origin="JFK", destination="LHR", departure_date="2026-12-01")

    def _flight(self):
        from unittest.mock import MagicMock

        leg = MagicMock()
        airline = MagicMock()
        airline.name = "BA"
        leg.airline = airline
        leg.flight_number = "178"
        flight = MagicMock()
        flight.legs = [leg]
        flight.price = 400.0
        flight.currency = "USD"
        flight.booking_token = "tok"
        return flight

    def test_no_match_is_validation_error(self, monkeypatch, params):
        """No exception at all — a deterministic "you passed bad flight_numbers" case."""
        flight = self._flight()
        monkeypatch.setattr("fli.mcp.server.SearchFlights.search", lambda me, *a, **k: [flight])
        result = _execute_booking_options(params, ["ZZ999"])
        assert result["success"] is False
        assert result["available_flights"] == [["BA178"]]  # existing field untouched
        assert result["error_type"] == "validation_error"
        assert result["retryable"] is False

    @pytest.mark.parametrize("exc,expected_type,expected_retryable", _SEARCH_CLIENT_ERROR_CASES)
    def test_get_booking_options_error_types(
        self, monkeypatch, params, exc, expected_type, expected_retryable
    ):
        flight = self._flight()
        monkeypatch.setattr("fli.mcp.server.SearchFlights.search", lambda me, *a, **k: [flight])
        monkeypatch.setattr("fli.mcp.server.SearchFlights.get_booking_options", _raiser(exc))
        result = _execute_booking_options(params, None)
        assert result["success"] is False
        assert result["error_type"] == expected_type
        assert result["retryable"] is expected_retryable
        assert result["options"] == []

    def test_successful_response_has_no_error_type(self, monkeypatch, params):
        flight = self._flight()
        monkeypatch.setattr("fli.mcp.server.SearchFlights.search", lambda me, *a, **k: [flight])
        monkeypatch.setattr(
            "fli.mcp.server.SearchFlights.get_booking_options", lambda me, *a, **k: []
        )
        result = _execute_booking_options(params, None)
        assert result["success"] is True
        assert "error_type" not in result


class TestFindAirportsErrorType:
    def test_unexpected_failure_is_unexpected_error(self, monkeypatch):
        monkeypatch.setattr(
            "fli.mcp.server.search_airports", _raiser(RuntimeError("index corrupted"))
        )
        result = _find_airports_impl("new york")
        assert result["success"] is False
        assert result["error_type"] == "unexpected_error"
        assert result["retryable"] is False

    def test_successful_response_has_no_error_type(self):
        result = _find_airports_impl("new york")
        assert result["success"] is True
        assert "error_type" not in result
