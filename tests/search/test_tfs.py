"""Tests for the search-page transport (``fli.search._tfs``).

The ``tfs`` fixtures below were issued by Google itself for the same queries,
so a byte mismatch means the encoder has drifted from what Google accepts.
Everything here is offline — no live API calls.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from fli.models import (
    Airline,
    Airport,
    FlightLeg,
    FlightResult,
    FlightSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    PriceLimit,
    SeatType,
    TimeRestrictions,
    TripType,
)
from fli.search._tfs import (
    apply_client_side_filters,
    build_tfs,
    extract_payload,
    page_url,
    unsupported_filters,
)

# Captured from Google's own search-page URLs (2026-08-26) for
# JFK -> LAX on 2026-09-15, returning 2026-09-19.
TFS_ONE_WAY = "CBwQAhoeEgoyMDI2LTA5LTE1agcIARIDSkZLcgcIARIDTEFYQAFIAXABmAEC"
TFS_NON_STOP = "CBwQAhogEgoyMDI2LTA5LTE1KABqBwgBEgNKRktyBwgBEgNMQVhAAUgBcAGYAQI"
TFS_ROUND_TRIP = (
    "CBwQAhoeEgoyMDI2LTA5LTE1agcIARIDSkZLcgcIARIDTEFYGh4SCjIwMjYtMDktMTlqBwgBEgNMQVhy"
    "BwgBEgNKRktAAUgBcAGYAQE"
)

OUTBOUND_DATE = "2026-09-15"
RETURN_DATE = "2026-09-19"


def _filters(segments, **kwargs) -> FlightSearchFilters:
    """Build filters over ``(origin, destination, date)`` triples."""
    return FlightSearchFilters(
        trip_type=kwargs.get("trip_type", TripType.ONE_WAY),
        passenger_info=kwargs.get("passenger_info", PassengerInfo(adults=1)),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport[origin], 0]],
                arrival_airport=[[Airport[destination], 0]],
                travel_date=date,
                time_restrictions=kwargs.get("time_restrictions"),
            )
            for origin, destination, date in segments
        ],
        stops=kwargs.get("stops", MaxStops.ANY),
        seat_type=kwargs.get("seat_type", SeatType.ECONOMY),
        airlines=kwargs.get("airlines"),
        airlines_exclude=kwargs.get("airlines_exclude"),
        max_duration=kwargs.get("max_duration"),
        price_limit=kwargs.get("price_limit"),
    )


def _decode(tfs: str) -> bytes:
    """Decode a tfs value, restoring the padding Google's URLs strip."""
    import base64

    return base64.urlsafe_b64decode(tfs + "=" * (-len(tfs) % 4))


def _flight(airline: Airline = Airline.AA, price: float = 300, duration: int = 180, hour: int = 9):
    return FlightResult(
        legs=[
            FlightLeg(
                airline=airline,
                flight_number="171",
                departure_airport=Airport.JFK,
                arrival_airport=Airport.LAX,
                departure_datetime=datetime(2026, 9, 15, hour, 0),
                arrival_datetime=datetime(2026, 9, 15, hour + 3, 0),
                duration=duration,
            )
        ],
        price=price,
        currency="USD",
        duration=duration,
        stops=0,
    )


class TestBuildTfs:
    def test_one_way_matches_google(self):
        assert build_tfs(_filters([("JFK", "LAX", OUTBOUND_DATE)])) == TFS_ONE_WAY

    def test_non_stop_matches_google(self):
        built = build_tfs(_filters([("JFK", "LAX", OUTBOUND_DATE)], stops=MaxStops.NON_STOP))
        assert built == TFS_NON_STOP

    def test_round_trip_matches_google(self):
        built = build_tfs(
            _filters(
                [("JFK", "LAX", OUTBOUND_DATE), ("LAX", "JFK", RETURN_DATE)],
                trip_type=TripType.ROUND_TRIP,
            )
        )
        assert built == TFS_ROUND_TRIP

    def test_any_stops_omits_the_ceiling(self):
        """MaxStops.ANY must leave field 5 out — writing 0 means non-stop."""
        assert build_tfs(_filters([("JFK", "LAX", OUTBOUND_DATE)])) != TFS_NON_STOP

    @pytest.mark.parametrize(
        ("stops", "expected_ceiling"),
        [
            (MaxStops.NON_STOP, 0),
            (MaxStops.ONE_STOP_OR_FEWER, 1),
            (MaxStops.TWO_OR_FEWER_STOPS, 2),
        ],
    )
    def test_stop_ceiling_is_zero_based(self, stops, expected_ceiling):
        raw = _decode(build_tfs(_filters([("JFK", "LAX", OUTBOUND_DATE)], stops=stops)))
        # Field 5, varint: tag 0x28 followed by the ceiling.
        assert bytes([0x28, expected_ceiling]) in raw

    def test_travel_dates_override_segment_dates(self):
        spec = _filters([("JFK", "LAX", OUTBOUND_DATE)])
        assert build_tfs(spec, travel_dates=["2026-10-01"]) != build_tfs(spec)

    def test_selected_flight_uses_field_four(self):
        """Legs pin the search only in field 4.

        Google ignores an unknown field number and silently re-serves the
        outbound board, so a wrong slot here makes round-trip expansion pair
        outbound flights with other outbound flights without erroring.
        """
        spec = _filters(
            [("JFK", "LAX", OUTBOUND_DATE), ("LAX", "JFK", RETURN_DATE)],
            trip_type=TripType.ROUND_TRIP,
        )
        spec.flight_segments[0].selected_flight = _flight()
        raw = _decode(build_tfs(spec))
        # Field 4, length-delimited: tag 0x22, then a body naming the flight.
        assert b"\x22" in raw
        assert b"AA" in raw and b"171" in raw
        index = raw.index(b"171")
        assert raw[index - 2] == 0x32, "flight number should sit in leg field 6"

    def test_passenger_mix_is_repeated_per_traveller(self):
        spec = _filters(
            [("JFK", "LAX", OUTBOUND_DATE)],
            passenger_info=PassengerInfo(adults=2, children=1),
        )
        raw = _decode(build_tfs(spec))
        assert raw.count(b"\x40\x01") == 2, "two adults means two field-8 entries"
        assert b"\x40\x02" in raw, "a child means a field-8 entry with code 2"

    def test_cabin_class_is_encoded(self):
        economy = build_tfs(_filters([("JFK", "LAX", OUTBOUND_DATE)]))
        business = build_tfs(_filters([("JFK", "LAX", OUTBOUND_DATE)], seat_type=SeatType.BUSINESS))
        assert economy != business


