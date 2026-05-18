"""Tests for the paired-row parser introduced to fix Issue #165.

Google Flights returns ROUND_TRIP + BUSINESS/FIRST initial results as
``[outbound_row, return_row]`` pairs rather than individual outbound rows.
The standard ``parse_flight_row`` mistakes the return row for a price block
and raises ValueError for every row, causing SearchParseError.

These tests verify:
1. ``_try_parse_flight_pair`` correctly extracts both legs from a paired item.
2. The ``_fetch_flights`` path silently recovers paired rows and returns
   ``(FlightResult, FlightResult)`` tuples in the result list.
3. ``search()`` surfaces those tuples directly (no expansion needed).
"""

from __future__ import annotations

from unittest.mock import patch

from fli.models import Airline, Airport, FlightResult
from fli.search._decoders import _try_parse_flight_pair, parse_flight_row
from fli.search.flights import SearchFlights

# ---------------------------------------------------------------------------
# Helpers re-used from test_parse_flights_data
# ---------------------------------------------------------------------------


def _leg(*, dep_iata, arr_iata, airline_code="BA", flight_number="117"):
    leg = [None] * 33
    leg[3] = dep_iata
    leg[4] = dep_iata + " Airport"
    leg[5] = arr_iata + " Airport"
    leg[6] = arr_iata
    leg[8] = [10, 30]
    leg[10] = [22, 45]
    leg[11] = 675
    leg[12] = [None] * 12
    leg[14] = "31 in"
    leg[17] = "Boeing 777"
    leg[19] = False
    leg[20] = [2026, 7, 11]
    leg[21] = [2026, 7, 11]
    leg[22] = [airline_code, flight_number, None, "British Airways"]
    leg[30] = "31 inches"
    leg[31] = 450000
    leg[32] = 3  # business cabin
    return leg


def _row(*, dep_iata, arr_iata, price=3200, airline_code="BA", flight_number="117"):
    """Build a minimal valid 11-element flight row."""
    detail = [None] * 25
    detail[0] = airline_code
    detail[1] = ["British Airways"]
    leg = _leg(
        dep_iata=dep_iata, arr_iata=arr_iata, airline_code=airline_code, flight_number=flight_number
    )
    detail[2] = [leg]
    detail[9] = 675
    row = [None] * 11
    row[0] = detail
    row[1] = [[None, price], None]
    row[8] = "SAMPLE_TOKEN"
    return row


# ---------------------------------------------------------------------------
# _try_parse_flight_pair
# ---------------------------------------------------------------------------


class TestTryParseFlightPair:
    """Unit tests for the paired-row decoder."""

    def test_valid_pair_returns_tuple(self):
        outbound = _row(dep_iata="LAX", arr_iata="LHR", price=3200)
        inbound = _row(dep_iata="LHR", arr_iata="LAX", price=3200, flight_number="118")
        result = _try_parse_flight_pair([outbound, inbound])
        assert result is not None
        out, ret = result
        assert isinstance(out, FlightResult)
        assert isinstance(ret, FlightResult)
        assert out.legs[0].departure_airport == Airport.LAX
        assert out.legs[0].arrival_airport == Airport.LHR
        assert ret.legs[0].departure_airport == Airport.LHR
        assert ret.legs[0].arrival_airport == Airport.LAX

    def test_valid_pair_preserves_price(self):
        outbound = _row(dep_iata="LAX", arr_iata="LHR", price=3100)
        inbound = _row(dep_iata="LHR", arr_iata="LAX", price=3100, flight_number="118")
        out, ret = _try_parse_flight_pair([outbound, inbound])
        assert out.price == 3100.0
        assert ret.price == 3100.0

    def test_returns_none_for_single_row(self):
        """A normal 11-element single row is not mistaken for a paired row."""
        row = _row(dep_iata="JFK", arr_iata="LAX")
        assert _try_parse_flight_pair(row) is None

    def test_returns_none_for_non_list(self):
        assert _try_parse_flight_pair(None) is None
        assert _try_parse_flight_pair(42) is None
        assert _try_parse_flight_pair("string") is None

    def test_returns_none_for_empty_list(self):
        assert _try_parse_flight_pair([]) is None

    def test_returns_none_for_single_element_list(self):
        row = _row(dep_iata="JFK", arr_iata="LAX")
        assert _try_parse_flight_pair([row]) is None

    def test_returns_none_when_subrow_unparseable(self):
        """If either sub-row is malformed, the pair is silently skipped."""
        outbound = _row(dep_iata="LAX", arr_iata="LHR")
        bad = [None, None]  # clearly not a flight row
        assert _try_parse_flight_pair([outbound, bad]) is None

    def test_single_row_still_parses_normally(self):
        """Confirm parse_flight_row is unaffected by the paired-row changes."""
        row = _row(dep_iata="LAX", arr_iata="LHR")
        flight = parse_flight_row(row)
        assert flight.price == 3200.0
        assert flight.legs[0].departure_airport == Airport.LAX


# ---------------------------------------------------------------------------
# _fetch_flights integration — paired rows returned as tuples
# ---------------------------------------------------------------------------


