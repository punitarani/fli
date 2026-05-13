"""Tests for Search class."""

from datetime import datetime, timedelta

import pytest
from tenacity import retry, stop_after_attempt, wait_exponential

from fli.models import (
    Airline,
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
    """Tests for _parse_price_info method handling missing/malformed price data."""

    def test_parse_price_info_valid_data(self):
        """Test _parse_price_info with valid price data."""
        data = [None, [[100, 200, 299.99]]]
        price, currency = SearchFlights._parse_price_info(data)
        assert price == 299.99
        assert currency is None

    def test_parse_price_info_empty_inner_list(self):
        """Test _parse_price_info returns 0.0 when inner price list is empty."""
        data = [None, [[]]]
        price, _ = SearchFlights._parse_price_info(data)
        assert price == 0.0

    def test_parse_price_info_empty_outer_list(self):
        """Test _parse_price_info returns 0.0 when outer price list is empty."""
        data = [None, []]
        price, _ = SearchFlights._parse_price_info(data)
        assert price == 0.0

    def test_parse_price_info_none_price_section(self):
        """Test _parse_price_info returns 0.0 when price section is None."""
        data = [None, None]
        price, _ = SearchFlights._parse_price_info(data)
        assert price == 0.0

    def test_parse_price_info_missing_price_section(self):
        """Test _parse_price_info returns 0.0 when data has no price section."""
        data = [None]
        price, _ = SearchFlights._parse_price_info(data)
        assert price == 0.0

    def test_parse_price_info_inner_list_none(self):
        """Test _parse_price_info returns 0.0 when inner list is None."""
        data = [None, [None]]
        price, _ = SearchFlights._parse_price_info(data)
        assert price == 0.0

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


def _make_leg(
    dep_airport: str,
    arr_airport: str,
    airline: str = "DL",
    flight_num: str = "100",
) -> list:
    """Build a minimal raw-API leg list with only the indices the parser reads."""
    leg = [None] * 23
    leg[3] = dep_airport
    leg[6] = arr_airport
    leg[8] = [10, 0]  # departure time
    leg[10] = [12, 0]  # arrival time
    leg[11] = 120  # leg duration (min)
    leg[20] = [2027, 2, 28]  # departure date
    leg[21] = [2027, 2, 28]  # arrival date
    leg[22] = [airline, flight_num]
    return leg


def _make_flight(legs: list[list], duration: int = 120, price: float = 299.99) -> list:
    """Build a minimal raw-API flight list around the given legs."""
    container = [None] * 10
    container[2] = legs
    container[9] = duration
    return [container, [[None, price]]]


class TestParseAirportAirline:
    """Tests for _parse_airport / _parse_airline handling of unknown codes (issue #146)."""

    def test_parse_airport_valid_code(self):
        """A known IATA airport code resolves to the matching enum member."""
        assert SearchFlights._parse_airport("JFK") == Airport.JFK

    def test_parse_airport_rail_station_code_raises_attribute_error(self):
        """Rail station codes (e.g., QKL for Cologne Hbf) must raise AttributeError.

        Regression for issue #146: Google Flights returns these codes for mixed
        air/rail itineraries; the parser must surface this so callers can skip
        the flight rather than crash the whole search.
        """
        with pytest.raises(AttributeError, match="QKL"):
            SearchFlights._parse_airport("QKL")

    def test_parse_airport_unknown_code_raises_attribute_error(self):
        """Any code not in the Airport enum raises AttributeError."""
        with pytest.raises(AttributeError):
            SearchFlights._parse_airport("ZZZ")

    def test_parse_airline_valid_code(self):
        """A known IATA airline code resolves to the matching enum member."""
        assert SearchFlights._parse_airline("DL") == Airline.DL

    def test_parse_airline_unknown_code_raises_attribute_error(self):
        """An unknown airline code raises AttributeError (e.g., rail operator)."""
        with pytest.raises(AttributeError):
            SearchFlights._parse_airline("XYZ")


class TestParseFlightsDataWithUnknownCodes:
    """End-to-end tests for _parse_flights_data with mixed valid/unknown codes."""

    def test_parse_succeeds_for_normal_flight(self):
        """A flight whose legs use only known airport codes parses successfully."""
        flight_data = _make_flight([_make_leg("LGW", "KRK", airline="LO", flight_num="280")])
        result = SearchFlights._parse_flights_data(flight_data)
        assert result.legs[0].departure_airport == Airport.LGW
        assert result.legs[0].arrival_airport == Airport.KRK
        assert result.legs[0].airline == Airline.LO

    def test_parse_raises_attribute_error_for_rail_station_leg(self):
        """A leg with a rail station code (QKL) raises AttributeError carrying the code.

        Regression for issue #146: this is the exact path that previously
        crashed the entire search. The surrounding loop in ``search`` catches
        this and skips the flight; the parser itself still surfaces the
        unknown code so callers can log/diagnose it.
        """
        flight_data = _make_flight([_make_leg("LGW", "QKL")])
        with pytest.raises(AttributeError, match="QKL"):
            SearchFlights._parse_flights_data(flight_data)

    def test_parse_raises_attribute_error_for_unknown_airline(self):
        """A leg with an unknown airline (e.g., a rail operator) raises AttributeError."""
        flight_data = _make_flight([_make_leg("LGW", "KRK", airline="XYZ")])
        with pytest.raises(AttributeError, match="XYZ"):
            SearchFlights._parse_flights_data(flight_data)


class TestSearchSkipsUnparseableFlights:
    """End-to-end test that ``search`` skips rail-mixed flights instead of crashing.

    Regression for issue #146 (and the general fix in #143).
    """

    @staticmethod
    def _build_api_response(flight_rows: list[list]) -> str:
        """Wrap synthetic flight rows in the layered JSON envelope the search expects."""
        import json

        # encoded_filters[2][0] is the primary results list the search reads.
        inner = json.dumps([None, None, [flight_rows], None])
        outer = json.dumps([[None, None, inner]])
        return ")]}'" + outer

    def test_search_returns_valid_flights_and_skips_rail_mixed(self, monkeypatch):
        """A response mixing valid flights with rail-station flights must not crash.

        Asserts that the valid flights are returned, and that the rail-station
        flight (with QKL = Cologne Hbf) is silently skipped.
        """
        valid_flight = _make_flight([_make_leg("LGW", "KRK", airline="LO", flight_num="280")])
        rail_flight = _make_flight([_make_leg("LGW", "QKL", airline="LO", flight_num="999")])

        class FakeResponse:
            def __init__(self, text: str) -> None:
                self.text = text

            def raise_for_status(self) -> None:
                return None

        class FakeClient:
            def __init__(self, payload: str) -> None:
                self._payload = payload

            def post(self, **_kwargs) -> FakeResponse:
                return FakeResponse(self._payload)

        payload = self._build_api_response([valid_flight, rail_flight])

        search = SearchFlights()
        search.client = FakeClient(payload)

        filters = FlightSearchFilters(
            passenger_info=PassengerInfo(adults=1),
            flight_segments=[
                FlightSegment(
                    departure_airport=[[Airport.LGW, 0]],
                    arrival_airport=[[Airport.KRK, 0]],
                    travel_date=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                )
            ],
            stops=MaxStops.ANY,
            seat_type=SeatType.ECONOMY,
            sort_by=SortBy.CHEAPEST,
            show_all_results=False,
        )

        results = search.search(filters)
        assert results is not None
        assert len(results) == 1
        assert results[0].legs[0].departure_airport == Airport.LGW
        assert results[0].legs[0].arrival_airport == Airport.KRK

    def test_search_returns_none_when_all_results_are_rail_mixed(self, monkeypatch):
        """If every flight has a rail station, ``search`` returns None rather than crashing."""
        rail_flight = _make_flight([_make_leg("LGW", "QKL")])

        class FakeResponse:
            def __init__(self, text: str) -> None:
                self.text = text

            def raise_for_status(self) -> None:
                return None

        class FakeClient:
            def __init__(self, payload: str) -> None:
                self._payload = payload

            def post(self, **_kwargs) -> FakeResponse:
                return FakeResponse(self._payload)

        payload = self._build_api_response([rail_flight])

        search = SearchFlights()
        search.client = FakeClient(payload)

        filters = FlightSearchFilters(
            passenger_info=PassengerInfo(adults=1),
            flight_segments=[
                FlightSegment(
                    departure_airport=[[Airport.LGW, 0]],
                    arrival_airport=[[Airport.KRK, 0]],
                    travel_date=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                )
            ],
            stops=MaxStops.ANY,
            seat_type=SeatType.ECONOMY,
            sort_by=SortBy.CHEAPEST,
            show_all_results=False,
        )

        # Must NOT raise the AttributeError described in issue #146.
        assert search.search(filters) is None
