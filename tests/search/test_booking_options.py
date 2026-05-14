"""Tests for SearchFlights.get_booking_options encoding + booking-row parsing."""

import json
import urllib.parse
from datetime import datetime

import pytest

from fli.models import (
    Airline,
    Airport,
    BookingOption,
    FlightLeg,
    FlightResult,
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
    TripType,
)
from fli.search.flights import SearchFlights, _try_parse_booking_row


def _round_trip_filters():
    """Build a round-trip filter with selected_flight set on both segments."""
    leg_out = FlightLeg(
        airline=Airline.AA,
        flight_number="171",
        departure_airport=Airport.JFK,
        arrival_airport=Airport.LAX,
        departure_datetime=datetime(2026, 7, 15, 6, 0),
        arrival_datetime=datetime(2026, 7, 15, 9, 1),
        duration=361,
    )
    leg_in = FlightLeg(
        airline=Airline.AA,
        flight_number="28",
        departure_airport=Airport.LAX,
        arrival_airport=Airport.JFK,
        departure_datetime=datetime(2026, 7, 19, 15, 15),
        arrival_datetime=datetime(2026, 7, 19, 23, 54),
        duration=339,
    )
    sel_out = FlightResult(
        legs=[leg_out], price=347, currency="USD", duration=361, stops=0,
    )
    sel_in = FlightResult(
        legs=[leg_in], price=347, currency="USD", duration=339, stops=0,
    )
    seg_out = FlightSegment(
        departure_airport=[[Airport.JFK, 0]],
        arrival_airport=[[Airport.LAX, 0]],
        travel_date="2026-07-15",
        selected_flight=sel_out,
    )
    seg_in = FlightSegment(
        departure_airport=[[Airport.LAX, 0]],
        arrival_airport=[[Airport.JFK, 0]],
        travel_date="2026-07-19",
        selected_flight=sel_in,
    )
    return FlightSearchFilters(
        trip_type=TripType.ROUND_TRIP,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[seg_out, seg_in],
    )


class TestEncodeBookingPayload:
    def test_payload_has_token_and_main_struct(self):
        filters = _round_trip_filters()
        encoded = SearchFlights._encode_booking_payload("TEST-TOKEN", filters)
        # Decode the URL-encoded outer JSON.
        raw = urllib.parse.unquote(encoded)
        outer = json.loads(raw)
        # outer[0] is null, outer[1] is the inner-stringified payload.
        assert outer[0] is None
        payload = json.loads(outer[1])

        # outer[0]: [null, token]
        assert payload[0] == [None, "TEST-TOKEN"]
        # outer[1]: the same main filter struct that FlightSearchFilters.format() emits at [1]
        assert isinstance(payload[1], list)
        assert payload[1][2] == 1  # trip_type ROUND_TRIP
        assert payload[1][6] == [1, 0, 0, 0]  # passengers
        # outer[2] null and outer[3] 0 are required trailers.
        assert payload[2] is None
        assert payload[3] == 0

    def test_segments_include_selected_flight(self):
        filters = _round_trip_filters()
        encoded = SearchFlights._encode_booking_payload("T", filters)
        payload = json.loads(json.loads(urllib.parse.unquote(encoded))[1])
        segments = payload[1][13]
        assert len(segments) == 2
        # selected_flight legs sit at segment[8]; verify each leg's basic fields.
        out_sel = segments[0][8]
        assert out_sel == [["JFK", "2026-07-15", "LAX", None, "AA", "171"]]
        in_sel = segments[1][8]
        assert in_sel == [["LAX", "2026-07-19", "JFK", None, "AA", "28"]]


class TestGetBookingOptionsTokenGuard:
    def test_raises_when_no_token(self):
        filters = _round_trip_filters()
        flight = filters.flight_segments[0].selected_flight
        # selected_flight has no booking_token by default.
        with pytest.raises(ValueError, match="booking_token is required"):
            SearchFlights().get_booking_options(flight, filters)


def _row(price=347, fare_label="Basic Economy"):
    """Build a booking row with positional fields matching the live capture."""
    row = [None] * 22
    row[0] = 0
    row[1] = [["AA", "American", None, True]]
    row[2] = None
    row[3] = [["AA", "171"], ["AA", "28"]]
    row[4] = False
    row[5] = ["www.aa.com/foo", None, ["https://www.google.com/travel/clk/f?u=abc"]]
    row[7] = [[None, price], None]   # price block; currency token omitted
    row[14] = [[[None, ["AA", fare_label.upper().replace(" ", " ")], 1]]]
    row[21] = [["AA", fare_label.upper()], [], None, fare_label]
    return row


class TestParseBookingRow:
    def test_basic_row(self):
        opt = _try_parse_booking_row(_row())
        assert isinstance(opt, BookingOption)
        assert opt.vendor_code == "AA"
        assert opt.vendor_name == "American"
        assert opt.is_airline_direct is True
        assert opt.flights == [("AA", "171"), ("AA", "28")]
        assert opt.booking_url == "www.aa.com/foo"
        assert opt.google_click_url == "https://www.google.com/travel/clk/f?u=abc"

    def test_extracts_price_from_row7(self):
        opt = _try_parse_booking_row(_row(price=457))
        assert opt is not None
        assert opt.price == 457.0

    def test_extracts_fare_name_from_row21(self):
        opt = _try_parse_booking_row(_row(fare_label="Main Cabin"))
        assert opt is not None
        assert opt.fare_name == "Main Cabin"

    def test_rejects_non_booking_list(self):
        # Random outer list — should not falsely parse.
        assert _try_parse_booking_row([1, 2, 3]) is None

    def test_rejects_short_list(self):
        assert _try_parse_booking_row([0, [["AA", "American"]]]) is None

    def test_rejects_when_first_not_int(self):
        row = _row()
        row[0] = "not-an-int"
        assert _try_parse_booking_row(row) is None


class TestParseBookingChunk:
    def test_walks_nested_lists(self):
        # Build full-shape rows so the positional parser matches them.
        row_aa = _row(price=347, fare_label="Basic Economy")
        row_ex = _row(price=400, fare_label="Refundable")
        row_ex[1] = [["EX", "Expedia", None, False]]
        chunk = [None, [row_aa, row_ex]]
        opts = SearchFlights._parse_booking_chunk(chunk)
        assert len(opts) == 2
        assert {o.vendor_code for o in opts} == {"AA", "EX"}
        # Order from the parser walk preserves chunk order.
        by_vendor = {o.vendor_code: o for o in opts}
        assert by_vendor["AA"].is_airline_direct is True
        assert by_vendor["EX"].is_airline_direct is False
