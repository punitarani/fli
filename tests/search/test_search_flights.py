"""Tests for Search class."""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from tenacity import retry, stop_after_attempt, wait_exponential

from fli.models import (
    Airport,
    FlightResult,
    FlightSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
)
from fli.models.google_flights.base import TripType
from fli.search import SearchFlights


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
def search_with_retry(search: SearchFlights, search_params):
    """Search with retry logic for flaky API responses."""
    results = search.search(search_params)
    if not results:
        raise ValueError("Empty results, retrying...")
    return results


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
        show_all_results=False,
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
        show_all_results=False,
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
        show_all_results=False,
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
        show_all_results=False,
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


def _make_leg_data(
    dep_airport,
    arr_airport,
    airline_code,
    flight_num,
    dep_date,
    arr_date,
    dep_time,
    arr_time,
    duration,
):
    """Build a single leg data entry matching the raw Google Flights API format."""
    # Indices: 3=dep_airport, 6=arr_airport, 8=dep_time, 10=arr_time,
    #          11=duration, 20=dep_date, 21=arr_date, 22=[airline, flight_num]
    leg = [None] * 23
    leg[3] = dep_airport
    leg[6] = arr_airport
    leg[8] = dep_time
    leg[10] = arr_time
    leg[11] = duration
    leg[20] = dep_date
    leg[21] = arr_date
    leg[22] = [airline_code, flight_num]
    return leg


def _make_flight_data(legs, total_duration, price):
    """Build a flight data entry matching the raw Google Flights API format."""
    flight_info = [None] * 10
    flight_info[2] = legs
    flight_info[9] = total_duration
    price_info = [[None, price], None]
    return [flight_info, price_info]


def _make_api_response(*flight_data_entries):
    """Build a mock API response matching the raw Google Flights response format."""
    inner_data = [None, None, [list(flight_data_entries)], None]
    response_text = ")]}'\n" + json.dumps([[None, None, json.dumps(inner_data)]])
    mock_response = MagicMock()
    mock_response.text = response_text
    return mock_response


def _make_outbound_flights():
    """Create mock outbound flight data (SFO -> JFK)."""
    return [
        _make_flight_data(
            legs=[
                _make_leg_data(
                    "SFO", "JFK", "DL", "DL100", [2026, 5, 2], [2026, 5, 2], [8, 0], [16, 30], 330
                )
            ],
            total_duration=330,
            price=299.99,
        ),
        _make_flight_data(
            legs=[
                _make_leg_data(
                    "SFO", "JFK", "UA", "UA200", [2026, 5, 2], [2026, 5, 2], [10, 0], [18, 15], 315
                )
            ],
            total_duration=315,
            price=349.99,
        ),
    ]


def _make_return_flights():
    """Create mock return flight data (JFK -> SFO)."""
    return [
        _make_flight_data(
            legs=[
                _make_leg_data(
                    "JFK", "SFO", "DL", "DL101", [2026, 5, 9], [2026, 5, 9], [9, 0], [12, 30], 390
                )
            ],
            total_duration=390,
            price=279.99,
        ),
        _make_flight_data(
            legs=[
                _make_leg_data(
                    "JFK", "SFO", "UA", "UA201", [2026, 5, 9], [2026, 5, 9], [11, 0], [14, 45], 405
                )
            ],
            total_duration=405,
            price=319.99,
        ),
    ]


def _make_complex_outbound_flights():
    """Create mock outbound flights with a connection (LAX -> ORD)."""
    return [
        _make_flight_data(
            legs=[
                _make_leg_data(
                    "LAX", "DFW", "AA", "AA300", [2026, 6, 1], [2026, 6, 1], [7, 0], [12, 30], 210
                ),
                _make_leg_data(
                    "DFW", "ORD", "AA", "AA301", [2026, 6, 1], [2026, 6, 1], [14, 0], [16, 30], 150
                ),
            ],
            total_duration=360,
            price=499.99,
        ),
    ]


def _make_complex_return_flights():
    """Create mock return flights with a connection (ORD -> LAX)."""
    return [
        _make_flight_data(
            legs=[
                _make_leg_data(
                    "ORD", "DFW", "AA", "AA302", [2026, 6, 15], [2026, 6, 15], [8, 0], [10, 30], 150
                ),
                _make_leg_data(
                    "DFW",
                    "LAX",
                    "AA",
                    "AA303",
                    [2026, 6, 15],
                    [2026, 6, 15],
                    [12, 0],
                    [13, 30],
                    210,
                ),
            ],
            total_duration=360,
            price=479.99,
        ),
    ]


@patch("fli.search.flights.get_client")
def test_basic_round_trip_search(mock_get_client, round_trip_search_params):
    """Test basic round-trip search with mocked HTTP client."""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    outbound_response = _make_api_response(*_make_outbound_flights())
    return_response = _make_api_response(*_make_return_flights())
    # First call returns outbound flights, subsequent calls return return flights
    mock_client.post.side_effect = [outbound_response, return_response, return_response]
    # Expect 3 calls: 1 outbound + 1 return per selected outbound (top_n=2)

    search = SearchFlights()
    results = search.search(round_trip_search_params, top_n=2)
    assert len(results) == 4  # 2 outbound × 2 return
    # 1 outbound call + 2 return calls (one per outbound flight)
    assert mock_client.post.call_count == 3


