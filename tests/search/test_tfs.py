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
    Alliance,
    FlightLeg,
    FlightResult,
    FlightSearchFilters,
    FlightSegment,
    LayoverRestrictions,
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
from fli.search.exceptions import SearchUnsupportedError

# Captured from Google's own search-page URLs (2026-08-26) for
# JFK -> LAX on 2026-09-15, returning 2026-09-19.
TFS_ONE_WAY = "CBwQAhoeEgoyMDI2LTA5LTE1agcIARIDSkZLcgcIARIDTEFYQAFIAXABmAEC"
TFS_NON_STOP = "CBwQAhogEgoyMDI2LTA5LTE1KABqBwgBEgNKRktyBwgBEgNMQVhAAUgBcAGYAQI"
TFS_ROUND_TRIP = (
    "CBwQAhoeEgoyMDI2LTA5LTE1agcIARIDSkZLcgcIARIDTEFYGh4SCjIwMjYtMDktMTlqBwgBEgNMQVhy"
    "BwgBEgNKRktAAUgBcAGYAQE"
)

TFS_MULTI_AIRPORT = (
    "CBwQAho5EgoyMDI2LTEwLTE1agcIARIDQk9NagcIARIDREVMagcIARIDQU1EcgcIARIDT1JEcgcIARIDRFRX"
    "QAFIAXABmAEC"
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


def _flight(
    airline: Airline = Airline.AA,
    price: float = 300,
    duration: int = 180,
    hour: int = 9,
) -> FlightResult:
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
    def test_stop_ceiling_is_zero_based(self, stops: MaxStops, expected_ceiling: int) -> None:
        raw = _decode(build_tfs(_filters([("JFK", "LAX", OUTBOUND_DATE)], stops=stops)))
        # Field 5, varint: tag 0x28 followed by the ceiling.
        assert bytes([0x28, expected_ceiling]) in raw

    def test_every_airport_reaches_the_request(self):
        """All origins and destinations must survive encoding.

        Serializing only entry zero still produces a valid, successful search
        for the first pair, so a truncated request looks like a working one and
        the missing city pairs never surface as an error.
        """
        spec = FlightSearchFilters(
            trip_type=TripType.ONE_WAY,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=[
                FlightSegment(
                    departure_airport=[[Airport.BOM, 0], [Airport.DEL, 0], [Airport.AMD, 0]],
                    arrival_airport=[[Airport.ORD, 0], [Airport.DTW, 0]],
                    travel_date=OUTBOUND_DATE,
                )
            ],
            stops=MaxStops.ANY,
            seat_type=SeatType.ECONOMY,
        )
        raw = _decode(build_tfs(spec))
        for code in (b"BOM", b"DEL", b"AMD", b"ORD", b"DTW"):
            assert code in raw, f"{code.decode()} was dropped from the request"

    def test_multi_airport_matches_google(self):
        """Byte-for-byte against a tfs Google issued for the same query."""
        spec = FlightSearchFilters(
            trip_type=TripType.ONE_WAY,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=[
                FlightSegment(
                    departure_airport=[[Airport.BOM, 0], [Airport.DEL, 0], [Airport.AMD, 0]],
                    arrival_airport=[[Airport.ORD, 0], [Airport.DTW, 0]],
                    travel_date="2026-10-15",
                )
            ],
            stops=MaxStops.ANY,
            seat_type=SeatType.ECONOMY,
        )
        assert build_tfs(spec) == TFS_MULTI_AIRPORT

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

    def test_trip_type_field_19(self):
        """Field 19 must say one-way (2) or round trip (1), never anything else."""
        one_way = _decode(build_tfs(_filters([("JFK", "LAX", OUTBOUND_DATE)])))
        round_trip = _decode(
            build_tfs(
                _filters(
                    [("JFK", "LAX", OUTBOUND_DATE), ("LAX", "JFK", RETURN_DATE)],
                    trip_type=TripType.ROUND_TRIP,
                )
            )
        )
        assert one_way.endswith(b"\x98\x01\x02")
        assert round_trip.endswith(b"\x98\x01\x01")

    def test_multi_city_is_refused(self):
        """Encoding it as one-way would return the first leg's board as the trip."""
        spec = _filters(
            [
                ("MNL", "DXB", "2026-10-12"),
                ("DXB", "FCO", "2026-10-16"),
                ("FCO", "MNL", "2026-10-25"),
            ],
            trip_type=TripType.MULTI_CITY,
        )
        with pytest.raises(SearchUnsupportedError, match="Multi-city"):
            build_tfs(spec)


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

    def test_window_follows_the_segment_being_chosen(self):
        """Return-leg candidates honour the return window, not the outbound one.

        During round-trip expansion the outbound is already pinned and the
        rows coming back are return options. Filtering them against segment
        zero's window drops valid returns and keeps invalid ones without ever
        raising.
        """
        spec = FlightSearchFilters(
            trip_type=TripType.ROUND_TRIP,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=[
                FlightSegment(
                    departure_airport=[[Airport.JFK, 0]],
                    arrival_airport=[[Airport.LAX, 0]],
                    travel_date=OUTBOUND_DATE,
                    time_restrictions=TimeRestrictions(earliest_departure=5, latest_departure=9),
                    selected_flight=_flight(hour=6),
                ),
                FlightSegment(
                    departure_airport=[[Airport.LAX, 0]],
                    arrival_airport=[[Airport.JFK, 0]],
                    travel_date=RETURN_DATE,
                    time_restrictions=TimeRestrictions(earliest_departure=18, latest_departure=23),
                ),
            ],
            stops=MaxStops.ANY,
            seat_type=SeatType.ECONOMY,
        )
        returns = [_flight(hour=6), _flight(hour=20)]
        kept = apply_client_side_filters(returns, spec)
        hours = [f.legs[0].departure_datetime.hour for f in kept]
        assert hours == [20], f"expected the 20:00 return to survive, got {hours}"

    def test_window_applies_to_outbound_before_anything_is_pinned(self):
        """With nothing selected yet, segment zero's window is the right one."""
        spec = FlightSearchFilters(
            trip_type=TripType.ROUND_TRIP,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=[
                FlightSegment(
                    departure_airport=[[Airport.JFK, 0]],
                    arrival_airport=[[Airport.LAX, 0]],
                    travel_date=OUTBOUND_DATE,
                    time_restrictions=TimeRestrictions(earliest_departure=5, latest_departure=9),
                ),
                FlightSegment(
                    departure_airport=[[Airport.LAX, 0]],
                    arrival_airport=[[Airport.JFK, 0]],
                    travel_date=RETURN_DATE,
                    time_restrictions=TimeRestrictions(earliest_departure=18, latest_departure=23),
                ),
            ],
            stops=MaxStops.ANY,
            seat_type=SeatType.ECONOMY,
        )
        kept = apply_client_side_filters([_flight(hour=6), _flight(hour=20)], spec)
        assert [f.legs[0].departure_datetime.hour for f in kept] == [6]

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


class TestAllianceAndLayoverEncoding:
    """Alliances and layover bounds ride in the request, not a post-filter.

    Google reads both out of the segment, so a search that sets them comes
    back already filtered — and back-filled, which a client-side filter
    can't do.
    """

    def test_alliances_ride_in_the_carrier_include_list(self):
        spec = _filters([("JFK", "LAX", OUTBOUND_DATE)])
        spec.alliances = [Alliance.STAR_ALLIANCE]
        raw = _decode(build_tfs(spec))
        # Field 6, length-delimited: tag 0x32, length 13, then the name.
        assert b"\x32\x0dSTAR_ALLIANCE" in raw

    def test_alliances_exclude_uses_the_exclude_list(self):
        spec = _filters([("JFK", "LAX", OUTBOUND_DATE)])
        spec.alliances_exclude = [Alliance.ONEWORLD]
        raw = _decode(build_tfs(spec))
        # Field 7, length-delimited: tag 0x3a, length 8, then the name.
        assert b"\x3a\x08ONEWORLD" in raw

    def test_layover_restrictions_are_encoded(self):
        spec = _filters([("JFK", "LAX", OUTBOUND_DATE)])
        spec.layover_restrictions = LayoverRestrictions(
            airports=[Airport.ORD], min_duration=120, max_duration=300
        )
        raw = _decode(build_tfs(spec))
        assert b"\x7a\x03ORD" in raw, "layover airport should sit in field 15"
        assert b"\x88\x01\x78" in raw, "min layover should sit in field 17"
        assert b"\x90\x01\xac\x02" in raw, "max layover should sit in field 18"

    def test_unset_filters_leave_the_bytes_alone(self):
        """A plain search must still match the tfs Google issues for it."""
        assert build_tfs(_filters([("JFK", "LAX", OUTBOUND_DATE)])) == TFS_ONE_WAY

    def test_alliances_and_layovers_are_no_longer_unsupported(self):
        spec = _filters([("JFK", "LAX", OUTBOUND_DATE)])
        spec.alliances = [Alliance.SKYTEAM]
        spec.layover_restrictions = LayoverRestrictions(min_duration=90)
        assert unsupported_filters(spec) == []
