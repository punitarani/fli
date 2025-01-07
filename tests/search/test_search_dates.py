"""Tests for SearchDates class."""

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
from fli.search import SearchDates
from fli.search.dates import DatePrice


@pytest.fixture
def search():
    """Create a reusable SearchDates instance."""
    return SearchDates()


@pytest.fixture
def basic_search_params():
    """Create basic date search params for testing."""
    today = datetime.now()
    future_date = today + timedelta(days=30)
    start_date = future_date - timedelta(days=7)
    end_date = future_date + timedelta(days=7)

    return DateSearchFilters(
        passenger_info=PassengerInfo(
            adults=1,
            children=0,
            infants_in_seat=0,
            infants_on_lap=0,
        ),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.SFO, 0]],
                travel_date=future_date.strftime("%Y-%m-%d"),
            )
        ],
        stops=MaxStops.NON_STOP,
        seat_type=SeatType.ECONOMY,
        from_date=start_date.strftime("%Y-%m-%d"),
        to_date=end_date.strftime("%Y-%m-%d"),
    )


@pytest.fixture
def complex_search_params():
    """Create more complex date search params for testing."""
    today = datetime.now()
    future_date = today + timedelta(days=60)
    start_date = future_date - timedelta(days=20)
    end_date = future_date + timedelta(days=20)

    return DateSearchFilters(
        passenger_info=PassengerInfo(
            adults=1,
            children=1,
            infants_in_seat=0,
            infants_on_lap=0,
        ),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LHR, 0]],
                travel_date=future_date.strftime("%Y-%m-%d"),
            )
        ],
        stops=MaxStops.TWO_OR_FEWER_STOPS,
        seat_type=SeatType.BUSINESS,
        from_date=start_date.strftime("%Y-%m-%d"),
        to_date=end_date.strftime("%Y-%m-%d"),
    )


@pytest.mark.parametrize(
    "search_params_fixture",
    [
        "basic_search_params",
        "complex_search_params",
    ],
)
def test_search_functionality(search, search_params_fixture, request):
    """Test date search functionality with different data sets."""
    search_params = request.getfixturevalue(search_params_fixture)
    results = search.search(search_params)

    # Check if results are returned
    assert results is not None
    assert isinstance(results, list)

    # Calculate expected number of days
    start_date = datetime.strptime(search_params.from_date, "%Y-%m-%d")
    end_date = datetime.strptime(search_params.to_date, "%Y-%m-%d")
    expected_days = (end_date - start_date).days + 1

    # Verify number of results matches the date range
    assert len(results) == expected_days

    # Check if results contain DatePrice objects
    for result in results:
        assert isinstance(result, DatePrice)
        assert isinstance(result.date, datetime)
        assert isinstance(result.price, float)
        assert result.price > 0


def test_multiple_searches(search, basic_search_params, complex_search_params):
    """Test performing multiple searches with the same SearchDates instance."""
    # First search
    results1 = search.search(basic_search_params)
    assert isinstance(results1, list)
    assert all(isinstance(r, DatePrice) for r in results1)

    # Second search with different data
    results2 = search.search(complex_search_params)
    assert isinstance(results2, list)
    assert all(isinstance(r, DatePrice) for r in results2)

    # Third search reusing first search data
    results3 = search.search(basic_search_params)
    assert isinstance(results3, list)
    assert all(isinstance(r, DatePrice) for r in results3)


def test_date_price_sorting(search, basic_search_params):
    """Test that results are properly sorted by date."""
    results = search.search(basic_search_params)
    assert results is not None

    # Verify results are sorted by date
    dates = [r.date for r in results]
    assert dates == sorted(dates)
