"""Unit tests for the multi-segment recursion in ``SearchFlights._expand_multi_leg``.

The recursion mutates a deep copy of the caller's filters as it walks
segment-by-segment, so it has been a quiet source of subtle bugs around
selected-flight state and locale kwarg propagation. These mock-based
tests pin the contract without hitting Google.

Mocking note: as of the parallelisation refactor, ``_expand_multi_leg``
calls ``self._fetch_flights`` directly (with ``capture_session=False``)
rather than ``self.search`` — that change keeps the parallel workers
from racing on ``_last_session_id``. The tests below mock
``_fetch_flights`` accordingly. Each mocked call returns a flat list of
next-leg ``FlightResult`` instances; ``_expand_multi_leg`` handles its
own recursion for multi-city.
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

        The new recursion path: ``_expand_multi_leg`` calls
        ``self._fetch_flights`` for the next segment and, while more
        segments remain unselected, recurses into ``_expand_multi_leg``
        directly. Mock ``_fetch_flights`` to return the next-leg
        candidates as a flat list at each level.
        """
        client = SearchFlights()
        outbound = [_result(Airport.JFK, Airport.LAX)]
        leg2 = _result(Airport.LAX, Airport.SEA)
        leg3 = _result(Airport.SEA, Airport.JFK)
        responses = iter([[leg2], [leg3]])

        def _fake_fetch(filters, **kwargs):
            return next(responses)

        with patch.object(SearchFlights, "_fetch_flights", side_effect=_fake_fetch):
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

        def _fake_fetch(filters, **kwargs):
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
        with patch.object(SearchFlights, "_fetch_flights", side_effect=_fake_fetch):
            client._expand_multi_leg(
                outbound,
                rt_filters,
                top_n=5,
                currency="EUR",
                language="en-GB",
                country="GB",
            )
        assert captured_kwargs, "Expected at least one expansion fetch() call"
        for call in captured_kwargs:
            assert call["currency"] == "EUR"
            assert call["language"] == "en-GB"
            assert call["country"] == "GB"
            # Expansion calls must never write to the shared session cache.
            assert call["capture_session"] is False

    def test_caller_filters_not_mutated(self):
        """``_expand_multi_leg`` must operate on a deepcopy of the input."""
        client = SearchFlights()
        filters = _three_segment_filters()
        outbound = [_result(Airport.JFK, Airport.LAX)]
        leg2 = [_result(Airport.LAX, Airport.SEA)]
        leg3 = [_result(Airport.SEA, Airport.JFK)]
        responses = iter([leg2, leg3])

        def _fake_fetch(filters_arg, **kwargs):
            return next(responses)

        with patch.object(SearchFlights, "_fetch_flights", side_effect=_fake_fetch):
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
        """When a recursive fetch returns None, that combo is dropped."""
        client = SearchFlights()
        outbound = [_result(Airport.JFK, Airport.LAX), _result(Airport.JFK, Airport.LAX, hour=14)]

        def _fake_fetch(filters, **kwargs):
            # First outbound expansion returns results, second returns None.
            if _fake_fetch.calls == 0:
                _fake_fetch.calls += 1
                return [_result(Airport.LAX, Airport.JFK)]
            _fake_fetch.calls += 1
            return None

        _fake_fetch.calls = 0

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
        with patch.object(SearchFlights, "_fetch_flights", side_effect=_fake_fetch):
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


def _priceless_result(dep: Airport, arr: Airport, hour: int = 9) -> FlightResult:
    """Mirrors ``_result`` but with ``price=None`` (issue #165 shape)."""
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
        price=None,
        currency="USD",
        duration=180,
        stops=0,
        booking_token=f"TOKEN_{dep.name}_{arr.name}_{hour}",
    )


class TestExpandMultiLegPriceless:
    """Issue #165: expansion must not crash when prices are ``None``.

    The decoder change in ``_parse_price_info`` surfaces premium-cabin
    round-trip outbound rows with ``price=None``. Those rows then drive
    ``_expand_multi_leg``; the second-leg fetch may also return
    ``price=None`` rows. The recursion must propagate those through
    without touching the (None) prices for any arithmetic.
    """

    def test_all_priceless_rt_produces_combos(self):
        """Outbound and return both priceless → tuples still assembled."""
        client = SearchFlights()
        outbound = [_priceless_result(Airport.JFK, Airport.LAX)]

        def _fake_fetch(filters, **kwargs):
            return [_priceless_result(Airport.LAX, Airport.JFK, hour=16)]

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
        with patch.object(SearchFlights, "_fetch_flights", side_effect=_fake_fetch):
            combos = client._expand_multi_leg(
                outbound,
                rt_filters,
                top_n=5,
                currency="USD",
                language=None,
                country=None,
            )
        assert len(combos) == 1
        out_res, ret_res = combos[0]
        assert out_res.price is None
        assert ret_res.price is None
        assert out_res.booking_token is not None
        assert ret_res.booking_token is not None

    def test_mixed_priced_and_priceless(self):
        """Priced outbound + priceless return — combo assembled correctly."""
        client = SearchFlights()
        outbound = [_result(Airport.JFK, Airport.LAX)]  # priced

        def _fake_fetch(filters, **kwargs):
            return [_priceless_result(Airport.LAX, Airport.JFK, hour=16)]

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
        with patch.object(SearchFlights, "_fetch_flights", side_effect=_fake_fetch):
            combos = client._expand_multi_leg(
                outbound,
                rt_filters,
                top_n=5,
                currency="USD",
                language=None,
                country=None,
            )
        assert len(combos) == 1
        out_res, ret_res = combos[0]
        assert out_res.price == 300.0
        assert ret_res.price is None

    def test_multi_city_priceless_three_segments(self):
        """3-segment multi-city with all priceless rows still tuples cleanly."""
        client = SearchFlights()
        outbound = [_priceless_result(Airport.JFK, Airport.LAX)]
        leg2 = _priceless_result(Airport.LAX, Airport.SEA, hour=14)
        leg3 = _priceless_result(Airport.SEA, Airport.JFK, hour=18)
        responses = iter([[leg2], [leg3]])

        def _fake_fetch(filters, **kwargs):
            return next(responses)

        with patch.object(SearchFlights, "_fetch_flights", side_effect=_fake_fetch):
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
        assert all(item.price is None for item in combos[0])
