from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console
from typer import BadParameter

from fli.cli.enums import DayOfWeek
from fli.cli.utils import (
    display_flight_results,
    filter_dates_by_days,
    filter_flights_by_airlines,
    filter_flights_by_time,
    parse_airlines,
    parse_stops,
    serialize_date_result,
    serialize_flight_result,
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


def test_validate_date_single_digit(mock_context, mock_param):
    """Test date validation normalizes single-digit month and day."""
    assert validate_date(mock_context, mock_param, "2026-4-2") == "2026-04-02"
    assert validate_date(mock_context, mock_param, "2026-12-5") == "2026-12-05"
    assert validate_date(mock_context, mock_param, "2026-1-15") == "2026-01-15"


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


def test_parse_airlines_numeric_prefix():
    """Test that airline codes starting with a digit are resolved correctly."""
    result = parse_airlines(["3F"])
    assert result == [Airline._3F]


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


# ---------------------------------------------------------------------------
# display_flight_results — round-trip price must not be doubled
# ---------------------------------------------------------------------------


def _make_flight_result(price: float, airline=Airline.DL, flight_number="DL123") -> FlightResult:
    """Create a FlightResult for testing display."""
    now = datetime.now()
    return FlightResult(
        price=price,
        duration=300,
        stops=0,
        legs=[
            FlightLeg(
                airline=airline,
                flight_number=flight_number,
                departure_airport=Airport.JFK,
                arrival_airport=Airport.LAX,
                departure_datetime=now,
                arrival_datetime=now + timedelta(hours=5),
                duration=300,
            )
        ],
    )


def _capture_display(flights: list) -> str:
    """Run display_flight_results and capture the rendered text."""
    buf = StringIO()
    test_console = Console(file=buf, width=120, force_terminal=True)
    with patch("fli.cli.utils.console", test_console):
        display_flight_results(flights)
    return buf.getvalue()


def test_display_one_way_price():
    """One-way flight should display the flight price as-is."""
    output = _capture_display([_make_flight_result(price=159.0)])
    assert "$159.00" in output


def test_display_round_trip_price_not_doubled():
    """Round-trip display must use outbound price only (Google returns full RT price per leg)."""
    outbound = _make_flight_result(price=317.0, flight_number="DL100")
    return_flight = _make_flight_result(price=317.0, airline=Airline.DL, flight_number="DL200")

    output = _capture_display([(outbound, return_flight)])

    assert "$317.00" in output
    assert "$634.00" not in output


def test_display_round_trip_price_asymmetric():
    """When leg prices differ, total should be the outbound price, not the sum."""
    outbound = _make_flight_result(price=400.0)
    return_flight = _make_flight_result(price=350.0)

    output = _capture_display([(outbound, return_flight)])

    assert "$400.00" in output
    assert "$750.00" not in output


def test_serialize_flight_result_one_way():
    """JSON flight serialization should use machine-readable nested fields."""
    flight = _make_flight_result(price=159.0)

    payload = serialize_flight_result(flight)

    assert payload["price"] == 159.0
    assert payload["currency"] == "USD"
    assert payload["legs"][0]["departure_airport"]["code"] == "JFK"
    assert payload["legs"][0]["airline"]["code"] == "DL"


def test_serialize_flight_result_round_trip():
    """Round-trip JSON serialization should expose outbound and return segments."""
    outbound = _make_flight_result(price=317.0, flight_number="DL100")
    return_flight = _make_flight_result(price=317.0, flight_number="DL200")

    payload = serialize_flight_result((outbound, return_flight))

    assert payload["price"] == 317.0
    assert payload["currency"] == "USD"
    assert payload["outbound"]["legs"][0]["flight_number"] == "DL100"
    assert payload["return"]["legs"][0]["flight_number"] == "DL200"


def test_serialize_date_result_round_trip():
    """Date serialization should include the return date for round-trip searches."""
    result = DatePrice(
        date=(datetime(2026, 5, 1), datetime(2026, 5, 8)),
        price=599.98,
    )

    payload = serialize_date_result(result, TripType.ROUND_TRIP)

    assert payload == {
        "departure_date": "2026-05-01",
        "return_date": "2026-05-08",
        "price": 599.98,
        "currency": "USD",
    }
