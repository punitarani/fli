from datetime import datetime, timedelta

import pytest
from typer.testing import CliRunner

from fli.cli.main import app
from fli.models.google_flights.base import TripType
from fli.search import DatePrice


@pytest.fixture
def runner():
    """Return a CliRunner instance."""
    return CliRunner()


def test_basic_cheap_search(runner, mock_search_dates, mock_console):
    """Test basic cheap flight search (one-way by default)."""
    mock_search_dates.search.return_value = [
        DatePrice(
            date=(datetime.now() + timedelta(days=1),),
            price=299.99,
        ),
    ]
    result = runner.invoke(app, ["cheap", "JFK", "LAX"])
    assert result.exit_code == 0
    mock_search_dates.search.assert_called_once()
    args, _ = mock_search_dates.search.call_args
    assert args[0].trip_type == TripType.ONE_WAY


def test_cheap_with_date_range(runner, mock_search_dates, mock_console):
    """Test cheap search with custom date range."""
    from_date = datetime.now().strftime("%Y-%m-%d")
    to_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    mock_search_dates.search.return_value = [
        DatePrice(
            date=(datetime.now() + timedelta(days=1),),
            price=299.99,
        ),
    ]
    result = runner.invoke(
        app,
        ["cheap", "JFK", "LAX", "--from", from_date, "--to", to_date],
    )
    assert result.exit_code == 0
    mock_search_dates.search.assert_called_once()


def test_cheap_with_days(runner, mock_search_dates, mock_console):
    """Test cheap search with specific days."""
    # Get next Monday
    today = datetime.now()
    days_until_monday = (7 - today.weekday()) % 7
    next_monday = today + timedelta(days=days_until_monday)

    mock_search_dates.search.return_value = [
        DatePrice(
            date=(next_monday,),
            price=299.99,
        ),
    ]
    result = runner.invoke(
        app,
        ["cheap", "JFK", "LAX", "--monday", "--friday"],
    )
    assert result.exit_code == 0
    mock_search_dates.search.assert_called_once()


def test_cheap_with_airlines(runner, mock_search_dates, mock_console):
    """Test cheap search with airline filter."""
    mock_search_dates.search.return_value = [
        DatePrice(
            date=(datetime.now() + timedelta(days=1),),
            price=299.99,
        ),
    ]
    result = runner.invoke(
        app,
        ["cheap", "JFK", "LAX", "-a", "DL", "-a", "UA"],
    )
    assert result.exit_code == 0
    mock_search_dates.search.assert_called_once()


def test_cheap_with_seat_type(runner, mock_search_dates, mock_console):
    """Test cheap search with seat type."""
    mock_search_dates.search.return_value = [
        DatePrice(
            date=(datetime.now() + timedelta(days=1),),
            price=299.99,
        ),
    ]
    result = runner.invoke(
        app,
        ["cheap", "JFK", "LAX", "--class", "BUSINESS"],
    )
    assert result.exit_code == 0
    mock_search_dates.search.assert_called_once()


def test_cheap_with_stops(runner, mock_search_dates, mock_console):
    """Test cheap search with stops filter."""
    mock_search_dates.search.return_value = [
        DatePrice(
            date=(datetime.now() + timedelta(days=1),),
            price=299.99,
        ),
    ]
    result = runner.invoke(
        app,
        ["cheap", "JFK", "LAX", "--stops", "NON_STOP"],
    )
    assert result.exit_code == 0
    mock_search_dates.search.assert_called_once()


def test_cheap_with_time(runner, mock_search_dates, mock_console):
    """Test cheap search with time filter."""
    mock_search_dates.search.return_value = [
        DatePrice(
            date=(datetime.now() + timedelta(days=1),),
            price=299.99,
        ),
    ]
    result = runner.invoke(
        app,
        ["cheap", "JFK", "LAX", "--time", "6-20"],
    )
    assert result.exit_code == 0
    mock_search_dates.search.assert_called_once()


def test_cheap_with_sort(runner, mock_search_dates, mock_console):
    """Test cheap search with sort option."""
    mock_search_dates.search.return_value = [
        DatePrice(
            date=(datetime.now() + timedelta(days=1),),
            price=299.99,
        ),
    ]
    result = runner.invoke(
        app,
        ["cheap", "JFK", "LAX", "--sort"],
    )
    assert result.exit_code == 0
    mock_search_dates.search.assert_called_once()


def test_cheap_invalid_airport(runner, mock_search_dates, mock_console):
    """Test cheap search with invalid airport code."""
    result = runner.invoke(app, ["cheap", "XXX", "LAX"])
    assert result.exit_code == 1
    assert "Error" in result.stdout


def test_cheap_invalid_date_range(runner, mock_search_dates, mock_console):
    """Test cheap search with invalid date range."""
    result = runner.invoke(
        app,
        ["cheap", "JFK", "LAX", "--from", "2024-01-01", "--to", "2023-12-31"],
    )
    assert result.exit_code == 1
    assert "Error" in result.stdout


def test_cheap_no_results(runner, mock_search_dates, mock_console):
    """Test cheap search with no results."""
    # Override the mock to return an empty list
    mock_search_dates.search.return_value = []

    result = runner.invoke(app, ["cheap", "JFK", "LAX"])
    assert result.exit_code == 1
    assert "No flights found" in result.stdout


def test_cheap_round_trip(runner, mock_search_dates, mock_console):
    """Test cheap search with round-trip flag."""
    mock_search_dates.search.return_value = [
        DatePrice(
            date=(
                datetime.now() + timedelta(days=1),
                datetime.now() + timedelta(days=8),
            ),
            price=599.98,
        ),
    ]
    result = runner.invoke(
        app,
        ["cheap", "JFK", "LAX", "--round"],
    )
    assert result.exit_code == 0
    mock_search_dates.search.assert_called_once()
    args, _ = mock_search_dates.search.call_args
    assert args[0].trip_type == TripType.ROUND_TRIP


def test_cheap_round_trip_with_duration(runner, mock_search_dates, mock_console):
    """Test cheap round-trip search with custom duration."""
    mock_search_dates.search.return_value = [
        DatePrice(
            date=(
                datetime.now() + timedelta(days=1),
                datetime.now() + timedelta(days=15),
            ),
            price=599.98,
        ),
    ]
    result = runner.invoke(
        app,
        ["cheap", "JFK", "LAX", "--round", "-d", "14"],
    )
    assert result.exit_code == 0
    mock_search_dates.search.assert_called_once()
    args, _ = mock_search_dates.search.call_args
    assert args[0].trip_type == TripType.ROUND_TRIP
    assert args[0].duration == 14
