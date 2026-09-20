"""Fuzz testing for Search functionality."""

import random
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
from fli.search import SearchFlights


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


def generate_random_test_cases(num_tests: int) -> list[tuple]:
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
        # PassengerInfo caps the booking-wide total at 9 (Google Flights' own
        # limit) and requires infants_on_lap <= adults; bound each draw by the
        # remaining headroom so the generator never produces a mix the model
        # would reject outright.
        remaining_after_children = max(0, 9 - adults - children)
        infants_on_lap = random.randint(0, min(adults, remaining_after_children))
        remaining_after_lap = max(0, remaining_after_children - infants_on_lap)
        infants_in_seat = random.randint(
            0, min(max(0, adults - infants_on_lap), remaining_after_lap)
        )
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
    "dep_airport, arr_airport, dep_date, adults, children, infants_on_lap, infants_in_seat, seat_type, stops, sort_by",  # noqa: E501
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
    """Parameterized fuzz test for flight search with various filter combinations.

    Designed to run in parallel using pytest-xdist.
    """
    passenger_info = PassengerInfo(
        adults=adults,
        children=children,
        infants_on_lap=infants_on_lap,
        infants_in_seat=infants_in_seat,
    )

    search_filters = FlightSearchFilters(
        passenger_info=passenger_info,
        flight_segments=[
            FlightSegment(
                departure_airport=[[dep_airport, 0]],
                arrival_airport=[[arr_airport, 0]],
                travel_date=dep_date.strftime("%Y-%m-%d"),
            )
        ],
        stops=stops,
        seat_type=seat_type,
        sort_by=sort_by,
    )

    flights = search.search(search_filters)
    assert isinstance(flights, list) or flights is None