@patch("fli.search.flights.get_client")
def test_complex_round_trip_search(mock_get_client, complex_round_trip_params):
    """Test complex round-trip search with multiple passengers and connections."""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    outbound_response = _make_api_response(*_make_complex_outbound_flights())
    return_response = _make_api_response(*_make_complex_return_flights())
    mock_client.post.side_effect = [outbound_response, return_response]

    search = SearchFlights()
    results = search.search(complex_round_trip_params, top_n=1)

    assert results is not None
    assert isinstance(results, list)
    assert len(results) > 0
    for combo in results:
        assert isinstance(combo, tuple)
        assert len(combo) == 2
        # Outbound has a connection (2 legs)
        assert combo[0].stops == 1
        assert len(combo[0].legs) == 2
        # Return also has a connection (2 legs)
        assert combo[1].stops == 1
        assert len(combo[1].legs) == 2


@patch("fli.search.flights.get_client")
def test_round_trip_with_selected_outbound(mock_get_client, round_trip_search_params):
    """Test that round-trip search selects outbound and fetches returns."""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    outbound_response = _make_api_response(*_make_outbound_flights())
    return_response = _make_api_response(*_make_return_flights())
    mock_client.post.side_effect = [outbound_response, return_response]

    search = SearchFlights()
    results = search.search(round_trip_search_params, top_n=1)

    assert results is not None
    assert isinstance(results, list)
    # With top_n=1, only 1 outbound is selected, paired with return options
    assert len(results) > 0
    # HTTP client should be called twice: once for outbound, once for return
    assert mock_client.post.call_count == 2


@pytest.mark.parametrize(
    "search_params_fixture",
    [
        "round_trip_search_params",
        "complex_round_trip_params",
    ],
)
@patch("fli.search.flights.get_client")
def test_round_trip_result_structure(mock_get_client, search_params_fixture, request):
    """Test the structure of round-trip search results."""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    if search_params_fixture == "round_trip_search_params":
        outbound_flights = _make_outbound_flights()
        return_flights = _make_return_flights()
    else:
        outbound_flights = _make_complex_outbound_flights()
        return_flights = _make_complex_return_flights()

    outbound_response = _make_api_response(*outbound_flights)
    return_response = _make_api_response(*return_flights)
    mock_client.post.side_effect = [outbound_response, return_response]

    search_params = request.getfixturevalue(search_params_fixture)
    search = SearchFlights()
    results = search.search(search_params, top_n=1)

    assert results is not None
    assert isinstance(results, list)
    for combo in results:
        assert isinstance(combo, tuple)
        assert len(combo) == 2
        for flight in combo:
            assert isinstance(flight, FlightResult)
            assert flight.price > 0
            assert flight.duration > 0
            assert flight.stops >= 0
            assert len(flight.legs) > 0


class TestParsePrice:
    """Tests for _parse_price method handling missing/malformed price data."""

    def test_parse_price_valid_data(self):
        """Test _parse_price with valid price data."""
        data = [None, [[100, 200, 299.99]]]
        assert SearchFlights._parse_price(data) == 299.99

    def test_parse_price_empty_inner_list(self):
        """Test _parse_price returns 0.0 when inner price list is empty."""
        data = [None, [[]]]
        assert SearchFlights._parse_price(data) == 0.0

    def test_parse_price_empty_outer_list(self):
        """Test _parse_price returns 0.0 when outer price list is empty."""
        data = [None, []]
        assert SearchFlights._parse_price(data) == 0.0

    def test_parse_price_none_price_section(self):
        """Test _parse_price returns 0.0 when price section is None."""
        data = [None, None]
        assert SearchFlights._parse_price(data) == 0.0

    def test_parse_price_missing_price_section(self):
        """Test _parse_price returns 0.0 when data has no price section."""
        data = [None]
        assert SearchFlights._parse_price(data) == 0.0

    def test_parse_price_inner_list_none(self):
        """Test _parse_price returns 0.0 when inner list is None."""
        data = [None, [None]]
        assert SearchFlights._parse_price(data) == 0.0

    def test_parse_currency_from_live_price_token(self):
        """_parse_currency should decode the returned currency from a live token sample."""
        data = [
            None,
            [
                [None, 118],
                "CjRIQktCNmV1UjNqNjhBR043X0FCRy0tLS0tLS0tLS12dGpkN0FBQUFBR25JcWZNS2pGTTBBEgZV"
                "QTIyMDkaCgjcWxACGgNVU0Q4HHDcWw==",
            ],
        ]
        assert SearchFlights._parse_currency(data) == "USD"

    def test_parse_price_info_combines_price_and_currency(self):
        """_parse_price_info should preserve price and extract the returned currency."""
        data = [
            None,
            [
                [None, 118],
                "CjRIQktCNmV1UjNqNjhBR043X0FCRy0tLS0tLS0tLS12dGpkN0FBQUFBR25JcWZNS2pGTTBBEgZV"
                "QTIyMDkaCgjcWxACGgNVU0Q4HHDcWw==",
            ],
        ]
        assert SearchFlights._parse_price_info(data) == (118.0, "USD")
