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
    """Distinguish "price unknown" (empty head → ``None``) from "malformed" (raises)."""

    def test_parse_price_info_valid_data(self):
        """Valid price data: returns the numeric price."""
        data = [None, [[100, 200, 299.99]]]
        price, currency = SearchFlights._parse_price_info(data)
        assert price == 299.99
        assert currency is None

    def test_parse_price_info_empty_inner_list_returns_none(self):
        """Empty head (``[[], ...]``) → ``price=None`` (issue #165: premium-RT)."""
        data = [None, [[]]]
        price, currency = SearchFlights._parse_price_info(data)
        assert price is None
        assert currency is None

    def test_parse_price_info_empty_outer_list_raises(self):
        """An empty outer price list has no head element; raise."""
        data = [None, []]
        with pytest.raises(ValueError):
            SearchFlights._parse_price_info(data)

    def test_parse_price_info_none_price_section_raises(self):
        """A None price section means no usable price; raise to skip the row."""
        data = [None, None]
        with pytest.raises(ValueError):
            SearchFlights._parse_price_info(data)

    def test_parse_price_info_missing_price_section_raises(self):
        """A row with no row[1] at all: raise (parse_flight_row will skip)."""
        data = [None]
        with pytest.raises(ValueError):
            SearchFlights._parse_price_info(data)

    def test_parse_price_info_inner_list_none_raises(self):
        """A None head element is malformed; raise."""
        data = [None, [None]]
        with pytest.raises(ValueError):
            SearchFlights._parse_price_info(data)

    def test_parse_price_info_non_numeric_price_raises(self):
        """A non-numeric value at price[-1] is malformed; raise."""
        data = [None, [[100, 200, "not-a-price"]]]
        with pytest.raises(ValueError):
            SearchFlights._parse_price_info(data)

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


class TestSearchParseErrorMessage:
    """SearchParseError surfaces sample reasons when every row fails."""

    def _client_with_canned_response(self, body: str) -> SearchFlights:
        from unittest.mock import patch

        sf = SearchFlights()

        def _fake_post(url, data, **kwargs):  # noqa: ANN001
            return type(
                "R",
                (),
                {
                    "content": body.encode("utf-8"),
                    "text": body,
                    "raise_for_status": lambda self: None,
                },
            )()

        patcher = patch.object(sf.client, "post", side_effect=_fake_post)
        patcher.start()
        return sf

    def _build_response(self, rows: list) -> str:
        """Wrap ``rows`` in a minimal but parser-valid wrb.fr response."""
        import json

        # ``_capture_session_id`` reads ``inner[0][4]`` — give it a
        # plausible 5-element list. ``_fetch_flights`` reads
        # ``inner[2]`` and ``inner[3]`` — index 3 must exist (any list
        # value is fine; we put the rows on index 2).
        inner = [
            [None, None, None, None, "FAKE_SESSION"],
            None,
            [[*rows]],
            None,
        ]
        outer = [["wrb.fr", None, json.dumps(inner, separators=(",", ":"))]]
        return ")]}'\n\n" + json.dumps(outer)

    def test_error_includes_sample_failure_reasons(self):
        """When all rows fail, the error message names what went wrong."""
        from fli.search.flights import SearchParseError

        # Build a response with three flight rows that all trigger the
        # "price field is not numeric" branch in _parse_price_info.
        bad_row = [None, [[None, "not-a-number"]]]
        body = self._build_response([bad_row, bad_row, bad_row])

        sf = self._client_with_canned_response(body)
        filters = FlightSearchFilters(
            passenger_info=PassengerInfo(adults=1),
            flight_segments=[
                FlightSegment(
                    departure_airport=[[Airport.JFK, 0]],
                    arrival_airport=[[Airport.LAX, 0]],
                    travel_date=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                )
            ],
        )
        with pytest.raises(SearchParseError, match="sample reasons:.*not numeric"):
            sf.search(filters)

    def test_error_dedups_repeated_reasons(self):
        """Identical failure messages collapse to a single sample."""
        from fli.search.flights import SearchParseError

        bad_row = [None, [[None, "not-a-number"]]]
        body = self._build_response([bad_row] * 10)
        sf = self._client_with_canned_response(body)
        filters = FlightSearchFilters(
            passenger_info=PassengerInfo(adults=1),
            flight_segments=[
                FlightSegment(
                    departure_airport=[[Airport.JFK, 0]],
                    arrival_airport=[[Airport.LAX, 0]],
                    travel_date=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                )
            ],
        )
        with pytest.raises(SearchParseError) as excinfo:
            sf.search(filters)
        # Only one unique reason — appears once in the message.
        msg = str(excinfo.value)
        assert msg.count("not numeric") == 1
        assert "0/10" in msg
