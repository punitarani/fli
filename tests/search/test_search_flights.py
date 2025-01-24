"""Tests for Search class."""

from datetime import datetime, timedelta

import pytest

from fli.models import (
    Airport,
    FlightSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
)
from fli.models.google_flights.base import TripType
from fli.search import SearchFlights


@pytest.fixture
def search():
    """Create a reusable Search instance."""
    return SearchFlights()


@pytest.fixture
def basic_search_params():
    """Create basic search params for testing."""
    today = datetime.now()
    future_date = today + timedelta(days=30)
    return FlightSearchFilters(
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
    )


@pytest.fixture
def complex_search_params():
    """Create more complex search params for testing."""
    today = datetime.now()
    future_date = today + timedelta(days=60)
    return FlightSearchFilters(
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
    )


@pytest.fixture
def round_trip_search_params():
    """Create basic round trip search params for testing."""
    today = datetime.now()
    outbound_date = today + timedelta(days=30)
    return_date = outbound_date + timedelta(days=7)

    return FlightSearchFilters(
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
    )


@pytest.fixture
def complex_round_trip_params():
    """Create more complex round trip search params for testing."""
    today = datetime.now()
    outbound_date = today + timedelta(days=60)
    return_date = outbound_date + timedelta(days=14)

    return FlightSearchFilters(
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
    )


@pytest.mark.parametrize(
    "search_params_fixture",
    [
        "basic_search_params",
        "complex_search_params",
    ],
)
def test_search_functionality(search, search_params_fixture, request):
    """Test flight search functionality with different data sets."""
    search_params = request.getfixturevalue(search_params_fixture)
    results = search.search(search_params)
    assert isinstance(results, list)


def test_multiple_searches(search, basic_search_params, complex_search_params):
    """Test performing multiple searches with the same Search instance."""
    # First search
    results1 = search.search(basic_search_params)
    assert isinstance(results1, list)

    # Second search with different data
    results2 = search.search(complex_search_params)
    assert isinstance(results2, list)

    # Third search reusing first search data
    results3 = search.search(basic_search_params)
    assert isinstance(results3, list)


def test_basic_round_trip_search(search, round_trip_search_params):
    """Test basic round trip flight search functionality."""
    results = search.search(round_trip_search_params)
    assert isinstance(results, list)
    assert len(results) > 0

    # Check that results contain tuples of outbound and return flights
    for outbound, return_flight in results:
        # Verify outbound flight
        assert outbound.legs[0].departure_airport == Airport.SFO
        assert outbound.legs[-1].arrival_airport == Airport.JFK

        # Verify return flight
        assert return_flight.legs[0].departure_airport == Airport.JFK
        assert return_flight.legs[-1].arrival_airport == Airport.SFO


def test_complex_round_trip_search(search, complex_round_trip_params):
    """Test complex round trip flight search with multiple passengers and stops."""
    results = search.search(complex_round_trip_params)
    assert isinstance(results, list)
    assert len(results) > 0

    # Check that results contain tuples of outbound and return flights
    for outbound, return_flight in results:
        # Verify outbound flight
        assert outbound.legs[0].departure_airport == Airport.LAX
        assert outbound.legs[-1].arrival_airport == Airport.ORD
        assert outbound.stops <= MaxStops.ONE_STOP_OR_FEWER.value

        # Verify return flight
        assert return_flight.legs[0].departure_airport == Airport.ORD
        assert return_flight.legs[-1].arrival_airport == Airport.LAX
        assert return_flight.stops <= MaxStops.ONE_STOP_OR_FEWER.value


def test_round_trip_with_selected_outbound(search, round_trip_search_params):
    """Test round trip search with a pre-selected outbound flight."""
    # First get outbound flights
    initial_results = search.search(round_trip_search_params)
    assert len(initial_results) > 0

    # Select first outbound flight and search for returns
    selected_outbound = initial_results[0][0]  # Get first outbound flight
    round_trip_search_params.flight_segments[0].selected_flight = selected_outbound

    return_results = search.search(round_trip_search_params)
    assert isinstance(return_results, list)
    assert len(return_results) > 0

    # Verify all return flights match the selected outbound
    for return_flight in return_results:
        assert return_flight.legs[0].departure_airport == Airport.JFK
        assert return_flight.legs[-1].arrival_airport == Airport.SFO


@pytest.mark.parametrize(
    "search_params_fixture",
    [
        "round_trip_search_params",
        "complex_round_trip_params",
    ],
)
def test_round_trip_result_structure(search, search_params_fixture, request):
    """Test the structure of round trip search results with different parameters."""
    search_params = request.getfixturevalue(search_params_fixture)
    results = search.search(search_params)

    assert isinstance(results, list)
    assert len(results) > 0

    for result in results:
        assert isinstance(result, tuple)
        assert len(result) == 2
        outbound, return_flight = result

        # Verify both flights have the expected structure
        for flight in (outbound, return_flight):
            assert hasattr(flight, "price")
            assert hasattr(flight, "duration")
            assert hasattr(flight, "stops")
            assert hasattr(flight, "legs")
            assert len(flight.legs) > 0
