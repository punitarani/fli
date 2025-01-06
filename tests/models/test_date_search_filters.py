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
                    travel_date="2025-06-01",
                )
            ],
            price_limit=None,
            stops=MaxStops.NON_STOP,
            seat_type=SeatType.PREMIUM_ECONOMY,
            from_date="2025-05-20",
            to_date="2025-06-10",
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
                        "2025-06-01",
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
                "2025-05-20",
                "2025-06-10",
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
                    travel_date="2025-06-01",
                ),
            ],
            price_limit=None,
            stops=MaxStops.ONE_STOP_OR_FEWER,
            seat_type=SeatType.FIRST,
            from_date="2025-05-07",
            to_date="2025-06-25",
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
                        "2025-06-01",
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
                "2025-05-07",
                "2025-06-25",
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
                    travel_date="2025-06-01",
                )
            ],
            stops=MaxStops.ANY,
            airlines=[Airline.AA, Airline.F9, Airline.UA],
            max_duration=660,
            layover_restrictions=LayoverRestrictions(
                airports=[Airport.LAX],
                max_duration=420,
            ),
            from_date="2025-05-01",
            to_date="2025-07-01",
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
                        "2025-06-01",
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
                "2025-05-01",
                "2025-07-01",
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
