"""Tests for the GetBookingResults protobuf token builder + tfu URL parser.

The builder reproduces a byte-perfect copy of the captured token from a
live booking-page URL. The captured fixture is the authoritative
reference — any change to the builder must keep this byte-equal.

The tfu parser extracts the same booking token from a ``tfu=`` URL
parameter — the value Google's UI puts in the booking-page URL after a
user clicks "Select flight".
"""

from __future__ import annotations

import base64

import pytest

from fli.search._proto import (
    build_booking_token,
    decode_booking_token,
    extract_booking_token_from_tfu,
    extract_session_id_from_tfu,
)

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
        assert b_built == b_capt, f"\nbuilt: {b_built.hex()}\ncapt:  {b_capt.hex()}"

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

    @pytest.mark.parametrize("code", ["USD", "EUR", "GBP", "JPY", "INR"])
    def test_different_currencies(self, code):
        token = build_booking_token("S", "DL", "1", 1, 100, code)
        decoded = decode_booking_token(token)
        assert decoded["field_3"]["field_3"] == code

    @pytest.mark.parametrize("idx", [0, 1, 2, 5, 10])
    def test_leg_index_in_field_2(self, idx):
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
        token = build_booking_token("S", "A", "1", 0, 0, "X")
        decoded = decode_booking_token(token)
        assert decoded["field_3"]["field_1"] == 0
        assert decoded["field_2"] == "A1#0"

    def test_zero_padding_handling(self):
        # Tokens whose base64 needs padding (length mod 4 != 0) round-trip.
        token = build_booking_token("ABC", "AA", "1", 1, 100, "USD")
        decoded = decode_booking_token(token)
        assert decoded["field_1"] == "ABC"


@pytest.mark.parametrize(
    "session_id, airline_code, flight_number, price_cents, currency, exc_match",
    [
        ("S", "AA", "1", -1, "USD", "price_cents must be non-negative"),
        ("", "AA", "1", 100, "USD", "session_id must be non-empty"),
        ("S", "", "1", 100, "USD", "airline_code must be non-empty"),
        ("S", "AA", "", 100, "USD", "flight_number must be non-empty"),
        ("S", "AA", "1", 100, "", "currency must be non-empty"),
    ],
)
def test_build_booking_token_validation(
    session_id, airline_code, flight_number, price_cents, currency, exc_match
):
    """Reject empty / negative inputs upfront."""
    with pytest.raises(ValueError, match=exc_match):
        build_booking_token(session_id, airline_code, flight_number, 1, price_cents, currency)


def test_non_ascii_session_id_encodes():
    # If Google ever returns a non-ASCII session id, the builder must
    # not crash — UTF-8 keeps round-trip equivalence for ASCII data
    # while accepting arbitrary bytes for the future.
    token = build_booking_token("Sé", "AA", "1", 1, 100, "USD")
    decoded = decode_booking_token(token)
    # decode_booking_token's ascii-decoder will replace the non-ascii
    # byte, but the call doesn't raise.
    assert "field_1" in decoded


class TestDecodeBookingTokenEdgeCases:
    def test_unsupported_top_level_wire_type_rejected(self):
        # Build a payload with wire type 5 (fixed32) at top level.
        # Tag byte = (1 << 3) | 5 = 0x0D, then 4 bytes of data.
        bad_payload = bytes([0x0D, 0x01, 0x02, 0x03, 0x04])
        bad_token = base64.b64encode(bad_payload).decode("ascii")
        with pytest.raises(ValueError, match="unsupported wire type 5"):
            decode_booking_token(bad_token)


# Live `tfu` URL parameter captured 2026-05-14 from a JFK→LAX RT booking page.
LIVE_TFU = (
    "CmxDalJJVVZwUk1FOUJjRVZyZEVWQlEzaFRkVkZDUnkwdExTMHRMUzB0TFhCcVltWjZOMEZCUVVGQlIyOUd"
    "PVlpGU0U5SVVXRkJFZ1pCUVRJNEl6RWFDd2o0amdJUUFob0RWVk5FT0J4dytJNEMSAggAIgA"
)
LIVE_BOOKING_URL = (
    "https://www.google.com/travel/flights/booking"
    "?tfs=CBwQAho_EgoyMDI2LTA3LTE1Ih8KA0pGSxIKMjAyNi0wNy0xNRoDTEFYKgJBQTIDMTcxagcIAR"
    "IDSkZLcgcIARIDTEFYGj4SCjIwMjYtMDctMTkiHgoDTEFYEgoyMDI2LTA3LTE5GgNKRksqAkFBMgIy"
    "OGoHCAESA0xBWHIHCAESA0pGS0ABSAFwAYIBCwj___________8BmAEB"
    f"&tfu={LIVE_TFU}&hl=en&gl=US&curr=USD"
)


