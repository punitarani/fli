"""Tests for DateSearchFilters validation and auto-correction."""

from datetime import datetime, timedelta, timezone

import pytest

from fli.models import (
    Airport,
    DateSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
)
from fli.models.google_flights.dates import MAX_PAST_FROM_DATE_DAYS


def utc_today():
    """Today's date in UTC — the anchor the validators reference."""
    return datetime.now(timezone.utc).date()


@pytest.fixture
def future_date():
    """Get a date 30 days in the future."""
    return datetime.now() + timedelta(days=30)


@pytest.fixture
def basic_search_params(future_date):
    """Create basic search params for testing."""
    return {
        "passenger_info": PassengerInfo(
            adults=1,
            children=0,
            infants_in_seat=0,
            infants_on_lap=0,
        ),
        "flight_segments": [
            FlightSegment(
                departure_airport=[[Airport.PHX, 0]],
                arrival_airport=[[Airport.SFO, 0]],
                travel_date=future_date.strftime("%Y-%m-%d"),
            )
        ],
        "stops": MaxStops.NON_STOP,
        "seat_type": SeatType.ECONOMY,
    }


def test_date_search_normal_dates(basic_search_params, future_date):
    """Test DateSearchFilters with normal date range."""
    from_date = future_date - timedelta(days=7)
    to_date = future_date + timedelta(days=7)

    filters = DateSearchFilters(
        **basic_search_params,
        from_date=from_date.strftime("%Y-%m-%d"),
        to_date=to_date.strftime("%Y-%m-%d"),
    )

    assert filters.from_date == from_date.strftime("%Y-%m-%d")
    assert filters.to_date == to_date.strftime("%Y-%m-%d")


def test_date_search_past_from_date(basic_search_params, future_date):
    """Test DateSearchFilters auto-corrects past from_date to today."""
    past_date = utc_today() - timedelta(days=7)
    to_date = future_date + timedelta(days=7)

    filters = DateSearchFilters(
        **basic_search_params,
        from_date=past_date.strftime("%Y-%m-%d"),
        to_date=to_date.strftime("%Y-%m-%d"),
    )

    assert filters.from_date == utc_today().strftime("%Y-%m-%d")
    assert filters.to_date == to_date.strftime("%Y-%m-%d")


def test_date_search_reversed_dates(basic_search_params, future_date):
    """Test DateSearchFilters auto-corrects reversed dates."""
    earlier_date = future_date
    later_date = future_date + timedelta(days=7)

    # Create with reversed dates
    filters = DateSearchFilters(
        **basic_search_params,
        from_date=later_date.strftime("%Y-%m-%d"),
        to_date=earlier_date.strftime("%Y-%m-%d"),
    )

    # Verify dates were swapped
    assert filters.from_date == earlier_date.strftime("%Y-%m-%d")
    assert filters.to_date == later_date.strftime("%Y-%m-%d")


def test_date_search_past_to_date(basic_search_params):
    """Test DateSearchFilters raises error for past to_date."""
    from_date = utc_today() - timedelta(days=7)
    to_date = utc_today() - timedelta(days=2)

    with pytest.raises(ValueError, match="To date cannot be in the past"):
        DateSearchFilters(
            **basic_search_params,
            from_date=from_date.strftime("%Y-%m-%d"),
            to_date=to_date.strftime("%Y-%m-%d"),
        )

    # Even if the from and to dates are reversed, the to date must not be in the past
    with pytest.raises(ValueError, match="To date cannot be in the past"):
        DateSearchFilters(
            **basic_search_params,
            from_date=to_date.strftime("%Y-%m-%d"),
            to_date=from_date.strftime("%Y-%m-%d"),
        )


def test_date_search_today_to_date(basic_search_params, future_date):
    """Test DateSearchFilters accepts a to_date of today.

    A range ending "today" is still live for any traveler west of UTC, so the
    validator anchors to utc_today - 1 rather than the server's naive today.
    """
    today = utc_today()
    from_date = today - timedelta(days=1)

    filters = DateSearchFilters(
        **basic_search_params,
        from_date=from_date.strftime("%Y-%m-%d"),
        to_date=today.strftime("%Y-%m-%d"),
    )

    assert filters.to_date == today.strftime("%Y-%m-%d")


def test_date_search_from_date_clamp_cannot_pass_to_date(basic_search_params):
    """Test the from_date clamp cannot push from_date past a to_date at the rejection floor.

    to_date may be as early as yesterday UTC, so clamping from_date to plain
    "today" would invert the range; the clamp must cap at to_date instead.
    """
    from_date = utc_today() - timedelta(days=MAX_PAST_FROM_DATE_DAYS + 4)
    to_date = utc_today() - timedelta(days=1)

    filters = DateSearchFilters(
        **basic_search_params,
        from_date=from_date.strftime("%Y-%m-%d"),
        to_date=to_date.strftime("%Y-%m-%d"),
    )

    assert filters.from_date == to_date.strftime("%Y-%m-%d")
    assert filters.parsed_from_date <= filters.parsed_to_date


def test_date_search_past_from_date_after_swap(basic_search_params, future_date):
    """Test DateSearchFilters bumps up from_date to current date after date swap."""
    past_date = utc_today() - timedelta(days=7)
    later_date = future_date + timedelta(days=7)

    # Create with reversed dates where from_date is in the future but will be swapped with past date
    filters = DateSearchFilters(
        **basic_search_params,
        from_date=later_date.strftime("%Y-%m-%d"),
        to_date=past_date.strftime("%Y-%m-%d"),
    )

    # After swap and adjustment, from_date should be today and to_date should be the later date
    assert filters.from_date == utc_today().strftime("%Y-%m-%d")
    assert filters.to_date == later_date.strftime("%Y-%m-%d")
