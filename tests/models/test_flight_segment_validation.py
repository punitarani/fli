"""Tests for FlightSegment validation."""

from datetime import datetime, timedelta, timezone

import pytest

from fli.models import Airport, FlightSegment, TimeRestrictions


def utc_today():
    """Today's date in UTC — the anchor the validators reference."""
    return datetime.now(timezone.utc).date()


@pytest.fixture
def future_date():
    """Get a date 30 days in the future."""
    return datetime.now() + timedelta(days=30)


def test_flight_segment_normal():
    """Test FlightSegment with valid data."""
    future = datetime.now() + timedelta(days=30)
    segment = FlightSegment(
        departure_airport=[[Airport.PHX, 0]],
        arrival_airport=[[Airport.SFO, 0]],
        travel_date=future.strftime("%Y-%m-%d"),
    )
    assert segment.departure_airport == [[Airport.PHX, 0]]
    assert segment.arrival_airport == [[Airport.SFO, 0]]
    assert segment.travel_date == future.strftime("%Y-%m-%d")


def test_flight_segment_past_date():
    """Test FlightSegment rejects past travel dates."""
    past = utc_today() - timedelta(days=2)
    with pytest.raises(ValueError, match="Travel date cannot be in the past"):
        FlightSegment(
            departure_airport=[[Airport.PHX, 0]],
            arrival_airport=[[Airport.SFO, 0]],
            travel_date=past.strftime("%Y-%m-%d"),
        )


def test_flight_segment_today():
    """Test FlightSegment accepts today's date."""
    today = datetime.now()
    segment = FlightSegment(
        departure_airport=[[Airport.PHX, 0]],
        arrival_airport=[[Airport.SFO, 0]],
        travel_date=today.strftime("%Y-%m-%d"),
    )
    assert segment.travel_date == today.strftime("%Y-%m-%d")


def test_flight_segment_accepts_yesterday_in_utc():
    """Test FlightSegment accepts the day before the UTC date.

    Travel dates are local to the origin airport, but the validator can only see
    the server clock. At 17:00 in San Francisco the UTC date has already rolled
    over, so a same-day evening SFO departure looks like "yesterday" to a UTC
    container. Rejecting it blinds every westward user to same-day flights for
    the last hours of their day, so utc_today - 1 must remain searchable.
    """
    yesterday_utc = utc_today() - timedelta(days=1)
    segment = FlightSegment(
        departure_airport=[[Airport.SFO, 0]],
        arrival_airport=[[Airport.LAX, 0]],
        travel_date=yesterday_utc.strftime("%Y-%m-%d"),
    )
    assert segment.travel_date == yesterday_utc.strftime("%Y-%m-%d")


def test_flight_segment_same_airports():
    """Test FlightSegment rejects same departure and arrival airports."""
    future = datetime.now() + timedelta(days=30)
    with pytest.raises(ValueError, match="Departure and arrival airports must be different"):
        FlightSegment(
            departure_airport=[[Airport.PHX, 0]],
            arrival_airport=[[Airport.PHX, 0]],  # Same as departure
            travel_date=future.strftime("%Y-%m-%d"),
        )


def test_flight_segment_missing_airports():
    """Test FlightSegment rejects missing airports."""
    future = datetime.now() + timedelta(days=30)
    with pytest.raises(ValueError, match="Both departure and arrival airports must be specified"):
        FlightSegment(
            departure_airport=[],
            arrival_airport=[[Airport.SFO, 0]],
            travel_date=future.strftime("%Y-%m-%d"),
        )

    with pytest.raises(ValueError, match="Both departure and arrival airports must be specified"):
        FlightSegment(
            departure_airport=[[Airport.PHX, 0]],
            arrival_airport=[],
            travel_date=future.strftime("%Y-%m-%d"),
        )


def test_flight_segment_with_time_restrictions(future_date):
    """Test FlightSegment with TimeRestrictions."""
    # Normal order
    segment1 = FlightSegment(
        departure_airport=[[Airport.PHX, 0]],
        arrival_airport=[[Airport.SFO, 0]],
        travel_date=future_date.strftime("%Y-%m-%d"),
        time_restrictions=TimeRestrictions(
            earliest_departure=9,
            latest_departure=20,
            earliest_arrival=13,
            latest_arrival=21,
        ),
    )
    assert segment1.time_restrictions.earliest_departure == 9
    assert segment1.time_restrictions.latest_departure == 20

    # Reversed order (should be auto-corrected by TimeRestrictions)
    segment2 = FlightSegment(
        departure_airport=[[Airport.PHX, 0]],
        arrival_airport=[[Airport.SFO, 0]],
        travel_date=future_date.strftime("%Y-%m-%d"),
        time_restrictions=TimeRestrictions(
            earliest_departure=20,  # Later than latest_departure
            latest_departure=9,  # Earlier than earliest_departure
            earliest_arrival=21,  # Later than latest_arrival
            latest_arrival=13,  # Earlier than earliest_arrival
        ),
    )
    assert segment2.time_restrictions.earliest_departure == 9  # Swapped
    assert segment2.time_restrictions.latest_departure == 20  # Swapped
    assert segment2.time_restrictions.earliest_arrival == 13  # Swapped
    assert segment2.time_restrictions.latest_arrival == 21  # Swapped
