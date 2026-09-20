"""Tests for the dates CLI command."""

import json
from datetime import datetime, timedelta

import pytest
from typer.testing import CliRunner

from fli.cli.main import app
from fli.models import Airline
from fli.models.google_flights.base import TripType
from fli.search import DatePrice
from fli.search.exceptions import (
    SearchClientError,
    SearchConnectionError,
    SearchHTTPError,
    SearchTimeoutError,
)


@pytest.fixture
def runner():
    """Return a CliRunner instance."""
    return CliRunner()


def test_basic_dates_search(runner, mock_search_dates, mock_console):
    """Test basic dates search (one-way by default)."""
    mock_search_dates.search.return_value = [
        DatePrice(
            date=(datetime.now() + timedelta(days=1),),
            price=299.99,
        ),
    ]
    result = runner.invoke(app, ["dates", "JFK", "LAX"])
    assert result.exit_code == 0
    mock_search_dates.search.assert_called_once()
    args, _ = mock_search_dates.search.call_args
    assert args[0].trip_type == TripType.ONE_WAY


def test_dates_with_passengers(runner, mock_search_dates, mock_console):
    """Test dates search passes adult passenger count into filters."""
    mock_search_dates.search.return_value = []
    result = runner.invoke(app, ["dates", "JFK", "LAX", "--passengers", "2", "--format", "json"])
    assert result.exit_code == 0
    args, _ = mock_search_dates.search.call_args
    assert args[0].passenger_info.adults == 2
    payload = json.loads(result.stdout)
    assert payload["query"]["passengers"] == 2


