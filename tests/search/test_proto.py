"""Tests for the GetBookingResults protobuf token builder.

The builder reproduces a byte-perfect copy of the captured token from a
live booking-page URL. The captured fixture is the authoritative
reference — any change to the builder must keep this byte-equal.
"""

from __future__ import annotations

import base64

from fli.search._proto import build_booking_token, decode_booking_token

# Captured live from a real booking page (2026-05-14):
#   JFK -> LAX outbound AA171, LAX -> JFK return AA28, RT $346.80 USD
CAPTURED_TOKEN = (
    "CjRIUHJ1SE9pTmdoeUVBQ0U1S2dCRy0tLS0tLS0tLS1wZm4zOUFBQUFBR29GZ2tjSG5SRHdBEgZBQTI4Iz"
    "EaCwj4jgIQAhoDVVNEOBxw+I4C"
)
CAPTURED_SESSION = "HPruHOiNghyEACE5KgBG----------pfn39AAAAAGoFgkcHnRDwA"


class TestBuildBookingToken:
    def test_byte_perfect_reproduction(self):
        built = build_booking_token(
            session_id=CAPTURED_SESSION,
            airline_code="AA",
            flight_number="28",
            leg_index=1,
            price_cents=34680,
            currency="USD",
        )
        # Bytes must match the captured token exactly.
        b_built = base64.b64decode(built + "=" * ((4 - len(built) % 4) % 4))
        capt_padding = "=" * ((4 - len(CAPTURED_TOKEN) % 4) % 4)
        b_capt = base64.urlsafe_b64decode(CAPTURED_TOKEN + capt_padding)
        assert b_built == b_capt, (
            f"\nbuilt: {b_built.hex()}\ncapt:  {b_capt.hex()}"
        )

    def test_round_trip_decode(self):
        token = build_booking_token(
            session_id="ABC123",
            airline_code="DL",
            flight_number="100",
            leg_index=1,
            price_cents=12345,
            currency="EUR",
        )
        decoded = decode_booking_token(token)
        assert decoded["field_1"] == "ABC123"
        assert decoded["field_2"] == "DL100#1"
        assert decoded["field_3"] == {"field_1": 12345, "field_2": 2, "field_3": "EUR"}
        assert decoded["field_7"] == 28
        assert decoded["field_14"] == 12345

    def test_different_currencies(self):
        for code in ("USD", "EUR", "GBP", "JPY", "INR"):
            token = build_booking_token("S", "DL", "1", 1, 100, code)
            decoded = decode_booking_token(token)
            assert decoded["field_3"]["field_3"] == code

    def test_leg_index_in_field_2(self):
        for idx in (0, 1, 2, 5, 10):
            token = build_booking_token("S", "AA", "100", idx, 100, "USD")
            decoded = decode_booking_token(token)
            assert decoded["field_2"] == f"AA100#{idx}"

    def test_price_varint_encoding(self):
        # 34680 spans 3 varint bytes: 0xf8 0x8e 0x02. Confirm round-trip.
        token = build_booking_token("S", "AA", "1", 1, 34680, "USD")
        decoded = decode_booking_token(token)
        assert decoded["field_3"]["field_1"] == 34680
        assert decoded["field_14"] == 34680

    def test_large_price(self):
        # Some routes exceed 6 digits in cents (transatlantic business).
        token = build_booking_token("S", "AA", "1", 1, 1_234_567, "USD")
        decoded = decode_booking_token(token)
        assert decoded["field_3"]["field_1"] == 1_234_567

    def test_decode_captured_token(self):
        decoded = decode_booking_token(CAPTURED_TOKEN)
        assert decoded["field_1"] == CAPTURED_SESSION
        assert decoded["field_2"] == "AA28#1"
        assert decoded["field_3"] == {"field_1": 34680, "field_2": 2, "field_3": "USD"}
        assert decoded["field_7"] == 28
        assert decoded["field_14"] == 34680


class TestVarintEncoding:
    """Spot-check the protobuf primitives used by the builder."""

    def test_small_varint_single_byte(self):
        # 0-127 fit in one byte
        token = build_booking_token("", "A", "1", 0, 0, "X")
        decoded = decode_booking_token(token)
        assert decoded["field_3"]["field_1"] == 0
        assert decoded["field_2"] == "A1#0"

    def test_zero_padding_handling(self):
        # Tokens whose base64 needs padding (length mod 4 != 0) round-trip.
        token = build_booking_token("ABC", "AA", "1", 1, 100, "USD")
        decoded = decode_booking_token(token)
        assert decoded["field_1"] == "ABC"
