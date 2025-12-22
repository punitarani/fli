"""Test MCP server functionality."""

from datetime import datetime, timedelta

from fli.mcp.server import (
    CheapFlightSearchRequest,
    FlightSearchRequest,
    search_cheap_flights,
    search_flights,
)


def get_future_date(days: int = 30) -> str:
    """Generate a future date string in YYYY-MM-DD format."""
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


class TestMCPServer:
    """Test suite for MCP server tools."""

    def test_search_flights_one_way(self):
        """Test one-way flight search."""
        params = FlightSearchRequest(
            from_airport="JFK",
            to_airport="LHR",
            date=get_future_date(30),
            seat_class="ECONOMY",
            stops="ANY",
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
        params = FlightSearchRequest(
            from_airport="LAX",
            to_airport="JFK",
            date=get_future_date(30),
            return_date=get_future_date(37),
            time_range="8-20",
            airlines=["AA", "DL"],
            seat_class="BUSINESS",
            stops="NON_STOP",
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

    def test_search_cheap_flights_one_way(self):
        """Test one-way cheap flight search."""
        start_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        end_date = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")

        params = CheapFlightSearchRequest(
            from_airport="JFK",
            to_airport="LHR",
            from_date=start_date,
            to_date=end_date,
            round_trip=False,
            seat_class="ECONOMY",
            stops="ANY",
            sort_by_price=True,
        )

        result = search_cheap_flights.fn(params)

        assert isinstance(result, dict)
        assert "success" in result
        assert "dates" in result
        assert "trip_type" in result

        if result["success"]:
            assert result["trip_type"] == "ONE_WAY"
            assert "count" in result
            assert "date_range" in result
            assert isinstance(result["dates"], list)

    def test_search_cheap_flights_round_trip(self):
        """Test round-trip cheap flight search."""
        start_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        end_date = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")

        params = CheapFlightSearchRequest(
            from_airport="LAX",
            to_airport="MIA",
            from_date=start_date,
            to_date=end_date,
            duration=7,
            round_trip=True,
            airlines=["AA", "B6"],
            seat_class="PREMIUM_ECONOMY",
            stops="ONE_STOP",
            time_range="6-22",
            days_of_week=["friday", "saturday"],
            sort_by_price=True,
        )

        result = search_cheap_flights.fn(params)

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
        params = FlightSearchRequest(
            from_airport="INVALID", to_airport="LHR", date=get_future_date(30)
        )

        result = search_flights.fn(params)

        assert isinstance(result, dict)
        assert result["success"] is False
        assert "error" in result
        assert "Invalid parameter value" in result["error"]
        assert result["flights"] == []

    def test_invalid_time_range(self):
        """Test error handling for invalid time range."""
        params = FlightSearchRequest(
            from_airport="JFK",
            to_airport="LHR",
            date=get_future_date(30),
            time_range="invalid-time",
        )

        result = search_flights.fn(params)

        assert isinstance(result, dict)
        assert result["success"] is False
        assert "error" in result
        assert "Invalid time range format" in result["error"]
        assert result["flights"] == []

    def test_invalid_seat_class(self):
        """Test error handling for invalid seat class."""
        params = FlightSearchRequest(
            from_airport="JFK",
            to_airport="LHR",
            date=get_future_date(30),
            seat_class="INVALID_CLASS",
        )

        result = search_flights.fn(params)

        assert isinstance(result, dict)
        assert result["success"] is False
        assert "error" in result
        assert "Invalid parameter value" in result["error"]
        assert result["flights"] == []

    def test_invalid_max_stops(self):
        """Test error handling for invalid max stops."""
        params = FlightSearchRequest(
            from_airport="JFK",
            to_airport="LHR",
            date=get_future_date(30),
            stops="INVALID_STOPS",
        )

        result = search_flights.fn(params)

        assert isinstance(result, dict)
        assert result["success"] is False
        assert "error" in result
        assert "Invalid parameter value" in result["error"]
        assert result["flights"] == []

    def test_invalid_airline_code(self):
        """Test error handling for invalid airline code."""
        params = FlightSearchRequest(
            from_airport="JFK",
            to_airport="LHR",
            date=get_future_date(30),
            airlines=["INVALID_AIRLINE"],
        )

        result = search_flights.fn(params)

        assert isinstance(result, dict)
        assert result["success"] is False
        assert "error" in result
        assert "Invalid airline code" in result["error"]
        assert result["flights"] == []

    def test_flight_search_params_validation(self):
        """Test FlightSearchParams validation."""
        # Valid params
        future_date = get_future_date(30)
        params = FlightSearchRequest(from_airport="JFK", to_airport="LHR", date=future_date)
        assert params.from_airport == "JFK"
        assert params.to_airport == "LHR"
        assert params.date == future_date
        assert params.seat_class == "ECONOMY"  # default
        assert params.stops == "ANY"  # default
        assert params.sort_by == "CHEAPEST"  # default

    def test_cheap_flight_search_params_validation(self):
        """Test CheapFlightSearchParams validation."""
        # Valid params
        from_date = get_future_date(30)
        to_date = get_future_date(60)
        params = CheapFlightSearchRequest(
            from_airport="JFK",
            to_airport="LHR",
            from_date=from_date,
            to_date=to_date,
        )
        assert params.from_airport == "JFK"
        assert params.to_airport == "LHR"
        assert params.from_date == from_date
        assert params.to_date == to_date
        assert params.duration == 3  # default
        assert params.round_trip is False  # default
        assert params.seat_class == "ECONOMY"  # default
        assert params.stops == "ANY"  # default
        assert params.sort_by_price is False  # default
