"""Fuzz testing for Search functionality."""

import random
from datetime import datetime, timedelta
from typing import List, Tuple

import pytest

from fli.models import (
    Airport,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
)
from fli.search import SearchFlights, SearchFlightsFilters


@pytest.fixture
def search():
    """Create a reusable Search instance."""
    return SearchFlights()


def generate_test_id(val, argname=None, idx=None) -> str:
    """Generate a test ID for pytest."""
    if isinstance(val, datetime):
        val = val.strftime("%Y%m%d")
    if argname:
        return f"{argname}-{val}"
    if idx is not None:
        return f"{idx}-{val}"
    return str(val)


def generate_random_test_cases(num_tests: int) -> List[Tuple]:
    """Generate randomized test cases for fuzz testing."""
    random.seed(42)
    airports = list(Airport)
    seat_types = list(SeatType)
    max_stops = list(MaxStops)
    sort_bys = list(SortBy)

    test_cases = []
    seen_combinations = set()

    while len(test_cases) < num_tests:
        dep_airport = random.choice(airports)
        arr_airport = random.choice(airports)
        if dep_airport == arr_airport:
            continue

        today = datetime.now()
        dep_date = today + timedelta(days=random.randint(1, 365))
        adults = random.randint(1, 4)
        children = random.randint(0, 2)
        infants_on_lap = random.randint(0, adults)
        infants_in_seat = random.randint(0, max(0, adults - infants_on_lap))
        seat_type = random.choice(seat_types)
        stops = random.choice(max_stops)
        sort_by = random.choice(sort_bys)

        test_case = (
            dep_airport,
            arr_airport,
            dep_date,
            adults,
            children,
            infants_on_lap,
            infants_in_seat,
            seat_type,
            stops,
            sort_by,
        )
        if test_case not in seen_combinations:
            seen_combinations.add(test_case)
            test_cases.append(test_case)

    return test_cases


@pytest.mark.fuzz
@pytest.mark.parallel
@pytest.mark.parametrize(
    "dep_airport, arr_airport, dep_date, adults, children, infants_on_lap, infants_in_seat, seat_type, stops, sort_by",
    generate_random_test_cases(num_tests=100),
    ids=generate_test_id,
)
def test_search_fuzz(
    search: SearchFlights,
    dep_airport: Airport,
    arr_airport: Airport,
    dep_date: datetime,
    adults: int,
    children: int,
    infants_on_lap: int,
    infants_in_seat: int,
    seat_type: SeatType,
    stops: MaxStops,
    sort_by: SortBy,
):
    """
    Parameterized fuzz test for flight search with various filter combinations.
    Designed to run in parallel using pytest-xdist.
    """
    passenger_info = PassengerInfo(
        adults=adults,
        children=children,
        infants_on_lap=infants_on_lap,
        infants_in_seat=infants_in_seat,
    )

    search_filters = SearchFlightsFilters(
        departure_airport=dep_airport,
        arrival_airport=arr_airport,
        departure_date=dep_date.strftime("%Y-%m-%d"),
        passenger_info=passenger_info,
        seat_type=seat_type,
        stops=stops,
        sort_by=sort_by,
    )

    flights = search.search(search_filters)
    assert isinstance(flights, list) or flights is None
