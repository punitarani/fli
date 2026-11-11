from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from fli.models import (
    Airline,
    Airport,
    Alliance,
    BagsFilter,
    ExplorePlace,
    ExploreRegion,
    ExploreSearchFilters,
    MaxStops,
    PassengerInfo,
    PriceLimit,
    SeatType,
    TripType,
)


def get_future_date(days: int = 30) -> str:
    """Generate a future date string in YYYY-MM-DD format."""
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


DEPARTURE_DATE = get_future_date(30)

TEST_CASES = [
    {
        # Replicates the richest captured HAR request (idx 337): London city
        # -> Southern Europe with every filter set. The expected literal below
        # is the decoded f.req inner payload from the capture (date swapped
        # for a future one).
        "name": "HAR capture replication (all filters)",
        "search": ExploreSearchFilters(
            origin=ExplorePlace(mid="/m/04jpl", type_code=4),
            destination=ExplorePlace(mid="/m/0250wj", type_code=6),
            trip_type=TripType.ONE_WAY,
            passenger_info=PassengerInfo(adults=1),
            seat_type=SeatType.ECONOMY,
            price_limit=PriceLimit(max_price=900),
            bags=BagsFilter(carry_on=True, checked_bags=0),
            trip_length_window=[4, 23, 0, 23],
            stops=MaxStops.NON_STOP,
            alliances=[Alliance.ONEWORLD],
            departure_date=DEPARTURE_DATE,
            max_duration=600,
        ),
        "formatted": [
            [],
            None,
            None,
            [
                None,
                None,
                2,
                None,
                [],
                1,
                [1, 0, 0, 0],
                [None, 900],
                None,
                None,
                [1, 0],
                None,
                None,
                [
                    [
                        [[["/m/04jpl", 4]]],
                        [[["/m/0250wj", 6]]],
                        [4, 23, 0, 23],
                        1,
                        ["ONEWORLD"],
                        None,
                        DEPARTURE_DATE,
                        [600],
                    ]
                ],
                None,
                None,
                None,
                1,
                None,
                None,
                None,
                None,
                None,
                None,
                1,
                1,
            ],
            None,
            1,
            None,
            0,
            None,
            0,
            [447, 712],
            3,
        ],
    },
    {
        "name": "Minimal: airport origin to ANYWHERE",
        "search": ExploreSearchFilters(origin=Airport.JFK, departure_date=DEPARTURE_DATE),
        "formatted": [
            [],
            None,
            None,
            [
                None,
                None,
                2,
                None,
                [],
                1,
                [1, 0, 0, 0],
                None,
                None,
                None,
                None,
                None,
                None,
                [
                    [
                        [[["JFK", 0]]],
                        [[["/m/02j71", 6]]],
                        None,
                        0,
                        None,
                        None,
                        DEPARTURE_DATE,
                        None,
                    ]
                ],
                None,
                None,
                None,
                1,
                None,
                None,
                None,
                None,
                None,
                None,
                1,
                1,
            ],
            None,
            1,
            None,
            0,
            None,
            0,
            [447, 712],
            3,
        ],
    },
    {
        "name": "Airlines and region enum destination",
        "search": ExploreSearchFilters(
            origin=Airport.LHR,
            destination=ExploreRegion.EUROPE,
            departure_date=DEPARTURE_DATE,
            airlines=[Airline.BA, Airline.AA],
            airlines_exclude=[Airline.FR],
        ),
        "formatted": [
            [],
            None,
            None,
            [
                None,
                None,
                2,
                None,
                [],
                1,
                [1, 0, 0, 0],
                None,
                None,
                None,
                None,
                None,
                None,
                [
                    [
                        [[["LHR", 0]]],
                        [[["/m/02j9z", 6]]],
                        None,
                        0,
                        ["AA", "BA"],
                        ["FR"],
                        DEPARTURE_DATE,
                        None,
                    ]
                ],
                None,
                None,
                None,
                1,
                None,
                None,
                None,
                None,
                None,
                None,
                1,
                1,
            ],
            None,
            1,
            None,
            0,
            None,
            0,
            [447, 712],
            3,
        ],
    },
]


@pytest.mark.parametrize("test_case", TEST_CASES, ids=[tc["name"] for tc in TEST_CASES])
def test_explore_search_filters_format(test_case):
    """Test explore filters format() against expected wire payloads."""
    assert test_case["search"].format() == test_case["formatted"]