def test_dates_with_family_passenger_mix(runner, mock_search_dates, mock_console):
    """Test dates search passes the full passenger mix into filters and JSON query echo."""
    mock_search_dates.search.return_value = []
    result = runner.invoke(
        app,
        [
            "dates",
            "JFK",
            "LAX",
            "--passengers",
            "2",
            "--children",
            "1",
            "--infants-in-seat",
            "1",
            "--infants-on-lap",
            "1",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0
    args, _ = mock_search_dates.search.call_args
    assert args[0].passenger_info.adults == 2
    assert args[0].passenger_info.children == 1
    assert args[0].passenger_info.infants_in_seat == 1
    assert args[0].passenger_info.infants_on_lap == 1
    payload = json.loads(result.stdout)
    assert payload["query"]["passengers"] == 2
    assert payload["query"]["children"] == 1
    assert payload["query"]["infants_in_seat"] == 1
    assert payload["query"]["infants_on_lap"] == 1


def test_dates_invalid_passenger_mix_exits_nonzero_with_clean_message(
    runner, mock_search_dates, mock_console
):
    """A passenger mix Google Flights would reject fails cleanly, not with a pydantic dump."""
    result = runner.invoke(
        app,
        ["dates", "JFK", "LAX", "--passengers", "1", "--infants-on-lap", "3"],
    )
    assert result.exit_code == 1
    assert "validation error for" not in result.stdout.lower()
    assert "infants_on_lap" in result.stdout
    mock_search_dates.search.assert_not_called()


def test_dates_invalid_passenger_mix_json_error(runner, mock_search_dates, mock_console):
    """JSON mode surfaces the same passenger-mix error as a clean payload."""
    result = runner.invoke(
        app,
        [
            "dates",
            "JFK",
            "LAX",
            "--passengers",
            "9",
            "--children",
            "1",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert "Total passengers must be between 1 and 9" in payload["error"]["message"]


def test_dates_with_date_range(runner, mock_search_dates, mock_console):
    """Test dates search with custom date range."""
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
        ["dates", "JFK", "LAX", "--from", from_date, "--to", to_date],
    )
    assert result.exit_code == 0
    mock_search_dates.search.assert_called_once()


def test_dates_with_days(runner, mock_search_dates, mock_console):
    """Test dates search with specific days."""
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
        ["dates", "JFK", "LAX", "--monday", "--friday"],
    )
    assert result.exit_code == 0
    mock_search_dates.search.assert_called_once()


def test_dates_with_airlines(runner, mock_search_dates, mock_console):
    """Repeated -a flags resolve to the matching Airline enums on the filter."""
    mock_search_dates.search.return_value = [
        DatePrice(
            date=(datetime.now() + timedelta(days=1),),
            price=299.99,
        ),
    ]
    result = runner.invoke(
        app,
        ["dates", "JFK", "LAX", "-a", "DL", "-a", "UA"],
    )
    assert result.exit_code == 0
    args, _ = mock_search_dates.search.call_args
    assert args[0].airlines == [Airline.DL, Airline.UA]


def test_dates_with_comma_separated_airlines(runner, mock_search_dates, mock_console):
    """Single -a flag with comma-joined codes splits into multiple airlines."""
    mock_search_dates.search.return_value = [
        DatePrice(
            date=(datetime.now() + timedelta(days=1),),
            price=299.99,
        ),
    ]
    result = runner.invoke(
        app,
        ["dates", "JFK", "LAX", "-a", "DL,UA"],
    )
    assert result.exit_code == 0
    args, _ = mock_search_dates.search.call_args
    assert args[0].airlines == [Airline.DL, Airline.UA]


def test_dates_with_cabin_class(runner, mock_search_dates, mock_console):
    """Test dates search with cabin class."""
    mock_search_dates.search.return_value = [
        DatePrice(
            date=(datetime.now() + timedelta(days=1),),
            price=299.99,
        ),
    ]
    result = runner.invoke(
        app,
        ["dates", "JFK", "LAX", "--class", "BUSINESS"],
    )
    assert result.exit_code == 0
    mock_search_dates.search.assert_called_once()


def test_dates_with_stops(runner, mock_search_dates, mock_console):
    """Test dates search with stops filter."""
    mock_search_dates.search.return_value = [
        DatePrice(
            date=(datetime.now() + timedelta(days=1),),
            price=299.99,
        ),
    ]
    result = runner.invoke(
        app,
        ["dates", "JFK", "LAX", "--stops", "NON_STOP"],
    )
    assert result.exit_code == 0
    mock_search_dates.search.assert_called_once()


def test_dates_with_time(runner, mock_search_dates, mock_console):
    """Test dates search with time filter."""
    mock_search_dates.search.return_value = [
        DatePrice(
            date=(datetime.now() + timedelta(days=1),),
            price=299.99,
        ),
    ]
    result = runner.invoke(
        app,
        ["dates", "JFK", "LAX", "--time", "6-20"],
    )
    assert result.exit_code == 0
    mock_search_dates.search.assert_called_once()


def test_dates_with_sort(runner, mock_search_dates, mock_console):
    """Test dates search with sort option."""
    mock_search_dates.search.return_value = [
        DatePrice(
            date=(datetime.now() + timedelta(days=1),),
            price=299.99,
        ),
    ]
    result = runner.invoke(
        app,
        ["dates", "JFK", "LAX", "--sort"],
    )
    assert result.exit_code == 0
    mock_search_dates.search.assert_called_once()


def test_dates_invalid_airport(runner, mock_search_dates, mock_console):
    """Test dates search with invalid airport code."""
    result = runner.invoke(app, ["dates", "XXX", "LAX"])
    assert result.exit_code == 1
    assert "Error" in result.stdout


def test_dates_invalid_date_range(runner, mock_search_dates, mock_console):
    """Test dates search with invalid date range."""
    result = runner.invoke(
        app,
        ["dates", "JFK", "LAX", "--from", "2024-01-01", "--to", "2023-12-31"],
    )
    assert result.exit_code == 1
    assert "Error" in result.stdout


def test_dates_no_results(runner, mock_search_dates, mock_console):
    """Test dates search with no results."""
    mock_search_dates.search.return_value = []

    result = runner.invoke(app, ["dates", "JFK", "LAX"])
    assert result.exit_code == 1
    assert "No flights found" in result.stdout


def test_dates_round_trip(runner, mock_search_dates, mock_console):
    """Test dates search with round-trip flag."""
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
        ["dates", "JFK", "LAX", "--round"],
    )
    assert result.exit_code == 0
    mock_search_dates.search.assert_called_once()
    args, _ = mock_search_dates.search.call_args
    assert args[0].trip_type == TripType.ROUND_TRIP


def test_dates_round_trip_with_duration(runner, mock_search_dates, mock_console):
    """Test dates round-trip search with custom duration."""
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
        ["dates", "JFK", "LAX", "--round", "-d", "14"],
    )
    assert result.exit_code == 0
    mock_search_dates.search.assert_called_once()
    args, _ = mock_search_dates.search.call_args
    assert args[0].trip_type == TripType.ROUND_TRIP
    assert args[0].duration == 14