class TestFetchFlightsPairedRows:
    """_fetch_flights returns (FlightResult, FlightResult) tuples for paired rows."""

    def _build_inner(self, rows: list) -> list:
        """Build a minimal ``inner`` list as parse_first_wrb_payload would return."""
        inner = [None] * 5
        inner[2] = [rows, None, False, False, [1]]
        inner[3] = [[], 0, False, False, [1]]
        return inner

    def test_single_rows_returned_as_flat_list(self):
        row = _row(dep_iata="LAX", arr_iata="LHR")
        inner = self._build_inner([row])

        client = SearchFlights()
        with (
            patch("fli.search.flights.parse_first_wrb_payload", return_value=inner),
            patch.object(
                client.client,
                "post",
            ) as mock_post,
        ):
            mock_post.return_value.text = ""
            mock_post.return_value.raise_for_status = lambda: None

            from datetime import datetime, timedelta

            from fli.models import FlightSearchFilters, FlightSegment, PassengerInfo

            future = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
            filters = FlightSearchFilters(
                passenger_info=PassengerInfo(adults=1),
                flight_segments=[
                    FlightSegment(
                        departure_airport=[[Airport.LAX, 0]],
                        arrival_airport=[[Airport.LHR, 0]],
                        travel_date=future,
                    )
                ],
            )
            result = client._fetch_flights(
                filters, currency=None, language=None, country=None, capture_session=False
            )

        assert result is not None
        assert len(result) == 1
        assert isinstance(result[0], FlightResult)

    def test_paired_rows_returned_as_tuples(self):
        """Paired [outbound, return] items become (FlightResult, FlightResult) tuples."""
        outbound = _row(dep_iata="LAX", arr_iata="LHR", price=3200)
        inbound = _row(dep_iata="LHR", arr_iata="LAX", price=3200, flight_number="118")
        paired = [outbound, inbound]
        inner = self._build_inner([paired, paired])  # two identical combos

        client = SearchFlights()
        with (
            patch("fli.search.flights.parse_first_wrb_payload", return_value=inner),
            patch.object(
                client.client,
                "post",
            ) as mock_post,
        ):
            mock_post.return_value.text = ""
            mock_post.return_value.raise_for_status = lambda: None

            from datetime import datetime, timedelta

            from fli.models import FlightSearchFilters, FlightSegment, PassengerInfo

            future = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
            filters = FlightSearchFilters(
                passenger_info=PassengerInfo(adults=1),
                flight_segments=[
                    FlightSegment(
                        departure_airport=[[Airport.LAX, 0]],
                        arrival_airport=[[Airport.LHR, 0]],
                        travel_date=future,
                    )
                ],
            )
            result = client._fetch_flights(
                filters, currency=None, language=None, country=None, capture_session=False
            )

        assert result is not None
        assert len(result) == 2
        for item in result:
            assert isinstance(item, tuple)
            out, ret = item
            assert isinstance(out, FlightResult)
            assert isinstance(ret, FlightResult)
            assert out.legs[0].departure_airport == Airport.LAX
            assert ret.legs[0].departure_airport == Airport.LHR


# ---------------------------------------------------------------------------
# search() integration — pre-paired results bypass expansion
# ---------------------------------------------------------------------------


class TestSearchReturnsPairedResultsDirectly:
    """search() returns pre-paired (outbound, return) tuples without calling _expand_multi_leg."""

    def test_search_returns_tuples_for_paired_response(self):
        from datetime import datetime, timedelta

        from fli.models import (
            FlightLeg,
            FlightResult,
            FlightSearchFilters,
            FlightSegment,
            PassengerInfo,
            SeatType,
            TripType,
        )

        future = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")
        future2 = (datetime.now() + timedelta(days=74)).strftime("%Y-%m-%d")

        filters = FlightSearchFilters(
            trip_type=TripType.ROUND_TRIP,
            passenger_info=PassengerInfo(adults=2),
            flight_segments=[
                FlightSegment(
                    departure_airport=[[Airport.LAX, 0]],
                    arrival_airport=[[Airport.LHR, 0]],
                    travel_date=future,
                ),
                FlightSegment(
                    departure_airport=[[Airport.LHR, 0]],
                    arrival_airport=[[Airport.LAX, 0]],
                    travel_date=future2,
                ),
            ],
            seat_type=SeatType.BUSINESS,
        )

        def _make_result(dep: Airport, arr: Airport) -> FlightResult:
            return FlightResult(
                legs=[
                    FlightLeg(
                        airline=Airline.BA,
                        flight_number="117",
                        departure_airport=dep,
                        arrival_airport=arr,
                        departure_datetime=datetime(2026, 7, 11, 10, 30),
                        arrival_datetime=datetime(2026, 7, 11, 22, 45),
                        duration=675,
                    )
                ],
                price=3200.0,
                duration=675,
                stops=0,
            )

        pre_paired = (
            _make_result(Airport.LAX, Airport.LHR),
            _make_result(Airport.LHR, Airport.LAX),
        )

        client = SearchFlights()
        with (
            patch.object(
                SearchFlights,
                "_fetch_flights",
                return_value=[pre_paired],
            ),
            patch.object(
                SearchFlights,
                "_expand_multi_leg",
            ) as mock_expand,
        ):
            result = client.search(filters)

        # Expansion must not have been called — tuples were already present
        mock_expand.assert_not_called()
        assert result is not None
        assert len(result) == 1
        assert isinstance(result[0], tuple)
        assert result[0][0].legs[0].departure_airport == Airport.LAX
        assert result[0][1].legs[0].departure_airport == Airport.LHR
