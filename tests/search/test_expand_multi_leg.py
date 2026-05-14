"""Unit tests for the multi-segment recursion in ``SearchFlights._expand_multi_leg``.

The recursion mutates a deep copy of the caller's filters as it walks
segment-by-segment, so it has been a quiet source of subtle bugs around
selected-flight state and locale kwarg propagation. These mock-based
tests pin the contract without hitting Google.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from fli.models import (
    Airline,
    Airport,
    FlightLeg,
    FlightResult,
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
    TripType,
)
from fli.search.flights import SearchFlights


def _future(days: int) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


def _result(dep: Airport, arr: Airport, hour: int = 9) -> FlightResult:
    return FlightResult(
        legs=[
            FlightLeg(
                airline=Airline.AA,
                flight_number="100",
                departure_airport=dep,
                arrival_airport=arr,
                departure_datetime=datetime(2026, 7, 15, hour, 0),
                arrival_datetime=datetime(2026, 7, 15, hour + 3, 0),
                duration=180,
            )
        ],
        price=300,
        currency="USD",
        duration=180,
        stops=0,
    )


def _three_segment_filters() -> FlightSearchFilters:
    """JFK → LAX → SEA → JFK multi-city, no selected_flights yet."""
    seg1 = FlightSegment(
        departure_airport=[[Airport.JFK, 0]],
        arrival_airport=[[Airport.LAX, 0]],
        travel_date=_future(60),
    )
    seg2 = FlightSegment(
        departure_airport=[[Airport.LAX, 0]],
        arrival_airport=[[Airport.SEA, 0]],
        travel_date=_future(63),
    )
    seg3 = FlightSegment(
        departure_airport=[[Airport.SEA, 0]],
        arrival_airport=[[Airport.JFK, 0]],
        travel_date=_future(66),
    )
    return FlightSearchFilters(
        trip_type=TripType.MULTI_CITY,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[seg1, seg2, seg3],
    )


class TestExpandMultiLeg:
    def test_multi_city_three_segments_produces_3_tuples(self):
        """3-segment multi-city flattens to 3-tuples of FlightResult.

        The recursion model: ``_expand_multi_leg`` calls ``self.search()``
        for the next segment, and ``search()`` internally calls
        ``_expand_multi_leg`` again until every-but-last segment has a
        ``selected_flight``. We mock the *inner* ``search()`` to return
        the already-expanded tail (a tuple) so the outer call can prepend
        ``outbound`` and produce the full 3-tuple.
        """
        client = SearchFlights()
        outbound = [_result(Airport.JFK, Airport.LAX)]
        leg2 = _result(Airport.LAX, Airport.SEA)
        leg3 = _result(Airport.SEA, Airport.JFK)

        def _fake_search(filters, **kwargs):
            # First (and only) recursive call: 1 segment selected; the real
            # ``search()`` would expand to a list of (leg2, leg3) tuples.
            return [(leg2, leg3)]

        with patch.object(SearchFlights, "search", side_effect=_fake_search):
            combos = client._expand_multi_leg(
                outbound,
                _three_segment_filters(),
                top_n=5,
                currency="USD",
                language=None,
                country=None,
            )

        assert len(combos) == 1
        assert len(combos[0]) == 3
        assert all(isinstance(item, FlightResult) for item in combos[0])
        assert combos[0][0].legs[0].arrival_airport == Airport.LAX
        assert combos[0][1].legs[0].arrival_airport == Airport.SEA
        assert combos[0][2].legs[0].arrival_airport == Airport.JFK

    def test_locale_kwargs_forwarded_on_recursive_calls(self):
        """Currency / language / country must propagate to every recursion."""
        client = SearchFlights()
        outbound = [_result(Airport.JFK, Airport.LAX)]
        leg2 = [_result(Airport.LAX, Airport.JFK)]
        captured_kwargs: list[dict] = []

        def _fake_search(filters, **kwargs):
            captured_kwargs.append(dict(kwargs))
            return leg2

        # 2-segment round-trip variant — same recursion path, simpler shape.
        rt_filters = FlightSearchFilters(
            trip_type=TripType.ROUND_TRIP,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=[
                FlightSegment(
                    departure_airport=[[Airport.JFK, 0]],
                    arrival_airport=[[Airport.LAX, 0]],
                    travel_date=_future(60),
                ),
                FlightSegment(
                    departure_airport=[[Airport.LAX, 0]],
                    arrival_airport=[[Airport.JFK, 0]],
                    travel_date=_future(63),
                ),
            ],
        )
        with patch.object(SearchFlights, "search", side_effect=_fake_search):
            client._expand_multi_leg(
                outbound,
                rt_filters,
                top_n=5,
                currency="EUR",
                language="en-GB",
                country="GB",
            )
        assert captured_kwargs, "Expected at least one recursive search() call"
        for call in captured_kwargs:
            assert call["currency"] == "EUR"
            assert call["language"] == "en-GB"
            assert call["country"] == "GB"

    def test_caller_filters_not_mutated(self):
        """``_expand_multi_leg`` must operate on a deepcopy of the input."""
        client = SearchFlights()
        filters = _three_segment_filters()
        outbound = [_result(Airport.JFK, Airport.LAX)]
        leg2 = [_result(Airport.LAX, Airport.SEA)]
        leg3 = [_result(Airport.SEA, Airport.JFK)]
        responses = iter([leg2, leg3])

        def _fake_search(filters_arg, **kwargs):
            return next(responses)

        with patch.object(SearchFlights, "search", side_effect=_fake_search):
            client._expand_multi_leg(
                outbound,
                filters,
                top_n=5,
                currency=None,
                language=None,
                country=None,
            )
        # None of the caller's filters' selected_flight should have been touched.
        assert all(seg.selected_flight is None for seg in filters.flight_segments)

    def test_empty_next_results_skipped(self):
        """When a recursive search returns None, that combo is dropped."""
        client = SearchFlights()
        outbound = [_result(Airport.JFK, Airport.LAX), _result(Airport.JFK, Airport.LAX, hour=14)]

        def _fake_search(filters, **kwargs):
            # First outbound recursion returns results, second returns None.
            if _fake_search.calls == 0:
                _fake_search.calls += 1
                return [_result(Airport.LAX, Airport.JFK)]
            _fake_search.calls += 1
            return None

        _fake_search.calls = 0

        rt_filters = FlightSearchFilters(
            trip_type=TripType.ROUND_TRIP,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=[
                FlightSegment(
                    departure_airport=[[Airport.JFK, 0]],
                    arrival_airport=[[Airport.LAX, 0]],
                    travel_date=_future(60),
                ),
                FlightSegment(
                    departure_airport=[[Airport.LAX, 0]],
                    arrival_airport=[[Airport.JFK, 0]],
                    travel_date=_future(63),
                ),
            ],
        )
        with patch.object(SearchFlights, "search", side_effect=_fake_search):
            combos = client._expand_multi_leg(
                outbound,
                rt_filters,
                top_n=5,
                currency=None,
                language=None,
                country=None,
            )
        # Only the first outbound produced a combo.
        assert len(combos) == 1