def test_dates_json_output(runner, mock_search_dates, mock_console):
    """Test dates search JSON output."""
    departure_date = datetime.now() + timedelta(days=1)
    return_date = departure_date + timedelta(days=7)
    mock_search_dates.search.return_value = [
        DatePrice(
            date=(departure_date, return_date),
            price=599.98,
        )
    ]

    result = runner.invoke(
        app,
        ["dates", "JFK", "LAX", "--round", "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["search_type"] == "dates"
    assert payload["trip_type"] == "ROUND_TRIP"
    assert payload["count"] == 1
    assert payload["query"]["is_round_trip"] is True
    assert payload["dates"][0]["departure_date"] == departure_date.date().isoformat()
    assert payload["dates"][0]["return_date"] == return_date.date().isoformat()
    assert payload["dates"][0]["price"] == 599.98
    assert payload["dates"][0]["currency"] == "USD"


def test_dates_json_invalid_date(runner, mock_search_dates, mock_console):
    """Test dates JSON output for invalid date input."""
    result = runner.invoke(
        app,
        ["dates", "JFK", "LAX", "--from", "2024-13-45", "--format", "json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["search_type"] == "dates"
    assert payload["error"]["type"] == "validation_error"
    assert payload["error"]["message"] == "Date must be in YYYY-MM-DD format"


def test_dates_json_empty_results(runner, mock_search_dates, mock_console):
    """Test dates JSON output when no results are found."""
    mock_search_dates.search.return_value = []

    result = runner.invoke(
        app,
        ["dates", "JFK", "LAX", "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["count"] == 0
    assert payload["dates"] == []


def test_dates_over_the_cap_reports_cleanly(runner, mock_console):
    """A range wider than the per-search date cap fails with a readable message.

    Deliberately not mocking ``SearchDates``: the cap is enforced before any
    request, and the point is that the CLI surfaces it rather than dumping a
    traceback.
    """
    from_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    to_date = (datetime.now() + timedelta(days=200)).strftime("%Y-%m-%d")

    result = runner.invoke(app, ["dates", "JFK", "LAX", "--from", from_date, "--to", to_date])

    assert result.exit_code == 1
    assert "93-date limit" in result.output
    assert "Traceback" not in result.output


def test_dates_over_the_cap_json(runner, mock_console):
    """The same cap error is a structured JSON error, not a crash.

    T10 fix round 2, maintainer ruling U1: this is a bare ``ValueError``
    raised by ``SearchDates.search()`` with no mocking involved — it used
    to hit the CLI's ``except (AttributeError, ValueError)`` block and get
    hardcoded ``error_type="search_error"``. It's now routed through the
    shared classifier and reports ``validation_error`` (deliberate
    behaviour change, see the report's "Behaviour changes" section) plus
    the new ``retryable`` field.
    """
    from_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    to_date = (datetime.now() + timedelta(days=200)).strftime("%Y-%m-%d")

    result = runner.invoke(
        app,
        ["dates", "JFK", "LAX", "--from", from_date, "--to", to_date, "--format", "json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert "93-date limit" in payload["error"]["message"]
    assert payload["error"]["type"] == "validation_error"
    assert payload["error"]["retryable"] is False


def test_dates_json_invalid_airport_code(runner, mock_search_dates, mock_console):
    """An unresolvable airport code reports validation_error, not a crash."""
    result = runner.invoke(
        app,
        ["dates", "ZZZZ", "LAX", "--format", "json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["error"]["type"] == "validation_error"
    assert payload["error"]["retryable"] is False
    mock_search_dates.search.assert_not_called()


@pytest.mark.parametrize(
    "exc, expected_type, expected_retryable",
    [
        # Released v0.9.0 CLI --format json values — must not move.
        pytest.param(SearchTimeoutError("slow"), "timeout", True, id="timeout"),
        pytest.param(SearchConnectionError("no route"), "connection_error", True, id="connection"),
        pytest.param(SearchHTTPError("bad gw", status_code=502), "http_error", True, id="http-5xx"),
        pytest.param(
            SearchClientError("generic"), "search_error", False, id="generic-search-error"
        ),
        pytest.param(RuntimeError("bug"), "unexpected_error", False, id="unexpected"),
        # Gained in T10 fix round 2 (U1): a bare AttributeError used to be
        # hardcoded to "search_error" by the (AttributeError, ValueError)
        # block; it isn't a SearchClientError or input-validation failure,
        # so the shared classifier now calls it unexpected_error.
        pytest.param(
            AttributeError("'NoneType' object has no attribute 'name'"),
            "unexpected_error",
            False,
            id="bare-attribute-error",
        ),
    ],
)
def test_dates_json_error_type_matches_shared_classifier(
    runner, mock_search_dates, mock_console, exc, expected_type, expected_retryable
):
    """Dates --format json's error_type/retryable match fli.core.errors.classify_error."""
    mock_search_dates.search.side_effect = exc

    result = runner.invoke(app, ["dates", "JFK", "LAX", "--format", "json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["error"]["type"] == expected_type
    assert payload["error"]["retryable"] is expected_retryable
