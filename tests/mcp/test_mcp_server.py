"""Test MCP server functionality.

The four search tests below talk to Google for real, including from CI
runners. A transient search-page variant, a timeout or a hard rejection is a
property of the network that day rather than of this code, so
:func:`assert_live_search` reports those as skips — while every other failure,
and every assertion on the success path, still fails the build.
"""

from datetime import datetime, timedelta

import pytest

from fli.mcp.server import (
    DateSearchParams,
    FlightSearchParams,
)
from fli.mcp.server import (
    _search_dates_from_params as search_dates_fn,
)
from fli.mcp.server import (
    _search_flights_from_params as search_flights_fn,
)


def get_future_date(days: int = 30) -> str:
    """Generate a future date string in YYYY-MM-DD format."""
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


# Phrases that only a transport-level failure produces: the page arrived
# without its payload, Google refused the call, or the request never completed.
# Each one is a literal string from `fli.search.exceptions` / `_tfs` / the
# client's error wrapper, not a generic word.
#
# Deliberately narrow on both sides. The MCP layer wraps every exception as
# "Search failed: ...", so matching that prefix would mask real bugs; and a
# bare "http" marker matched the `https://errors.pydantic.dev/...` URL that
# every pydantic ValidationError ends with, which would have skipped a decoder
# regression instead of failing it.
TRANSPORT_FAILURES = (
    "no ds:1 payload",  # SearchParseError / the date sweep's _NO_PAYLOAD
    "declined the request",  # SearchRejectedError (error 13)
    "timed out talking to google flights",  # SearchTimeoutError
    "could not reach google flights",  # SearchConnectionError
    "returned an error response",  # SearchHTTPError (non-2xx status)
    "every date in the range failed",  # the date sweep's total-failure error
    "no date in the range could be priced",  # same, when the breaker tripped
)

# Phrases that mean we failed to understand a response we did receive. These
# must fail even though they can co-occur with transport wording.
PARSE_FAILURES = (
    "validationerror",
    "errors.pydantic.dev",
    "flight rows",  # "Parsed 0/N flight rows …"
    "shape changed",
    "shape may have changed",
)


def assert_live_search(result: dict, *, results_key: str, trip_type: str) -> None:
    """Assert a live search result's shape, skipping on transport failures.

    The error response shape carries no ``trip_type``/``count``, so asserting
    those unconditionally turns any transient failure into a red build. A
    decoder regression, on the other hand, must always fail — so a message that
    mentions parsing rows is never skipped, whatever else it says.
    """
    assert isinstance(result, dict)
    assert "success" in result
    assert results_key in result

    if not result["success"]:
        # Error shape: a non-empty message and an empty result list.
        assert "error" in result
        assert isinstance(result["error"], str) and result["error"]
        assert result[results_key] == []
        error = result["error"].lower()
        parse_failure = any(marker in error for marker in PARSE_FAILURES)
        transport_failure = any(marker in error for marker in TRANSPORT_FAILURES)
        if transport_failure and not parse_failure:
            pytest.skip(f"live search unavailable: {result['error']}")
        raise AssertionError(f"search failed for a non-transport reason: {result['error']}")

    assert "trip_type" in result, f"success response is missing trip_type: {sorted(result)}"
    assert result["trip_type"] == trip_type
    assert "count" in result
    assert isinstance(result[results_key], list)


