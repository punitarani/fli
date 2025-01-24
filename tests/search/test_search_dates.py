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
    SortBy,
)
from fli.models.google_flights.base import TripType
from fli.search import SearchDates


@pytest.fixture
def search():
    """Create a reusable SearchDates instance."""
    return SearchDates()


@pytest.fixture
def basic_search_params():
    """Create basic date search params for testing."""
    today = datetime.now()
    future_date = today + timedelta(days=30)
    return DateSearchFilters(
        passenger_info=PassengerInfo(
            adults=1,
            children=0,
            infants_in_seat=0,
            infants_on_lap=0,
        ),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.PHX, 0]],
                arrival_airport=[[Airport.SFO, 0]],
                travel_date=future_date.strftime("%Y-%m-%d"),
            )
        ],
        stops=MaxStops.NON_STOP,
        seat_type=SeatType.ECONOMY,
        sort_by=SortBy.CHEAPEST,
        from_date=(future_date - timedelta(days=30)).strftime("%Y-%m-%d"),
        to_date=(future_date + timedelta(days=30)).strftime("%Y-%m-%d"),
    )


@pytest.fixture
def complex_search_params():
    """Create more complex date search params for testing."""
    today = datetime.now()
    future_date = today + timedelta(days=60)
    return DateSearchFilters(
        passenger_info=PassengerInfo(
            adults=2,
            children=1,
            infants_in_seat=0,
            infants_on_lap=1,
        ),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LAX, 0]],
                travel_date=future_date.strftime("%Y-%m-%d"),
            )
        ],
        stops=MaxStops.ONE_STOP_OR_FEWER,
        seat_type=SeatType.FIRST,
        sort_by=SortBy.TOP_FLIGHTS,
        from_date=(future_date - timedelta(days=30)).strftime("%Y-%m-%d"),
        to_date=(future_date + timedelta(days=30)).strftime("%Y-%m-%d"),
    )


@pytest.fixture
def round_trip_search_params():
    """Create basic round trip search params for testing."""
    today = datetime.now()
    outbound_date = today + timedelta(days=30)
    return_date = outbound_date + timedelta(days=7)

    return DateSearchFilters(
        passenger_info=PassengerInfo(
            adults=1,
            children=0,
            infants_in_seat=0,
            infants_on_lap=0,
        ),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.SFO, 0]],
                arrival_airport=[[Airport.JFK, 0]],
                travel_date=outbound_date.strftime("%Y-%m-%d"),
            ),
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.SFO, 0]],
                travel_date=return_date.strftime("%Y-%m-%d"),
            ),
        ],
        stops=MaxStops.NON_STOP,
        seat_type=SeatType.ECONOMY,
        sort_by=SortBy.CHEAPEST,
        trip_type=TripType.ROUND_TRIP,
        from_date=(outbound_date - timedelta(days=30)).strftime("%Y-%m-%d"),
        to_date=(outbound_date + timedelta(days=30)).strftime("%Y-%m-%d"),
    )


@pytest.fixture
def complex_round_trip_params():
    """Create more complex round trip search params for testing."""
    today = datetime.now()
    outbound_date = today + timedelta(days=60)
    return_date = outbound_date + timedelta(days=14)

    return DateSearchFilters(
        passenger_info=PassengerInfo(
            adults=2,
            children=1,
            infants_in_seat=0,
            infants_on_lap=1,
        ),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.LAX, 0]],
                arrival_airport=[[Airport.ORD, 0]],
                travel_date=outbound_date.strftime("%Y-%m-%d"),
            ),
            FlightSegment(
                departure_airport=[[Airport.ORD, 0]],
                arrival_airport=[[Airport.LAX, 0]],
                travel_date=return_date.strftime("%Y-%m-%d"),
            ),
        ],
        stops=MaxStops.ONE_STOP_OR_FEWER,
        seat_type=SeatType.BUSINESS,
        sort_by=SortBy.TOP_FLIGHTS,
        trip_type=TripType.ROUND_TRIP,
        from_date=(outbound_date - timedelta(days=30)).strftime("%Y-%m-%d"),
        to_date=(outbound_date + timedelta(days=30)).strftime("%Y-%m-%d"),
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
    assert isinstance(results, list)


def test_multiple_searches(search, basic_search_params, complex_search_params):
    """Test performing multiple searches with the same SearchDates instance."""
    # First search
    results1 = search.search(basic_search_params)
    assert isinstance(results1, list)

    # Second search with different data
    results2 = search.search(complex_search_params)
    assert isinstance(results2, list)

    # Third search reusing first search data
    results3 = search.search(basic_search_params)
    assert isinstance(results3, list)


def test_date_price_sorting(search, basic_search_params):
    """Test that date prices are sorted chronologically."""
    results = search.search(basic_search_params)
    assert len(results) > 0

    # Verify dates are sorted
    dates = [result.date[0] for result in results]  # Get first date from tuple
    assert dates == sorted(dates)


def test_basic_round_trip_search(search, round_trip_search_params):
    """Test basic round trip date search functionality."""
    results = search.search(round_trip_search_params)
    assert isinstance(results, list)
    assert len(results) > 0

    # Verify date range
    from_date = datetime.strptime(round_trip_search_params.from_date, "%Y-%m-%d")
    to_date = datetime.strptime(round_trip_search_params.to_date, "%Y-%m-%d")

    for result in results:
        # For round trips, date is a tuple of (outbound_date, return_date)
        outbound_date, return_date = result.date
        assert from_date.date() <= outbound_date.date() <= to_date.date()
        assert outbound_date.date() <= return_date.date()  # Return can be same day or later
        assert hasattr(result, "price")
        assert result.price > 0


def test_complex_round_trip_search(search, complex_round_trip_params):
    """Test complex round trip date search with multiple passengers and stops."""
    results = search.search(complex_round_trip_params)
    assert isinstance(results, list)
    assert len(results) > 0

    # Verify date range
    from_date = datetime.strptime(complex_round_trip_params.from_date, "%Y-%m-%d")
    to_date = datetime.strptime(complex_round_trip_params.to_date, "%Y-%m-%d")

    for result in results:
        # For round trips, date is a tuple of (outbound_date, return_date)
        outbound_date, return_date = result.date
        assert from_date.date() <= outbound_date.date() <= to_date.date()
        assert outbound_date.date() <= return_date.date()  # Return can be same day or later
        assert hasattr(result, "price")
        assert result.price > 0


@pytest.mark.parametrize(
    "search_params_fixture",
    [
        "round_trip_search_params",
        "complex_round_trip_params",
    ],
)
def test_round_trip_result_structure(search, search_params_fixture, request):
    """Test the structure of round trip date search results with different parameters."""
    search_params = request.getfixturevalue(search_params_fixture)
    results = search.search(search_params)

    assert isinstance(results, list)
    assert len(results) > 0

    # Verify chronological order of outbound dates
    outbound_dates = [result.date[0] for result in results]
    assert outbound_dates == sorted(outbound_dates)

    # Verify result structure
    for result in results:
        assert isinstance(result.date, tuple)
        assert len(result.date) == 2  # Should have outbound and return dates
        outbound_date, return_date = result.date
        assert isinstance(outbound_date, datetime)
        assert isinstance(return_date, datetime)
        assert outbound_date <= return_date  # Return can be same day or later
        assert hasattr(result, "price")
        assert result.price > 0