def test_encode_wraps_and_urlencodes():
    """encode() must produce the double-encoded f.req value."""
    filters = ExploreSearchFilters(origin=Airport.JFK, departure_date=DEPARTURE_DATE)
    encoded = filters.encode()
    assert encoded.startswith("%5Bnull%2C%22%5B")  # [null,"[...
    assert "%20" not in encoded  # compact separators, no spaces


def test_multi_city_rejected():
    with pytest.raises(ValidationError, match="multi-city"):
        ExploreSearchFilters(
            origin=Airport.JFK, departure_date=DEPARTURE_DATE, trip_type=TripType.MULTI_CITY
        )


def test_departure_date_required():
    """The endpoint errors without a date, so the model requires one upfront."""
    with pytest.raises(ValidationError, match="departure_date"):
        ExploreSearchFilters(origin=Airport.JFK)


def test_past_departure_date_rejected():
    past = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    with pytest.raises(ValidationError, match="past"):
        ExploreSearchFilters(origin=Airport.JFK, departure_date=past)


def test_bad_mid_rejected():
    with pytest.raises(ValidationError, match="knowledge-graph"):
        ExplorePlace(mid="LON")


def test_same_origin_destination_rejected():
    with pytest.raises(ValidationError, match="same place"):
        ExploreSearchFilters(
            origin=ExplorePlace(mid="/m/02j9z", type_code=6),
            destination=ExploreRegion.EUROPE,
            departure_date=DEPARTURE_DATE,
        )


def test_bags_order_is_carry_on_first():
    """HAR-confirmed: explore bags slot is [carry_on, checked] (reverse of dates)."""
    filters = ExploreSearchFilters(
        origin=Airport.JFK,
        departure_date=DEPARTURE_DATE,
        bags=BagsFilter(carry_on=False, checked_bags=2),
    )
    assert filters.format()[3][10] == [0, 2]


@pytest.mark.parametrize(
    "window", [[], [4, 23], [4, 23, 7, 7, 0], [3, 23, 7, 7], [4, 23, -1, 7], [4, 23, 14, 7]]
)
def test_invalid_trip_window_rejected(window):
    with pytest.raises(ValidationError, match="trip_length_window"):
        ExploreSearchFilters(
            origin=Airport.LHR, departure_date=DEPARTURE_DATE, trip_length_window=window
        )


@pytest.mark.parametrize("window", [None, [4, 23, 0, 23], [4, 23, 7, 7]])
def test_valid_one_way_trip_window(window):
    filters = ExploreSearchFilters(
        origin=Airport.LHR, departure_date=DEPARTURE_DATE, trip_length_window=window
    )
    assert filters.format()[3][13][0][2] == window


@pytest.mark.parametrize(
    "destination",
    [
        Airport.LHR,
        ExplorePlace(mid="/m/04jpl", type_code=4),
        ExplorePlace(mid="/m/04jpl", type_code=0),
    ],
)
def test_non_region_destination_rejected(destination):
    """Google answers airport and city-typed destinations with error 3; fail locally."""
    with pytest.raises(ValidationError, match="destination"):
        ExploreSearchFilters(
            origin=Airport.JFK, destination=destination, departure_date=DEPARTURE_DATE
        )


@pytest.mark.parametrize(
    "destination", [ExploreRegion.EUROPE, ExplorePlace(mid="/m/07ssc", type_code=6)]
)
def test_region_destination_accepted(destination):
    filters = ExploreSearchFilters(
        origin=Airport.JFK, destination=destination, departure_date=DEPARTURE_DATE
    )
    assert filters.format()[3][13][0][1][0][0][1] == 6


@pytest.mark.parametrize(
    "window", [None, [4, 23, 0, 23], [4, 23, 0, 0], [4, 23, 1, 23], [4, 23, 7, 10]]
)
def test_round_trip_without_exact_length_rejected(window):
    """A range (or no window) makes Google quote one-way fares for some destinations."""
    with pytest.raises(ValidationError, match="exact trip length"):
        ExploreSearchFilters(
            origin=Airport.JFK,
            departure_date=DEPARTURE_DATE,
            trip_type=TripType.ROUND_TRIP,
            trip_length_window=window,
        )


@pytest.mark.parametrize("window", [[4, 23, 1, 1], [4, 23, 7, 7], [4, 23, 23, 23]])
def test_round_trip_with_exact_length_accepted(window):
    filters = ExploreSearchFilters(
        origin=Airport.JFK,
        departure_date=DEPARTURE_DATE,
        trip_type=TripType.ROUND_TRIP,
        trip_length_window=window,
    )
    assert filters.format()[3][13][0][2] == window
