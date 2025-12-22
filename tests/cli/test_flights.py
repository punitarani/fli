"""Tests for the flights CLI command."""

from datetime import datetime, timedelta

import pytest
from typer.testing import CliRunner

from fli.cli.main import app
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
    assert result.exit_code == 2
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
