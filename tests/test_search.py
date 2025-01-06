"""Tests for Search class."""

import itertools
from datetime import datetime, timedelta
from typing import List

import pytest

from fli import Search, SearchFilters
from fli.models import (
    Airport,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
)


@pytest.fixture
def search():
    """Create a reusable Search instance."""
    return Search()


@pytest.fixture
def basic_search_params():
    """Create basic search params for testing."""
    today = datetime.now()
    future_date = today + timedelta(days=30)
    return SearchFilters(
        departure_airport=Airport.PHX,
        arrival_airport=Airport.SFO,
        departure_date=future_date.strftime("%Y-%m-%d"),
        passenger_info=PassengerInfo(
            adults=1,
            children=0,
            infants_in_seat=0,
            infants_on_lap=0,
        ),
        stops=MaxStops.NON_STOP,
        seat_type=SeatType.ECONOMY,
    )


@pytest.fixture
def complex_search_params():
    """Create more complex search params for testing."""
    today = datetime.now()
    future_date = today + timedelta(days=60)
    return SearchFilters(
        departure_airport=Airport.JFK,
        arrival_airport=Airport.LAX,
        departure_date=future_date.strftime("%Y-%m-%d"),
        passenger_info=PassengerInfo(
            adults=2,
            children=1,
            infants_in_seat=0,
            infants_on_lap=1,
        ),
        stops=MaxStops.TWO_OR_FEWER_STOPS,
        seat_type=SeatType.PREMIUM_ECONOMY,
        sort_by=SortBy.CHEAPEST,
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
