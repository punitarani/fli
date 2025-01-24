from datetime import datetime

import pytest
from typer.testing import CliRunner

from fli.cli.main import app


@pytest.fixture
def runner():
    """Return a CliRunner instance."""
    return CliRunner()


def test_basic_search(runner, mock_search_flights, mock_console):
    """Test basic flight search with required parameters."""
    result = runner.invoke(app, ["search", "JFK", "LAX", datetime.now().strftime("%Y-%m-%d")])
    assert result.exit_code == 0
    mock_search_flights.search.assert_called_once()


def test_search_with_time_filter(runner, mock_search_flights, mock_console):
    """Test search with time filter."""
    result = runner.invoke(
        app,
        [
            "search",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "--time",
            "6-20",
        ],
    )
    assert result.exit_code == 0
    mock_search_flights.search.assert_called_once()


def test_search_with_airlines(runner, mock_search_flights, mock_console):
    """Test search with airline filter."""
    result = runner.invoke(
        app,
        [
            "search",
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


def test_search_with_seat_type(runner, mock_search_flights, mock_console):
    """Test search with seat type."""
    result = runner.invoke(
        app,
        [
            "search",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "--class",
            "BUSINESS",
        ],
    )
    assert result.exit_code == 0
    mock_search_flights.search.assert_called_once()


def test_search_with_stops(runner, mock_search_flights, mock_console):
    """Test search with stops filter."""
    result = runner.invoke(
        app,
        [
            "search",
            "JFK",
            "LAX",
            datetime.now().strftime("%Y-%m-%d"),
            "--stops",
            "NON_STOP",
        ],
    )
    assert result.exit_code == 0
    mock_search_flights.search.assert_called_once()


def test_search_invalid_airport(runner, mock_search_flights, mock_console):
    """Test search with invalid airport code."""
    result = runner.invoke(
        app,
        ["search", "XXX", "LAX", datetime.now().strftime("%Y-%m-%d")],
    )
    assert result.exit_code == 1
    assert "Error" in result.stdout


def test_search_invalid_date(runner, mock_search_flights, mock_console):
    """Test search with invalid date format."""
    result = runner.invoke(app, ["search", "JFK", "LAX", "2024-13-45"])
    assert result.exit_code == 2
    assert "Error" in result.stdout


def test_search_no_results(runner, mock_search_flights, mock_console):
    """Test search with no results."""
    # Override the mock to return no results
    mock_search_flights.search.return_value = []

    result = runner.invoke(
        app,
        ["search", "JFK", "LAX", datetime.now().strftime("%Y-%m-%d")],
    )
    assert result.exit_code == 1
    assert "No flights found" in result.stdout
