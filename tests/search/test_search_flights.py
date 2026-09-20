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


# Infant searches themselves work: the ``tfs`` passenger codes are verified
# against Google's own pricing (1=adult, 2=child, 3=lap infant, 4=infant in
# seat — see TestPassengerCodes in test_tfs.py and TestLapInfantPricing in
# test_search_flights_new_filters_live.py), and JFK->LHR economy with a lap
# infant returns 15 rows.
#
# What still comes back empty is this particular combination. Probed live
# 2026-09-20, one-stop-or-fewer, 60 days out:
#
#   2a+1c        FIRST    JFK->LAX   22 rows
#   1a           ECONOMY  JFK->LAX   35 rows
#   1a           FIRST    JFK->LHR   10 rows
#   2a+1c+1lap   FIRST    JFK->LAX    0 rows   <- this fixture
#   2a+1c+1lap   ECONOMY  JFK->LAX    0 rows
#   2a+1c+1seat  ECONOMY  JFK->LAX    0 rows
#   2a+1c+1lap   ECONOMY  JFK->LHR   15 rows
#   2a+1c+1lap   FIRST    JFK->LHR    0 rows
#
# So any infant on JFK->LAX, and any lap infant in FIRST, yields a page with
# no results grid, while the same passenger mix on other route/cabin pairs is
# served normally. Nothing in the request is rejected — Google simply inlines
# no rows — which reads as inventory rather than encoding. Non-strict so a
# change on Google's side surfaces as an unexpected pass.
INFANT_RESULTS_MISSING = pytest.mark.xfail(
    reason=(
        "Google inlines no results for JFK-LAX / LAX-ORD with a lap infant in "
        "FIRST or BUSINESS (0 rows); the same query without the infant returns "
        "22, and JFK-LHR economy with the same lap infant returns 15 — so the "
        "tfs passenger codes are correct and this is Google-side"
    ),
    strict=False,
)


@pytest.mark.parametrize(
    "search_params_fixture",
    [
        "basic_search_params",
        pytest.param("complex_search_params", marks=INFANT_RESULTS_MISSING),
    ],
)
def test_search_functionality(search, search_params_fixture, request):
    """Test flight search functionality with different data sets."""
    search_params = request.getfixturevalue(search_params_fixture)
    results = search.search(search_params)
    assert isinstance(results, list)


@INFANT_RESULTS_MISSING
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

    def _client_with_canned_response(self, monkeypatch, body: str) -> SearchFlights:
        # ``sf.client`` is the process-wide singleton, so the patch must be
        # undone when the test ends — ``monkeypatch`` does that for us.
        # A leaked patch here feeds this canned body to every later test.
        sf = SearchFlights()

        def _fake_get(url, **kwargs):  # noqa: ANN001
            return type(
                "R",
                (),
                {
                    "content": body.encode("utf-8"),
                    "text": body,
                    "raise_for_status": lambda self: None,
                },
            )()

        monkeypatch.setattr(sf.client, "get", _fake_get)
        return sf

    def _build_response(self, rows: list) -> str:
        """Wrap ``rows`` in a minimal but parser-valid search page."""
        import json

        # ``_capture_session_id`` reads ``payload[0][4]`` — give it a
        # plausible 5-element list. ``_fetch_flights`` reads
        # ``payload[2]`` and ``payload[3]`` — index 3 must exist (any list
        # value is fine; we put the rows on index 2).
        payload = [
            [None, None, None, None, "FAKE_SESSION"],
            None,
            [[*rows]],
            None,
        ]
        return (
            "<script>AF_initDataCallback({key: 'ds:1', hash: '1', data:"
            + json.dumps(payload, separators=(",", ":"))
            + ", sideChannel: {}});</script>"
        )

    def test_error_includes_sample_failure_reasons(self, monkeypatch):
        """When all rows fail, the error message names what went wrong."""
        from fli.search.flights import SearchParseError

        # Build a response with three flight rows that all trigger the
        # "price field is not numeric" branch in _parse_price_info.
        bad_row = [None, [[None, "not-a-number"]]]
        body = self._build_response([bad_row, bad_row, bad_row])

        sf = self._client_with_canned_response(monkeypatch, body)
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

    def test_error_dedups_repeated_reasons(self, monkeypatch):
        """Identical failure messages collapse to a single sample."""
        from fli.search.flights import SearchParseError

        bad_row = [None, [[None, "not-a-number"]]]
        body = self._build_response([bad_row] * 10)
        sf = self._client_with_canned_response(monkeypatch, body)
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


class TestTransientPageRetryOnFlightSearch:
    """Roughly one page in 60 arrives HTTP 200 with no ``ds:1`` blob.

    A round trip fetches six pages, so the per-search failure rate compounds.
    The retry lives in the shared page-fetch helper, so this exercises the same
    code path the date sweep uses.
    """

    BLANK = "<html>no data callback here</html>"

    @staticmethod
    def _filters() -> FlightSearchFilters:
        return FlightSearchFilters(
            passenger_info=PassengerInfo(adults=1),
            flight_segments=[
                FlightSegment(
                    departure_airport=[[Airport.JFK, 0]],
                    arrival_airport=[[Airport.LAX, 0]],
                    travel_date=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                )
            ],
        )

    @staticmethod
    def _good_page() -> str:
        import json

        from tests.search.test_parse_flights_data import _leg, _row

        payload = [
            [None, None, None, None, "FAKE_SESSION"],
            None,
            [[_row(legs=[_leg(dep_iata="JFK", arr_iata="LAX")])]],
            None,
        ]
        return (
            "<script>AF_initDataCallback({key: 'ds:1', hash: '1', data:"
            + json.dumps(payload, separators=(",", ":"))
            + ", sideChannel: {}});</script>"
        )

    def _sequenced(self, monkeypatch, bodies: list[str]):
        from fli.search import _tfs as tfs_module

        calls: list[str] = []
        slept: list[float] = []
        monkeypatch.setattr(tfs_module, "_sleep", slept.append)

        sf = SearchFlights()

        def _fake_get(url, **kwargs):  # noqa: ANN001
            body = bodies[min(len(calls), len(bodies) - 1)]
            calls.append(url)
            return type("R", (), {"text": body, "raise_for_status": lambda self: None})()

        monkeypatch.setattr(sf.client, "get", _fake_get)
        return sf, calls, slept

    def test_healthy_page_is_fetched_once(self, monkeypatch):
        sf, calls, slept = self._sequenced(monkeypatch, [self._good_page()])
        assert sf.search(self._filters())
        assert len(calls) == 1
        assert slept == []

    def test_missing_once_then_present_succeeds_in_two_fetches(self, monkeypatch):
        sf, calls, slept = self._sequenced(monkeypatch, [self.BLANK, self._good_page()])
        assert sf.search(self._filters())
        assert len(calls) == 2
        assert slept == [0.5]

    def test_missing_three_times_raises_after_exactly_three_fetches(self, monkeypatch):
        from fli.search.flights import SearchParseError

        sf, calls, slept = self._sequenced(monkeypatch, [self.BLANK])
        with pytest.raises(SearchParseError, match="no ds:1 payload"):
            sf.search(self._filters())
        assert len(calls) == 3
        assert slept == [0.5, 1.5]
