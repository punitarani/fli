"""Tests for the flights CLI command."""

import json
from datetime import datetime, timedelta

import pytest
from typer.testing import CliRunner

from fli.cli.main import app
from fli.models import Airline, Airport, FlightLeg, FlightResult
from fli.models.google_flights.base import TripType


@pytest.fixture
def runner():
    """Return a CliRunner instance."""
    return CliRunner()


def test_basic_flights_search(runner, mock_search_flights, mock_console):
    """Test basic flight search with required parameters."""
    result = runner.invoke(app, ["flights", "JFK", "LAX", datetime.now().strftime("%Y-%m-%d")])
    assert result.exit_code == 0
    mock_search_flights.search.assert_called_once()


def test_flights_with_time_filter(runner, mock_search_flights, mock_console):
    """Test flights search with time filter."""
    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "--time",
            "6-20",
        ],
    )
    assert result.exit_code == 0
    mock_search_flights.search.assert_called_once()


def test_flights_with_airlines(runner, mock_search_flights, mock_console):
    """Test flights search with airline filter."""
    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "-a",
            "DL",
            "-a",
            "UA",
        ],
    )
    assert result.exit_code == 0
    mock_search_flights.search.assert_called_once()


def test_flights_with_cabin_class(runner, mock_search_flights, mock_console):
    """Test flights search with cabin class."""
    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "--class",
            "BUSINESS",
        ],
    )
    assert result.exit_code == 0
    mock_search_flights.search.assert_called_once()


def test_flights_with_stops(runner, mock_search_flights, mock_console):
    """Test flights search with stops filter."""
    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "--stops",
            "NON_STOP",
        ],
    )
    assert result.exit_code == 0
    mock_search_flights.search.assert_called_once()


def test_flights_invalid_airport(runner, mock_search_flights, mock_console):
    """Test flights search with invalid airport code."""
    result = runner.invoke(
        app,
        ["flights", "XXX", "LAX", datetime.now().strftime("%Y-%m-%d")],
    )
    assert result.exit_code == 1
    assert "Error" in result.stdout


def test_flights_invalid_date(runner, mock_search_flights, mock_console):
    """Test flights search with invalid date format."""
    result = runner.invoke(app, ["flights", "JFK", "LAX", "2024-13-45"])
    assert result.exit_code == 1
    assert "Error" in result.output


def test_flights_no_results(runner, mock_search_flights, mock_console):
    """Test flights search with no results."""
    mock_search_flights.search.return_value = []

    result = runner.invoke(
        app,
        ["flights", "JFK", "LAX", datetime.now().strftime("%Y-%m-%d")],
    )
    assert result.exit_code == 1
    assert "No flights found" in result.stdout


def test_basic_round_trip_flights(runner, mock_search_flights, mock_console):
    """Test basic round-trip flight search."""
    outbound_date = datetime.now().strftime("%Y-%m-%d")
    return_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            outbound_date,
            "--return",
            return_date,
        ],
    )
    assert result.exit_code == 0
    mock_search_flights.search.assert_called_once()


def test_round_trip_with_filters(runner, mock_search_flights, mock_console):
    """Test round-trip flights search with additional filters."""
    outbound_date = datetime.now().strftime("%Y-%m-%d")
    return_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            outbound_date,
            "--return",
            return_date,
            "--class",
            "BUSINESS",
            "--stops",
            "NON_STOP",
            "-a",
            "DL",
        ],
    )
    assert result.exit_code == 0
    mock_search_flights.search.assert_called_once()
    args, kwargs = mock_search_flights.search.call_args
    assert args[0].trip_type == TripType.ROUND_TRIP


def test_round_trip_invalid_dates(runner, mock_search_flights, mock_console):
    """Test round-trip flights search with return date before outbound date."""
    outbound_date = datetime.now().strftime("%Y-%m-%d")
    return_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            outbound_date,
            "--return",
            return_date,
        ],
    )
    assert result.exit_code == 1
    assert "Error" in result.stdout


def test_flights_json_output(runner, mock_search_flights, mock_console):
    """Test flights search with JSON output."""
    result = runner.invoke(
        app,
        ["flights", "JFK", "LAX", datetime.now().strftime("%Y-%m-%d"), "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["data_source"] == "google_flights"
    assert payload["search_type"] == "flights"
    assert payload["trip_type"] == "ONE_WAY"
    assert payload["count"] == 2
    assert payload["query"]["origin"] == "JFK"
    assert payload["query"]["destination"] == "LAX"
    assert payload["flights"][0]["price"] == 299.99
    assert payload["flights"][0]["currency"] == "USD"
    assert payload["flights"][0]["legs"][0]["departure_airport"]["code"] == "JFK"
    assert payload["flights"][0]["legs"][0]["arrival_airport"]["code"] == "LAX"


def test_flights_json_round_trip_output(runner, mock_search_flights, mock_console):
    """Test round-trip flights JSON output preserves outbound and return sections."""
    now = datetime.now()
    mock_search_flights.search.return_value = [
        (
            FlightResult(
                price=599.98,
                duration=180,
                stops=0,
                legs=[
                    FlightLeg(
                        airline=Airline.DL,
                        flight_number="DL123",
                        departure_airport=Airport.JFK,
                        arrival_airport=Airport.LAX,
                        departure_datetime=now,
                        arrival_datetime=now + timedelta(hours=3),
                        duration=180,
                    )
                ],
            ),
            FlightResult(
                price=599.98,
                duration=200,
                stops=1,
                legs=[
                    FlightLeg(
                        airline=Airline.DL,
                        flight_number="DL456",
                        departure_airport=Airport.LAX,
                        arrival_airport=Airport.JFK,
                        departure_datetime=now + timedelta(days=7),
                        arrival_datetime=now + timedelta(days=7, hours=4),
                        duration=200,
                    )
                ],
            ),
        )
    ]

    result = runner.invoke(
        app,
        [
            "flights",
            "JFK",
            "LAX",
            now.strftime("%Y-%m-%d"),
            "--return",
            (now + timedelta(days=7)).strftime("%Y-%m-%d"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["trip_type"] == "ROUND_TRIP"
    assert payload["count"] == 1
    assert payload["flights"][0]["price"] == 599.98
    assert payload["flights"][0]["duration"] == 380
    assert payload["flights"][0]["stops"] == 1
    assert payload["flights"][0]["outbound"]["legs"][0]["flight_number"] == "DL123"
    assert payload["flights"][0]["return"]["legs"][0]["flight_number"] == "DL456"


def test_flights_json_invalid_date(runner, mock_search_flights, mock_console):
    """Test flights JSON output for invalid dates."""
    result = runner.invoke(
        app,
        ["flights", "JFK", "LAX", "2024-13-45", "--format", "json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["search_type"] == "flights"
    assert payload["error"]["type"] == "validation_error"
    assert "YYYY-MM-DD" in payload["error"]["message"]


def test_flights_json_no_results(runner, mock_search_flights, mock_console):
    """Test flights JSON output when no results are found."""
    mock_search_flights.search.return_value = []

    result = runner.invoke(
        app,
        ["flights", "JFK", "LAX", datetime.now().strftime("%Y-%m-%d"), "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["count"] == 0
    assert payload["flights"] == []
