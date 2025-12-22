from datetime import datetime, timedelta

import pytest

from fli.models import (
    Airline,
    Airport,
    FlightSearchFilters,
    FlightSegment,
    LayoverRestrictions,
    MaxStops,
    PassengerInfo,
    PriceLimit,
    SeatType,
    SortBy,
    TimeRestrictions,
)


def get_future_date(days: int = 30) -> str:
    """Generate a future date string in YYYY-MM-DD format."""
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


# Generate dynamic future date for tests
TRAVEL_DATE = get_future_date(30)

TEST_CASES = [
    {
        "name": "Test 1: Flight Search Data",
        "search": FlightSearchFilters(
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
                    time_restrictions=None,
                    travel_date=TRAVEL_DATE,
                )
            ],
            price_limit=None,
            stops=MaxStops.NON_STOP,
            seat_type=SeatType.PREMIUM_ECONOMY,
            sort_by=SortBy.CHEAPEST,
        ),
        "formatted": [
            [],
            [
                None,
                None,
                2,
                None,
                [],
                2,
                [1, 0, 0, 0],
                None,
                None,
                None,
                None,
                None,
                None,
                [
                    [
                        [[["PHX", 0]]],
                        [[["SFO", 0]]],
                        None,
                        1,
                        None,
                        None,
                        TRAVEL_DATE,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        3,
                    ]
                ],
                None,
                None,
                None,
                1,
            ],
            2,
            0,
            0,
            2,
        ],
        "encoded": None,
    },
    {
        "name": "Test 2: Flight Search Data",
        "search": FlightSearchFilters(
            passenger_info=PassengerInfo(
                adults=2,
                children=1,
                infants_in_seat=3,
                infants_on_lap=1,
            ),
            flight_segments=[
                FlightSegment(
                    departure_airport=[[Airport.PHX, 0]],
                    arrival_airport=[[Airport.SFO, 0]],
                    time_restrictions=None,
                    travel_date=TRAVEL_DATE,
                ),
            ],
            price_limit=None,
            stops=MaxStops.ONE_STOP_OR_FEWER,
            seat_type=SeatType.FIRST,
            sort_by=SortBy.TOP_FLIGHTS,
        ),
        "formatted": [
            [],
            [
                None,
                None,
                2,
                None,
                [],
                4,
                [2, 1, 1, 3],
                None,
                None,
                None,
                None,
                None,
                None,
                [
                    [
                        [[["PHX", 0]]],
                        [[["SFO", 0]]],
                        None,
                        2,
                        None,
                        None,
                        TRAVEL_DATE,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        3,
                    ],
                ],
                None,
                None,
                None,
                1,
            ],
            1,
            0,
            0,
            2,
        ],
        "encoded": None,
    },
    {
        "name": "Test 3: Flight Search Data",
        "search": FlightSearchFilters(
            passenger_info=PassengerInfo(
                adults=2,
                children=3,
                infants_in_seat=0,
                infants_on_lap=1,
            ),
            price_limit=PriceLimit(
                max_price=900,
            ),
            flight_segments=[
                FlightSegment(
                    departure_airport=[[Airport.PHX, 0]],
                    arrival_airport=[[Airport.SFO, 0]],
                    time_restrictions=TimeRestrictions(
                        earliest_departure=9,
                        latest_departure=20,
                        earliest_arrival=13,
                        latest_arrival=21,
                    ),
                    travel_date=TRAVEL_DATE,
                )
            ],
            stops=MaxStops.ANY,
            airlines=[Airline.AA, Airline.F9, Airline.UA],
            max_duration=660,
            layover_restrictions=LayoverRestrictions(
                airports=[Airport.LAX],
                max_duration=420,
            ),
        ),
        "formatted": [
            [],
            [
                None,
                None,
                2,
                None,
                [],
                1,
                [2, 3, 1, 0],
                [None, 900],
                None,
                None,
                None,
                None,
                None,
                [
                    [
                        [[["PHX", 0]]],
                        [[["SFO", 0]]],
                        [9, 20, 13, 21],
                        0,
                        ["AA", "F9", "UA"],
                        None,
                        TRAVEL_DATE,
                        [660],
                        None,
                        ["LAX"],
                        None,
                        None,
                        420,
                        None,
                        3,
                    ]
                ],
                None,
                None,
                None,
                1,
            ],
            0,
            0,
            0,
            2,
        ],
        "encoded": None,  # Dynamic date makes encoded string non-deterministic
    },
]


@pytest.mark.parametrize("test_case", TEST_CASES, ids=[tc["name"] for tc in TEST_CASES])
def test_flight_search_filters(test_case):
    """Test FlightSearchFilters formatting and encoding with various configurations."""
    search_filters = test_case["search"]

    # Test formatting
    formatted_filters = search_filters.format()
    assert formatted_filters == test_case["formatted"]

    # Test URL encoding
    encoded_filters = search_filters.encode()
    assert test_case["encoded"] is None or encoded_filters == test_case["encoded"]
