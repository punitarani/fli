"""Tests for DateSearchFilters validation and auto-correction."""

from datetime import datetime, timedelta

import pytest

from fli.models import (
    Airport,
    DateSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
)


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
    past_date = datetime.now() - timedelta(days=7)
    to_date = future_date + timedelta(days=7)

    filters = DateSearchFilters(
        **basic_search_params,
        from_date=past_date.strftime("%Y-%m-%d"),
        to_date=to_date.strftime("%Y-%m-%d"),
    )

    assert filters.from_date == datetime.now().date().strftime("%Y-%m-%d")
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
    from_date = datetime.now() - timedelta(days=7)
    to_date = datetime.now() - timedelta(days=1)

    with pytest.raises(ValueError, match="To date must be in the future"):
        DateSearchFilters(
            **basic_search_params,
            from_date=from_date.strftime("%Y-%m-%d"),
            to_date=to_date.strftime("%Y-%m-%d"),
        )

    # Even if the from and to dates are reversed, the to date should still be in the future
    with pytest.raises(ValueError, match="To date must be in the future"):
        DateSearchFilters(
            **basic_search_params,
            from_date=to_date.strftime("%Y-%m-%d"),
            to_date=from_date.strftime("%Y-%m-%d"),
        )


def test_date_search_today_to_date(basic_search_params, future_date):
    """Test DateSearchFilters raises error for today's to_date."""
    today = datetime.now()
    from_date = today - timedelta(days=7)

    with pytest.raises(ValueError, match="To date must be in the future"):
        DateSearchFilters(
            **basic_search_params,
            from_date=from_date.strftime("%Y-%m-%d"),
            to_date=today.strftime("%Y-%m-%d"),
        )

    # Even if the from and to dates are reversed, the to date should still be in the future
    with pytest.raises(ValueError, match="To date must be in the future"):
        DateSearchFilters(
            **basic_search_params,
            from_date=today.strftime("%Y-%m-%d"),
            to_date=from_date.strftime("%Y-%m-%d"),
        )


def test_date_search_segment_outside_range(basic_search_params, future_date):
    """Test DateSearchFilters validates flight segment dates are within range."""
    from_date = future_date
    to_date = future_date + timedelta(days=7)
    outside_date = future_date + timedelta(days=14)

    # Update flight segment to be outside the date range
    basic_search_params["flight_segments"][0].travel_date = outside_date.strftime("%Y-%m-%d")

    with pytest.raises(
        ValueError, match="Flight segment travel date .* must be within the search date range"
    ):
        DateSearchFilters(
            **basic_search_params,
            from_date=from_date.strftime("%Y-%m-%d"),
            to_date=to_date.strftime("%Y-%m-%d"),
        )

    # Even if the from and to dates are reversed, the to date should still be in the future
    with pytest.raises(
        ValueError, match="Flight segment travel date .* must be within the search date range"
    ):
        DateSearchFilters(
            **basic_search_params,
            from_date=to_date.strftime("%Y-%m-%d"),
            to_date=from_date.strftime("%Y-%m-%d"),
        )
