"""Test MCP server functionality."""

import pytest
from datetime import datetime, timedelta

from fli.mcp.server import (
    DateSearchParams,
    FlightSearchParams,
    mcp,
    search_dates,
    search_flights,
)


def get_future_date(days: int = 30) -> str:
    """Generate a future date string in YYYY-MM-DD format."""
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


class TestMCPServer:
    """Test suite for MCP server tools."""

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

        result = search_flights.fn(params)

        assert isinstance(result, dict)
        assert "success" in result
        assert "flights" in result
        assert "trip_type" in result

        if result["success"]:
            assert result["trip_type"] == "ONE_WAY"
            assert "count" in result
            assert isinstance(result["flights"], list)

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

        result = search_flights.fn(params)

        assert isinstance(result, dict)
        assert "success" in result
        assert "flights" in result
        assert "trip_type" in result

        if result["success"]:
            assert result["trip_type"] == "ROUND_TRIP"
            assert "count" in result
            assert isinstance(result["flights"], list)

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

        result = search_dates.fn(params)

        assert isinstance(result, dict)
        assert "success" in result
        assert "dates" in result
        assert "trip_type" in result

        if result["success"]:
            assert result["trip_type"] == "ONE_WAY"
            assert "count" in result
            assert "date_range" in result
            assert isinstance(result["dates"], list)

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

        result = search_dates.fn(params)

        assert isinstance(result, dict)
        assert "success" in result
        assert "dates" in result
        assert "trip_type" in result

        if result["success"]:
            assert result["trip_type"] == "ROUND_TRIP"
            assert "count" in result
            assert "duration" in result
            assert result["duration"] == 7
            assert isinstance(result["dates"], list)

    def test_invalid_airport_code(self):
        """Test error handling for invalid airport code."""
        params = FlightSearchParams(
            origin="INVALID", destination="LHR", departure_date=get_future_date(30)
        )

        result = search_flights.fn(params)

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

        result = search_flights.fn(params)

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

        result = search_flights.fn(params)

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

        result = search_flights.fn(params)

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

        result = search_flights.fn(params)

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


class TestMCPProtocol:
    """Test MCP protocol methods to ensure tools are properly exposed."""

    @pytest.mark.asyncio
    async def test_list_tools_returns_expected_tools(self):
        """Test that list_tools returns both search_flights and search_dates tools."""
        tools = await mcp.list_tools()

        tool_names = {tool.name for tool in tools}
        assert "search_flights" in tool_names
        assert "search_dates" in tool_names

    @pytest.mark.asyncio
    async def test_list_tools_returns_tool_objects(self):
        """Test that list_tools returns proper Tool objects with required fields."""
        tools = await mcp.list_tools()

        assert len(tools) >= 2

        for tool in tools:
            assert tool.name is not None
            assert tool.description is not None
            assert tool.inputSchema is not None

    @pytest.mark.asyncio
    async def test_search_flights_tool_has_correct_schema(self):
        """Test that search_flights tool has the expected input schema."""
        tools = await mcp.list_tools()

        search_flights_tool = next(t for t in tools if t.name == "search_flights")

        schema = search_flights_tool.inputSchema
        assert "properties" in schema

        required_params = {"origin", "destination", "departure_date"}
        assert required_params.issubset(set(schema["properties"].keys()))

    @pytest.mark.asyncio
    async def test_search_dates_tool_has_correct_schema(self):
        """Test that search_dates tool has the expected input schema."""
        tools = await mcp.list_tools()

        search_dates_tool = next(t for t in tools if t.name == "search_dates")

        schema = search_dates_tool.inputSchema
        assert "properties" in schema

        required_params = {"origin", "destination", "start_date", "end_date"}
        assert required_params.issubset(set(schema["properties"].keys()))

    @pytest.mark.asyncio
    async def test_tools_have_annotations(self):
        """Test that tools have the expected annotations."""
        tools = await mcp.list_tools()

        for tool in tools:
            if tool.name in {"search_flights", "search_dates"}:
                assert tool.annotations is not None
                assert tool.annotations.readOnlyHint is True
                assert tool.annotations.idempotentHint is True
