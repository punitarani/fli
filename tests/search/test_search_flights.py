"""Tests for Search class."""

from datetime import datetime, timedelta

import pytest
from tenacity import retry, stop_after_attempt, wait_exponential

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


# TODO: These round-trip tests hit the live Google Flights API with multiple
# sequential requests (outbound + return for each result), causing frequent
# timeouts on CI runners. They should be refactored to mock the HTTP client
# instead of making real API calls. See GitHub issue for follow-up.
#
# def test_basic_round_trip_search(search, round_trip_search_params):
# def test_complex_round_trip_search(search, complex_round_trip_params):
# def test_round_trip_with_selected_outbound(search, round_trip_search_params):
# def test_round_trip_result_structure(search, search_params_fixture, request):


class TestParsePriceInfo:
    """Tests for _parse_price_info.

    Empty / missing price blocks return ``(None, None)`` so unbookable
    carriers (Eastar Jet, Aero K, etc.) stay visible to consumers via
    ``FlightResult.price is None``. Only structurally-valid blocks with
    a corrupt price value raise — those rows get skipped by
    ``parse_flight_row``.
    """

    def test_parse_price_info_valid_data(self):
        """Valid price data: returns the numeric price."""
        data = [None, [[100, 200, 299.99]]]
        price, currency = SearchFlights._parse_price_info(data)
        assert price == 299.99
        assert currency is None

    def test_parse_price_info_empty_inner_list(self):
        """An empty inner price list (Eastar Jet shape) returns None."""
        data = [None, [[]]]
        price, _ = SearchFlights._parse_price_info(data)
        assert price is None

    def test_parse_price_info_empty_outer_list(self):
        """An empty outer price list has no head element; returns None."""
        data = [None, []]
        price, _ = SearchFlights._parse_price_info(data)
        assert price is None

    def test_parse_price_info_none_price_section(self):
        """A ``None`` price section means no usable price; returns None."""
        data = [None, None]
        price, _ = SearchFlights._parse_price_info(data)
        assert price is None

    def test_parse_price_info_missing_price_section(self):
        """A row with no ``row[1]`` at all returns None."""
        data = [None]
        price, _ = SearchFlights._parse_price_info(data)
        assert price is None

    def test_parse_price_info_inner_list_none(self):
        """A ``None`` head element returns None."""
        data = [None, [None]]
        price, _ = SearchFlights._parse_price_info(data)
        assert price is None

    def test_parse_price_info_non_numeric_price_raises(self):
        """A non-numeric value at ``price[-1]`` is malformed; raise so the row is skipped."""
        data = [None, [[100, 200, "not-a-price"]]]
        with pytest.raises(ValueError):
            SearchFlights._parse_price_info(data)

    def test_parse_price_info_unbookable_carrier_token(self):
        """Eastar Jet-style payload (empty inner list, no currency in token).

        Real shape captured from Google Flights for ZE6078 ICN-NRT 2026-06-15:
        the inner price list is empty and the base64 token carries no nested
        price/currency message. Parser should signal unknown via None, not
        raise.
        """
        data = [
            None,
            [
                [],
                "CjRIRlNfZ0FHamhKdElBR3NHOVFCRy0tLS0tLS0tLW9rZXExOEFBQUFBR29IOEY4QXY4RGVBEgVaRTYwNzgc",
            ],
        ]
        price, currency = SearchFlights._parse_price_info(data)
        assert price is None
        assert currency is None

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