class TestMCPServer:
    """Test suite for MCP server tools."""

    @pytest.mark.live
    def test_search_flights_one_way(self):
        """Test one-way flight search."""
        params = FlightSearchParams(
            origin="JFK",
            destination="LHR",
            departure_date=get_future_date(30),
            cabin_class="ECONOMY",
            max_stops="ANY",
            sort_by="CHEAPEST",
        )

        result = search_flights_fn(params)

        assert_live_search(result, results_key="flights", trip_type="ONE_WAY")

    @pytest.mark.live
    def test_search_flights_round_trip(self):
        """Test round-trip flight search."""
        params = FlightSearchParams(
            origin="LAX",
            destination="JFK",
            departure_date=get_future_date(30),
            return_date=get_future_date(37),
            departure_window="8-20",
            airlines=["AA", "DL"],
            cabin_class="BUSINESS",
            max_stops="NON_STOP",
            sort_by="DURATION",
        )

        result = search_flights_fn(params)

        assert_live_search(result, results_key="flights", trip_type="ROUND_TRIP")

    @pytest.mark.live
    def test_search_dates_one_way(self):
        """Test one-way date search."""
        start_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        end_date = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")

        params = DateSearchParams(
            origin="JFK",
            destination="LHR",
            start_date=start_date,
            end_date=end_date,
            is_round_trip=False,
            cabin_class="ECONOMY",
            max_stops="ANY",
            sort_by_price=True,
        )

        result = search_dates_fn(params)

        assert_live_search(result, results_key="dates", trip_type="ONE_WAY")
        if result["success"]:
            assert "date_range" in result

    @pytest.mark.live
    def test_search_dates_round_trip(self):
        """Test round-trip date search."""
        start_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        end_date = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")

        params = DateSearchParams(
            origin="LAX",
            destination="MIA",
            start_date=start_date,
            end_date=end_date,
            trip_duration=7,
            is_round_trip=True,
            airlines=["AA", "B6"],
            cabin_class="PREMIUM_ECONOMY",
            max_stops="ONE_STOP",
            departure_window="6-22",
            sort_by_price=True,
        )

        result = search_dates_fn(params)

        assert_live_search(result, results_key="dates", trip_type="ROUND_TRIP")
        if result["success"]:
            assert result["duration"] == 7

    def test_invalid_airport_code(self):
        """Test error handling for invalid airport code."""
        params = FlightSearchParams(
            origin="INVALID", destination="LHR", departure_date=get_future_date(30)
        )

        result = search_flights_fn(params)

        assert isinstance(result, dict)
        assert result["success"] is False
        assert "error" in result
        assert "Invalid airport code" in result["error"]
        assert result["flights"] == []

    def test_invalid_departure_window(self):
        """Test error handling for invalid departure window."""
        params = FlightSearchParams(
            origin="JFK",
            destination="LHR",
            departure_date=get_future_date(30),
            departure_window="invalid-time",
        )

        result = search_flights_fn(params)

        assert isinstance(result, dict)
        assert result["success"] is False
        assert "error" in result
        assert "time range" in result["error"].lower()
        assert result["flights"] == []

    def test_invalid_cabin_class(self):
        """Test error handling for invalid cabin class."""
        params = FlightSearchParams(
            origin="JFK",
            destination="LHR",
            departure_date=get_future_date(30),
            cabin_class="INVALID_CLASS",
        )

        result = search_flights_fn(params)

        assert isinstance(result, dict)
        assert result["success"] is False
        assert "error" in result
        assert "cabin_class" in result["error"].lower()
        assert result["flights"] == []

    def test_invalid_max_stops(self):
        """Test error handling for invalid max stops."""
        params = FlightSearchParams(
            origin="JFK",
            destination="LHR",
            departure_date=get_future_date(30),
            max_stops="INVALID_STOPS",
        )

        result = search_flights_fn(params)

        assert isinstance(result, dict)
        assert result["success"] is False
        assert "error" in result
        assert "max_stops" in result["error"].lower()
        assert result["flights"] == []

    def test_invalid_airline_code(self):
        """Test error handling for invalid airline code."""
        params = FlightSearchParams(
            origin="JFK",
            destination="LHR",
            departure_date=get_future_date(30),
            airlines=["INVALID_AIRLINE"],
        )

        result = search_flights_fn(params)

        assert isinstance(result, dict)
        assert result["success"] is False
        assert "error" in result
        assert "airline" in result["error"].lower()
        assert result["flights"] == []

    def test_flight_search_params_validation(self):
        """Test FlightSearchParams validation."""
        future_date = get_future_date(30)
        params = FlightSearchParams(origin="JFK", destination="LHR", departure_date=future_date)
        assert params.origin == "JFK"
        assert params.destination == "LHR"
        assert params.departure_date == future_date
        assert params.cabin_class == "ECONOMY"  # default
        assert params.max_stops == "ANY"  # default
        assert params.sort_by == "CHEAPEST"  # default

    def test_date_search_params_validation(self):
        """Test DateSearchParams validation."""
        start_date = get_future_date(30)
        end_date = get_future_date(60)
        params = DateSearchParams(
            origin="JFK",
            destination="LHR",
            start_date=start_date,
            end_date=end_date,
        )
        assert params.origin == "JFK"
        assert params.destination == "LHR"
        assert params.start_date == start_date
        assert params.end_date == end_date
        assert params.trip_duration == 3  # default
        assert params.is_round_trip is False  # default
        assert params.cabin_class == "ECONOMY"  # default
        assert params.max_stops == "ANY"  # default
        assert params.sort_by_price is False  # default
