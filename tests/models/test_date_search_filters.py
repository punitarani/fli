from datetime import datetime, timedelta

import pytest

from fli.models import (
    Airline,
    Airport,
    DateSearchFilters,
    FlightSegment,
    LayoverRestrictions,
    MaxStops,
    PassengerInfo,
    PriceLimit,
    SeatType,
    TimeRestrictions,
)


def get_future_date(days: int = 30) -> str:
    """Generate a future date string in YYYY-MM-DD format."""
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


# Generate dynamic future dates for tests
TRAVEL_DATE = get_future_date(30)
FROM_DATE_1 = get_future_date(20)
TO_DATE_1 = get_future_date(40)
FROM_DATE_2 = get_future_date(10)
TO_DATE_2 = get_future_date(55)
FROM_DATE_3 = get_future_date(5)
TO_DATE_3 = get_future_date(70)

TEST_CASES = [
    {
        "name": "Test 1: Flight Search Data",
        "search": DateSearchFilters(
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
            from_date=FROM_DATE_1,
            to_date=TO_DATE_1,
        ),
        "formatted": [
            None,
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
            [
                FROM_DATE_1,
                TO_DATE_1,
            ],
        ],
        "encoded": None,
    },
    {
        "name": "Test 2: Flight Search Data",
        "search": DateSearchFilters(
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
            from_date=FROM_DATE_2,
            to_date=TO_DATE_2,
        ),
        "formatted": [
            None,
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
            [
                FROM_DATE_2,
                TO_DATE_2,
            ],
        ],
        "encoded": None,
    },
    {
        "name": "Test 3: Flight Search Data",
        "search": DateSearchFilters(
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
            from_date=FROM_DATE_3,
            to_date=TO_DATE_3,
        ),
        "formatted": [
            None,
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
            [
                FROM_DATE_3,
                TO_DATE_3,
            ],
        ],
    },
]


@pytest.mark.parametrize("test_case", TEST_CASES, ids=[tc["name"] for tc in TEST_CASES])
def test_date_search_filters(test_case):
    """Test date search filters conversion to DateSearchFilters."""
    search_filters = test_case["search"]
    expected_formatted = test_case["formatted"]

    # Test conversion to DateSearchFilters
    formatted_filters = DateSearchFilters.format(search_filters)
    assert formatted_filters == expected_formatted
