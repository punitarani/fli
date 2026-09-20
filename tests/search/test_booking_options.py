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
        legs=[leg_out],
        price=347,
        currency="USD",
        duration=361,
        stops=0,
    )
    sel_in = FlightResult(
        legs=[leg_in],
        price=347,
        currency="USD",
        duration=339,
        stops=0,
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
        # selected_flight has no booking_token, and the client has no
        # cached session id (no prior search() call).
        with pytest.raises(ValueError, match="Missing booking token"):
            SearchFlights().get_booking_options(flight, filters)


class TestGetBookingOptionsPriceless:
    """Issue #165: ``get_booking_options`` works when ``last.price`` is None.

    Premium-cabin round-trip rows often come back from the shopping
    endpoint without a per-row price. The booking helper must not crash
    on ``int(None * 100)`` — instead it should fall through to the
    per-row ``booking_token`` captured at parse time.
    """

    def test_falls_back_to_per_row_token_when_price_is_none(self):
        """Cached session is present, but last.price=None → use row token."""
        from unittest.mock import patch

        sf = SearchFlights()
        sf._last_session_id = "FAKE_SESSION_ID_PRICELESS"
        filters = _round_trip_filters()
        # Drop both prices to simulate the premium-RT priceless case.
        # Assign the row-level token onto the return leg's
        # selected_flight — this is what ``parse_flight_row`` would have
        # populated from ``row[8]`` on the live response.
        out = filters.flight_segments[0].selected_flight
        ret = filters.flight_segments[1].selected_flight
        out.price = None
        ret.price = None
        ret.booking_token = "PER_ROW_TOKEN_FROM_ROW_8"

        captured: dict[str, str] = {}

        def _fake_post(url, data, **kwargs):  # noqa: ANN001
            captured["data"] = data
            return type(
                "R",
                (),
                {
                    "content": b")]}'\n\n4\n[[]]\n",
                    "text": ")]}'\n\n4\n[[]]\n",
                    "raise_for_status": lambda self: None,
                },
            )()

        with patch.object(sf.client, "post", side_effect=_fake_post):
            sf.get_booking_options((out, ret), filters, currency="USD")

        body = captured["data"]
        assert body.startswith("f.req=")
        decoded_body = urllib.parse.unquote(body[len("f.req=") :])
        outer = json.loads(decoded_body)
        payload = json.loads(outer[1])
        # outer[0] = [None, token]; the token should be the per-row
        # token, NOT a build_booking_token-generated session blob.
        assert payload[0] == [None, "PER_ROW_TOKEN_FROM_ROW_8"]

    def test_raises_clear_error_when_priceless_and_no_per_row_token(self):
        """No price AND no per-row token → user gets the actionable error."""
        sf = SearchFlights()
        sf._last_session_id = "FAKE_SESSION_ID"
        filters = _round_trip_filters()
        out = filters.flight_segments[0].selected_flight
        ret = filters.flight_segments[1].selected_flight
        out.price = None
        ret.price = None
        out.booking_token = None
        ret.booking_token = None
        with pytest.raises(ValueError, match="Missing booking token"):
            sf.get_booking_options((out, ret), filters)


class TestGetBookingOptionsErrorPaths:
    """Booking-flow failure modes: HTTP error, segment mismatch, malformed body."""

    def test_http_error_propagates_naturally(self):
        """HTTP failures bubble up unchanged — no wrapping into generic Exception."""
        from unittest.mock import patch

        sf = SearchFlights()
        sf._last_session_id = "S"
        filters = _round_trip_filters()
        flight = filters.flight_segments[1].selected_flight

        class FakeHTTPError(RuntimeError):
            pass

        def _boom(*args, **kwargs):
            raise FakeHTTPError("network down")

        with patch.object(sf.client, "post", side_effect=_boom):
            with pytest.raises(FakeHTTPError, match="network down"):
                sf.get_booking_options(flight, filters)

    def test_more_results_than_segments_rejected(self):
        """Caller passes a 3-tuple against 2-segment filters → ValueError."""
        filters = _round_trip_filters()  # 2 segments
        # Build a 3-tuple of flight results.
        f = filters.flight_segments[0].selected_flight
        oversized = (f, f, f)
        sf = SearchFlights()
        sf._last_session_id = "S"
        with pytest.raises(ValueError, match="3 segments but filters has 2"):
            sf.get_booking_options(oversized, filters)

    def test_malformed_body_returns_empty_options(self):
        """Garbage body still allows the call to complete with an empty list.

        This is the documented contract — the wire parser yields zero
        chunks for unrecognised bodies, so callers get ``[]`` rather than
        an exception when Google reshapes the response.
        """
        from unittest.mock import patch

        sf = SearchFlights()
        sf._last_session_id = "S"
        filters = _round_trip_filters()
        flight = filters.flight_segments[1].selected_flight

        def _fake_post(url, data, **kwargs):  # noqa: ANN001
            return type(
                "R",
                (),
                {
                    "content": b"garbage-no-prefix",
                    "text": "garbage-no-prefix",
                    "raise_for_status": lambda self: None,
                },
            )()

        with patch.object(sf.client, "post", side_effect=_fake_post):
            opts = sf.get_booking_options(flight, filters, currency="USD")
        assert opts == []


class TestEncodeBookingPayloadValidation:
    """``_encode_booking_payload`` rejects filters that can't produce a main struct."""

    def test_raises_when_filters_format_returns_no_main(self):
        """Patching the class method (Pydantic instances are frozen-ish)."""
        from unittest.mock import patch

        filters = _round_trip_filters()
        with patch.object(type(filters), "format", lambda self: [None]):
            with pytest.raises(ValueError, match="did not return a main struct"):
                SearchFlights._encode_booking_payload("TOKEN", filters)

    def test_raises_when_main_is_not_a_list(self):
        """If format()[1] is a non-list value, the encoder still rejects loudly."""
        from unittest.mock import patch

        filters = _round_trip_filters()
        with patch.object(type(filters), "format", lambda self: [None, "not-a-list"]):
            with pytest.raises(ValueError, match="did not return a main struct"):
                SearchFlights._encode_booking_payload("TOKEN", filters)


class TestGetBookingOptionsSessionCaching:
    def test_search_caches_session_id_on_client(self):
        """`search` populates `_last_session_id` from the response."""
        from unittest.mock import patch

        from fli.search.flights import SearchFlights

        sf = SearchFlights()
        # Fake a response whose ``inner[0][4]`` is a session id string.
        fake_inner = [
            [None, None, None, None, "HCAPTUREDSESSIONID----123ABC"],
            None,
            None,
            [
                [
                    [
                        [None] * 25 + [None],  # detail block (unused)
                    ]
                ],
                None,
                None,
                None,
                None,
            ],
        ]
        # Wrap as the chunked outer the client expects.
        outer_inner_json = json.dumps(fake_inner, separators=(",", ":"))
        outer = [["wrb.fr", None, outer_inner_json]]
        body = ")]}'\n\n" + json.dumps(outer)

        with patch.object(sf.client, "post") as mock_post:
            mock_response = type("R", (), {"text": body, "raise_for_status": lambda s: None})()
            mock_post.return_value = mock_response
            try:
                sf.search(_round_trip_filters())
            except Exception:
                # Parser will reject the fake flights — that's OK; we only
                # care about the session-id capture side effect.
                pass
        assert sf._last_session_id == "HCAPTUREDSESSIONID----123ABC"

    def test_get_booking_options_uses_cached_session_id(self):
        """Cached session id flows into the protobuf token builder.

        We mock the HTTP layer and inspect the request body — the token
        embedded at outer[0][1] should decode to a protobuf whose
        ``field 1`` is the cached session id.
        """
        from unittest.mock import patch

        from fli.search._proto import decode_booking_token
        from fli.search.flights import SearchFlights

        sf = SearchFlights()
        sf._last_session_id = "FAKE_SESSION_ID_12345"

        filters = _round_trip_filters()
        flight = filters.flight_segments[1].selected_flight  # return leg

        captured_body = {}

        def _fake_post(url, data, **kwargs):  # noqa: ANN001
            captured_body["data"] = data
            return type(
                "R",
                (),
                {
                    "content": b")]}'\n\n4\n[[]]\n",
                    "text": ")]}'\n\n4\n[[]]\n",
                    "raise_for_status": lambda self: None,
                },
            )()

        with patch.object(sf.client, "post", side_effect=_fake_post):
            sf.get_booking_options(flight, filters, currency="USD")

        # Extract token from the URL-encoded body
        body = captured_body["data"]
        assert body.startswith("f.req=")
        decoded_body = urllib.parse.unquote(body[len("f.req=") :])
        outer = json.loads(decoded_body)
        payload = json.loads(outer[1])
        token = payload[0][1]
        decoded = decode_booking_token(token)
        assert decoded["field_1"] == "FAKE_SESSION_ID_12345"


def _row(price=347, fare_label="Basic Economy"):
    """Build a booking row with positional fields matching the live capture."""
    row = [None] * 22
    row[0] = 0
    row[1] = [["AA", "American", None, True]]
    row[2] = None
    row[3] = [["AA", "171"], ["AA", "28"]]
    row[4] = False
    row[5] = ["www.aa.com/foo", None, ["https://www.google.com/travel/clk/f?u=abc"]]
    row[7] = [[None, price], None]  # price block; currency token omitted
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
