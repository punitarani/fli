"""Every MCP error response carries error_type + retryable (issue #234 follow-up).

Additive contract: `success`, `error`, and the tool's existing empty-result
key (`flights` / `dates` / `options`) must be byte-identical to what they
were before this change — these tests assert the new keys are *added*, not
that the old ones changed.

T10 fix round 3: dates are computed relative to `datetime.now()` at
test-run time rather than pinned to a fixed clock, per the same fix
applied to `tests/core/test_error_type_parity.py` — see that file's
docstring for why a fixed pinned clock paired with fixed future dates is
fragile (it can silently stop exercising the intended code path without
any test failure to flag it).
"""

from __future__ import annotations

from datetime import datetime, timedelta

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

# A single "comfortably in the future, whatever day this runs" date for
# tests that only need *a* valid date (not a specific range).
_FUTURE_DATE = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
_SHORT_RANGE_START = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")
_SHORT_RANGE_END = (datetime.now() + timedelta(days=69)).strftime("%Y-%m-%d")


def _raiser(exc: BaseException):
    def _fn(*args, **kwargs):
        raise exc

    return _fn


# (exception instance, expected error_type, expected retryable)
_SEARCH_CLIENT_ERROR_CASES = [
    pytest.param(SearchTimeoutError("slow"), "timeout", True, id="timeout"),
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
    pytest.param(SearchParseError("no ds:1 payload"), "parse_error", False, id="blocked"),
    pytest.param(SearchClientError("generic failure"), "search_error", False, id="generic"),
    pytest.param(RuntimeError("bug"), "unexpected_error", False, id="unexpected"),
]


class TestSearchFlightsErrorType:
    @pytest.fixture
    def params(self):
        return FlightSearchParams(origin="JFK", destination="LHR", departure_date=_FUTURE_DATE)

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
        params = FlightSearchParams(origin="ZZZZ", destination="LHR", departure_date=_FUTURE_DATE)
        result = _execute_flight_search(params)
        assert result["success"] is False
        assert result["error_type"] == "validation_error"
        assert result["retryable"] is False

    def test_too_many_travelers_is_validation_error(self):
        """9 adults + 5 children exceeds the 1-9 total-traveler cap -> pydantic ValidationError."""
        params = FlightSearchParams(
            origin="JFK",
            destination="LHR",
            departure_date=_FUTURE_DATE,
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
            origin="JFK",
            destination="LHR",
            start_date=_SHORT_RANGE_START,
            end_date=_SHORT_RANGE_END,
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
        """SearchDates.search() raises a bare ValueError for >93-date ranges — no mocking needed.

        Dates are relative to today (150-day range, well over the 93-date
        cap) so this keeps exercising SearchDates.search()'s cap check
        rather than drifting onto a "date in the past" pydantic validator
        that would also report validation_error but prove nothing about
        the cap path — see tests/core/test_error_type_parity.py's
        docstring for the fragile-fixed-date failure mode this avoids.
        """
        today = datetime.now()
        start_date = (today + timedelta(days=10)).strftime("%Y-%m-%d")
        end_date = (today + timedelta(days=10 + 150)).strftime("%Y-%m-%d")
        params = DateSearchParams(
            origin="JFK", destination="LHR", start_date=start_date, end_date=end_date
        )
        result = _execute_date_search(params)
        assert result["success"] is False
        assert "93-date limit" in result["error"]  # existing message untouched
        assert "in the past" not in result["error"]
        assert result["error_type"] == "validation_error"
        assert result["retryable"] is False

    def test_bad_airport_code_is_validation_error(self):
        params = DateSearchParams(
            origin="ZZZZ",
            destination="LHR",
            start_date=_SHORT_RANGE_START,
            end_date=_SHORT_RANGE_END,
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
        return FlightSearchParams(origin="JFK", destination="LHR", departure_date=_FUTURE_DATE)

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