class TestExtractBookingTokenFromTfu:
    def test_extract_from_bare_tfu_value(self):
        token = extract_booking_token_from_tfu(LIVE_TFU)
        # The extracted bytes must decode back to a recognisable booking token.
        decoded = decode_booking_token(token)
        assert decoded["field_2"] == "AA28#1"
        assert decoded["field_3"]["field_3"] == "USD"

    def test_extract_from_full_booking_url(self):
        token_url = extract_booking_token_from_tfu(LIVE_BOOKING_URL)
        token_bare = extract_booking_token_from_tfu(LIVE_TFU)
        assert token_url == token_bare

    def test_extract_session_id_round_trip(self):
        session = extract_session_id_from_tfu(LIVE_TFU)
        # 50-ish base64-alphabet bytes, starts with H, has "--" separator
        assert isinstance(session, str)
        assert len(session) > 30
        assert session.startswith("H")
        assert "-" in session

    def test_url_without_tfu_param_rejected(self):
        with pytest.raises(ValueError):
            extract_booking_token_from_tfu(
                "https://www.google.com/travel/flights/booking?tfs=ABC&hl=en"
            )

    def test_invalid_base64_rejected(self):
        # Garbage input should raise ValueError (specific message varies
        # by which validation step rejects first).
        with pytest.raises(ValueError):
            extract_booking_token_from_tfu("!!!!not-valid-base64!!!!")


@pytest.mark.parametrize(
    "data, expected",
    [
        (b"\x00", (0, 1)),
        (b"\x7f", (127, 1)),
        (b"\x80\x01", (128, 2)),
    ],
)
def test_read_varint(data, expected):
    from fli.search._proto import _read_varint

    assert _read_varint(data, 0) == expected


def test_read_varint_truncated_raises():
    from fli.search._proto import _read_varint

    with pytest.raises(IndexError):
        _read_varint(b"\x80", 0)  # MSB set but no continuation byte


class TestExtractBookingTokenFromTfuEdgeCases:
    """edge-case wire types that appear before field 1 in the outer tfu protobuf."""

    def _encode_tfu(self, raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @pytest.mark.parametrize(
        "prefix_bytes, token_bytes",
        [
            # field 2, wire 5 (fixed32): tag 0x15, 4 bytes
            (bytes([0x15]) + bytes([0x00, 0x00, 0x00, 0x01]), b"testtoken"),
            # field 3, wire 1 (fixed64): (3 << 3) | 1 = 0x19, 8 bytes
            (bytes([0x19]) + bytes(8), b"mytoken"),
        ],
    )
    def test_non_field1_wire_types_skipped(self, prefix_bytes, token_bytes):
        field1 = bytes([0x0A]) + bytes([len(token_bytes)]) + token_bytes
        tfu = self._encode_tfu(prefix_bytes + field1)
        assert extract_booking_token_from_tfu(tfu) == token_bytes.decode("ascii")

    def test_no_field1_raises_value_error(self):
        from fli.search._proto import _varint_field

        # Only field 2 as a varint — no field 1 present.
        raw = _varint_field(2, 42)
        tfu = self._encode_tfu(raw)
        with pytest.raises(ValueError, match="no field 1"):
            extract_booking_token_from_tfu(tfu)

    def test_unsupported_wire_type_raises_value_error(self):
        # Wire type 3 (start group) is not handled.
        # Tag for field 1, wire 3 = (1 << 3) | 3 = 11
        raw = bytes([11])
        tfu = self._encode_tfu(raw)
        with pytest.raises(ValueError, match="unsupported wire type"):
            extract_booking_token_from_tfu(tfu)


class TestDecodeBookingTokenHexFallback:
    def test_non_decodable_nested_field_stored_as_hex(self):
        """A field neither printable ASCII nor a valid nested message.

        Should be stored as a hex string instead of raising.
        """
        from fli.search._proto import _length_delim

        # bytes([0x80]) is not valid ASCII and causes IndexError when parsed
        # as a nested protobuf varint — the decoder should fall back to hex.
        raw = _length_delim(3, bytes([0x80]))
        token = base64.b64encode(raw).decode("ascii")
        decoded = decode_booking_token(token)
        assert decoded["field_3"] == "80"
