"""Tests for FlightSearchFilters validation."""

from datetime import datetime, timedelta, timezone

import pytest

from fli.models import (
    Airport,
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
    TripType,
)


def utc_today():
    """Today's date in UTC — the anchor the validators reference."""
    return datetime.now(timezone.utc).date()


def segment(origin, destination, travel_date):
    """Build a FlightSegment for the given route and date."""
    return FlightSegment(
        departure_airport=[[origin, 0]],
        arrival_airport=[[destination, 0]],
        travel_date=travel_date.strftime("%Y-%m-%d"),
    )


@pytest.fixture
def passengers():
    """Get a single adult passenger."""
    return PassengerInfo(adults=1, children=0, infants_in_seat=0, infants_on_lap=0)


def test_round_trip_return_after_departure(passengers):
    """Test FlightSearchFilters accepts a return date after the departure date."""
    depart = utc_today() + timedelta(days=30)
    back = utc_today() + timedelta(days=37)

    filters = FlightSearchFilters(
        trip_type=TripType.ROUND_TRIP,
        passenger_info=passengers,
        flight_segments=[
            segment(Airport.SFO, Airport.LAX, depart),
            segment(Airport.LAX, Airport.SFO, back),
        ],
    )

    assert filters.flight_segments[1].travel_date == back.strftime("%Y-%m-%d")


def test_round_trip_return_before_departure(passengers):
    """Test FlightSearchFilters rejects a return date before the departure date.

    Both dates are in the future, so the past-date validator cannot catch this.
    It previously went unvalidated and was passed straight to Google.
    """
    depart = utc_today() + timedelta(days=30)
    back = utc_today() + timedelta(days=20)

    with pytest.raises(ValueError, match="cannot be before departure date"):
        FlightSearchFilters(
            trip_type=TripType.ROUND_TRIP,
            passenger_info=passengers,
            flight_segments=[
                segment(Airport.SFO, Airport.LAX, depart),
                segment(Airport.LAX, Airport.SFO, back),
            ],
        )


def test_round_trip_same_day_return(passengers):
    """Test FlightSearchFilters accepts a same-day return."""
    depart = utc_today() + timedelta(days=30)

    filters = FlightSearchFilters(
        trip_type=TripType.ROUND_TRIP,
        passenger_info=passengers,
        flight_segments=[
            segment(Airport.SFO, Airport.LAX, depart),
            segment(Airport.LAX, Airport.SFO, depart),
        ],
    )

    assert filters.flight_segments[0].travel_date == filters.flight_segments[1].travel_date


def test_one_way_is_not_order_checked(passengers):
    """Test the ordering check does not apply to one-way trips."""
    filters = FlightSearchFilters(
        trip_type=TripType.ONE_WAY,
        passenger_info=passengers,
        flight_segments=[segment(Airport.SFO, Airport.LAX, utc_today() + timedelta(days=30))],
    )

    assert filters.trip_type == TripType.ONE_WAY


def test_multi_city_rejects_backwards_leg(passengers):
    """Test FlightSearchFilters rejects a multi-city leg that departs before the previous one."""
    first = utc_today() + timedelta(days=10)
    second = utc_today() + timedelta(days=20)
    third = utc_today() + timedelta(days=15)  # earlier than the second leg

    with pytest.raises(ValueError, match="Segment 3 .* cannot be before segment 2"):
        FlightSearchFilters(
            trip_type=TripType.MULTI_CITY,
            passenger_info=passengers,
            flight_segments=[
                segment(Airport.SFO, Airport.LAX, first),
                segment(Airport.LAX, Airport.JFK, second),
                segment(Airport.JFK, Airport.SFO, third),
            ],
        )
