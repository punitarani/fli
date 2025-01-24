from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from typer import BadParameter

from fli.cli.enums import DayOfWeek
from fli.cli.utils import (
    filter_dates_by_days,
    filter_flights_by_airlines,
    filter_flights_by_time,
    parse_airlines,
    parse_stops,
    validate_date,
    validate_time_range,
)
from fli.models import Airline, Airport, FlightLeg, FlightResult, MaxStops
from fli.models.google_flights.base import TripType
from fli.search.dates import DatePrice


@pytest.fixture
def mock_context():
    """Mock click Context."""
    return MagicMock()


@pytest.fixture
def mock_param():
    """Mock click Parameter."""
    return MagicMock()


def test_validate_date_valid(mock_context, mock_param):
    """Test date validation with valid date."""
    date = "2024-12-25"
    result = validate_date(mock_context, mock_param, date)
    assert result == date


def test_validate_date_invalid(mock_context, mock_param):
    """Test date validation with invalid date."""
    with pytest.raises(BadParameter):
        validate_date(mock_context, mock_param, "2024-13-45")


def test_validate_time_range_valid(mock_context, mock_param):
    """Test time range validation with valid range."""
    time_range = "6-20"
    result = validate_time_range(mock_context, mock_param, time_range)
    assert result == (6, 20)


def test_validate_time_range_invalid(mock_context, mock_param):
    """Test time range validation with invalid range."""
    with pytest.raises(BadParameter):
        validate_time_range(mock_context, mock_param, "25-30")


def test_validate_time_range_none(mock_context, mock_param):
    """Test time range validation with None value."""
    result = validate_time_range(mock_context, mock_param, None)
    assert result is None


def test_parse_stops_numeric():
    """Test parsing stops with numeric values."""
    assert parse_stops("0") == MaxStops.NON_STOP
    assert parse_stops("1") == MaxStops.ONE_STOP_OR_FEWER
    assert parse_stops("2") == MaxStops.TWO_OR_FEWER_STOPS


def test_parse_stops_string():
    """Test parsing stops with string values."""
    assert parse_stops("NON_STOP") == MaxStops.NON_STOP
    assert parse_stops("ANY") == MaxStops.ANY


def test_parse_stops_invalid():
    """Test parsing stops with invalid value."""
    with pytest.raises(BadParameter):
        parse_stops("INVALID")


def test_parse_airlines_valid():
    """Test parsing airlines with valid codes."""
    result = parse_airlines(["DL", "UA"])
    assert len(result) == 2
    assert Airline.DL in result
    assert Airline.UA in result


def test_parse_airlines_none():
    """Test parsing airlines with None value."""
    result = parse_airlines(None)
    assert result is None


def test_parse_airlines_invalid():
    """Test parsing airlines with invalid code."""
    with pytest.raises(BadParameter):
        parse_airlines(["INVALID"])


def test_filter_flights_by_time():
    """Test filtering flights by time range."""
    now = datetime.now().replace(hour=10)  # Set to 10 AM
    flights = [
        FlightResult(
            price=100,
            duration=120,
            stops=0,
            legs=[
                FlightLeg(
                    airline=Airline.DL,
                    flight_number="DL123",
                    departure_airport=Airport.JFK,
                    arrival_airport=Airport.LAX,
                    departure_datetime=now,
                    arrival_datetime=now + timedelta(hours=2),
                    duration=120,
                )
            ],
        )
    ]

    # Flight should be included (within range)
    result = filter_flights_by_time(flights, 8, 12)
    assert len(result) == 1

    # Flight should be excluded (outside range)
    result = filter_flights_by_time(flights, 12, 14)
    assert len(result) == 0


def test_filter_flights_by_airlines():
    """Test filtering flights by airlines."""
    now = datetime.now()
    flights = [
        FlightResult(
            price=100,
            duration=120,
            stops=0,
            legs=[
                FlightLeg(
                    airline=Airline.DL,
                    flight_number="DL123",
                    departure_airport=Airport.JFK,
                    arrival_airport=Airport.LAX,
                    departure_datetime=now,
                    arrival_datetime=now + timedelta(hours=2),
                    duration=120,
                )
            ],
        )
    ]

    # Flight should be included (matching airline)
    result = filter_flights_by_airlines(flights, [Airline.DL])
    assert len(result) == 1

    # Flight should be excluded (non-matching airline)
    result = filter_flights_by_airlines(flights, [Airline.UA])
    assert len(result) == 0


def test_filter_dates_by_days():
    """Test filtering dates by days of the week."""
    # Create a date that falls on a Monday
    monday_date = datetime(2024, 1, 1)  # January 1, 2024 was a Monday
    dates = [
        DatePrice(date=(monday_date,), price=100),
        DatePrice(date=(monday_date.replace(day=2),), price=200),  # Tuesday
    ]

    # Filter for Monday only
    result = filter_dates_by_days(dates, [DayOfWeek.MONDAY], TripType.ONE_WAY)
    assert len(result) == 1
    assert result[0].date[0] == monday_date

    # Filter for Tuesday only
    result = filter_dates_by_days(dates, [DayOfWeek.TUESDAY], TripType.ONE_WAY)
    assert len(result) == 1
    assert result[0].date[0] == monday_date.replace(day=2)

    # No day filters should return all dates
    result = filter_dates_by_days(dates, [], TripType.ONE_WAY)
    assert len(result) == 2