class TestPageUrl:
    def test_includes_locale_and_currency(self):
        url = page_url("TFS", currency="EUR", language="de", country="DE")
        assert "tfs=TFS" in url and "curr=EUR" in url and "hl=de" in url and "gl=DE" in url

    def test_defaults_when_locale_omitted(self):
        url = page_url("TFS")
        assert "hl=en" in url and "gl=US" in url and "curr=" not in url


class TestExtractPayload:
    def test_reads_the_ds1_blob(self):
        html = (
            "<script>AF_initDataCallback({key: 'ds:0', hash: '1', "
            'data:["other"], sideChannel: {}});</script>'
            "<script>AF_initDataCallback({key: 'ds:1', hash: '2', "
            'data:[1,2,[["row"]]], sideChannel: {}});</script>'
        )
        assert extract_payload(html) == [1, 2, [["row"]]]

    def test_returns_none_without_ds1(self):
        html = (
            "<script>AF_initDataCallback({key: 'ds:4', hash: '2', "
            "data:[], sideChannel: {}});</script>"
        )
        assert extract_payload(html) is None

    def test_returns_none_on_unparseable_blob(self):
        html = (
            "<script>AF_initDataCallback({key: 'ds:1', hash: '2', "
            "data:[oops, sideChannel: {}});</script>"
        )
        assert extract_payload(html) is None


class TestClientSideFilters:
    def test_airline_include_keeps_only_matching_carriers(self):
        flights = [_flight(Airline.AA), _flight(Airline.DL)]
        spec = _filters([("JFK", "LAX", OUTBOUND_DATE)], airlines=[Airline.AA])
        kept = apply_client_side_filters(flights, spec)
        assert [leg.airline for f in kept for leg in f.legs] == [Airline.AA]

    def test_airline_exclude_drops_matching_carriers(self):
        flights = [_flight(Airline.AA), _flight(Airline.DL)]
        spec = _filters([("JFK", "LAX", OUTBOUND_DATE)], airlines_exclude=[Airline.AA])
        kept = apply_client_side_filters(flights, spec)
        assert [leg.airline for f in kept for leg in f.legs] == [Airline.DL]

    def test_price_cap_drops_expensive_flights(self):
        flights = [_flight(price=100), _flight(price=900)]
        spec = _filters([("JFK", "LAX", OUTBOUND_DATE)], price_limit=PriceLimit(max_price=500))
        assert [f.price for f in apply_client_side_filters(flights, spec)] == [100]

    def test_max_duration_drops_long_flights(self):
        flights = [_flight(duration=120), _flight(duration=600)]
        spec = _filters([("JFK", "LAX", OUTBOUND_DATE)], max_duration=300)
        assert [f.duration for f in apply_client_side_filters(flights, spec)] == [120]

    def test_departure_window_drops_flights_outside_it(self):
        flights = [_flight(hour=6), _flight(hour=20)]
        spec = _filters(
            [("JFK", "LAX", OUTBOUND_DATE)],
            time_restrictions=TimeRestrictions(earliest_departure=8, latest_departure=22),
        )
        kept = apply_client_side_filters(flights, spec)
        assert [f.legs[0].departure_datetime.hour for f in kept] == [20]

    def test_no_filters_keeps_everything(self):
        flights = [_flight(Airline.AA), _flight(Airline.DL)]
        spec = _filters([("JFK", "LAX", OUTBOUND_DATE)])
        assert apply_client_side_filters(flights, spec) == flights


class TestUnsupportedFilters:
    def test_reports_nothing_for_a_plain_search(self):
        assert unsupported_filters(_filters([("JFK", "LAX", OUTBOUND_DATE)])) == []

    def test_names_filters_the_page_cannot_honour(self):
        spec = _filters([("JFK", "LAX", OUTBOUND_DATE)])
        spec.exclude_basic_economy = True
        assert "exclude_basic_economy" in unsupported_filters(spec)
