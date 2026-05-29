"""Tests for the GetBookingResults protobuf token builder and tfs deep-link token.

The builder reproduces a byte-perfect copy of the captured token from a
live booking-page URL. The captured fixture is the authoritative
reference — any change to the builder must keep this byte-equal.
"""

from __future__ import annotations

import base64

import pytest

from fli.search._proto import (
    LegSpec,
    build_booking_token,
    build_tfs_token,
    decode_booking_token,
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


# ---------------------------------------------------------------------------
# Captured tfs booking-URL fixtures (2026-05-28)
# ---------------------------------------------------------------------------

# Round-trip JFK→LAX (AA171 outbound, AA28 return) — the authoritative
# round-trip fixture, captured byte-for-byte from a live booking-page tfs.
_LIVE_TFS_RT = (
    "CBwQAho_EgoyMDI2LTA3LTE1Ih8KA0pGSxIKMjAyNi0wNy0xNRoDTEFYKgJBQTIDMTcxagcIAR"
    "IDSkZLcgcIARIDTEFYGj4SCjIwMjYtMDctMTkiHgoDTEFYEgoyMDI2LTA3LTE5GgNKRksqAkFBMgIy"
    "OGoHCAESA0xBWHIHCAESA0pGS0ABSAFwAYIBCwj___________8BmAEB"
)

# One-way nonstop LAX→ORD (UA729), captured 2026-05-28.  No segment-level f5
# field — matches encoder output byte-for-byte.
_LIVE_TFS_OW = (
    "CBwQAho_EgoyMDI2LTA4LTE1Ih8KA0xBWBIKMjAyNi0wOC0xNRoDT1JEKgJVQTIDNzI5"
    "agcIARIDTEFYcgcIARIDT1JEQAFIAXABggELCP___________wGYAQI"
)

# One-way 2-stop BOS→DEN(WN739)→SJC(WN389)→SEA(WN389), captured 2026-05-28.
# Three repeated f4 legs within one f3 segment.
_LIVE_TFS_3LEG = (
    "CBwQAhqBARIKMjAyNi0wOC0xNSIfCgNCT1MSCjIwMjYtMDgtMTUaA0RFTioCV04yAzczOSIfCgNERU4S"
    "CjIwMjYtMDgtMTUaA1NKQyoCV04yAzM4OSIfCgNTSkMSCjIwMjYtMDgtMTUaA1NFQSoCV04yAzM4OWoH"
    "CAESA0JPU3IHCAESA1NFQUABSAFwAYIBCwj___________8BmAEC"
)


def _b64url_to_bytes(s: str) -> bytes:
    """Decode a urlsafe-base64 string (padding optional) to raw bytes."""
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + pad)


class TestBuildTfsToken:
    """Byte-perfect golden tests for build_tfs_token."""

    def _tfs_bytes(self, tfs: str) -> bytes:
        return _b64url_to_bytes(tfs)

    def test_round_trip_byte_perfect(self):
        """Two-segment round-trip reproduces the captured booking-page tfs byte-for-byte."""
        segments = [
            # Outbound: JFK→LAX on 2026-07-15, AA171
            [LegSpec("JFK", "2026-07-15", "LAX", "AA", "171")],
            # Return: LAX→JFK on 2026-07-19, AA28
            [LegSpec("LAX", "2026-07-19", "JFK", "AA", "28")],
        ]
        built = build_tfs_token(segments, is_one_way=False)
        capt_hex = self._tfs_bytes(_LIVE_TFS_RT).hex()
        built_hex = _b64url_to_bytes(built).hex()
        assert self._tfs_bytes(built) == self._tfs_bytes(_LIVE_TFS_RT), (
            f"\nbuilt: {built_hex}\ncapt:  {capt_hex}"
        )

    def test_one_way_nonstop_byte_perfect(self):
        """One-way nonstop (LAX→ORD UA729) reproduces captured tfs byte-for-byte."""
        segments = [[LegSpec("LAX", "2026-08-15", "ORD", "UA", "729")]]
        built = build_tfs_token(segments, is_one_way=True)
        capt_hex = self._tfs_bytes(_LIVE_TFS_OW).hex()
        built_hex = _b64url_to_bytes(built).hex()
        assert self._tfs_bytes(built) == self._tfs_bytes(_LIVE_TFS_OW), (
            f"\nbuilt: {built_hex}\ncapt:  {capt_hex}"
        )

    def test_multi_leg_connection_byte_perfect(self):
        """Three-leg connection BOS→DEN→SJC→SEA reproduces captured tfs byte-for-byte."""
        segments = [
            [
                LegSpec("BOS", "2026-08-15", "DEN", "WN", "739"),
                LegSpec("DEN", "2026-08-15", "SJC", "WN", "389"),
                LegSpec("SJC", "2026-08-15", "SEA", "WN", "389"),
            ]
        ]
        built = build_tfs_token(segments, is_one_way=True)
        capt_hex = self._tfs_bytes(_LIVE_TFS_3LEG).hex()
        built_hex = _b64url_to_bytes(built).hex()
        assert self._tfs_bytes(built) == self._tfs_bytes(_LIVE_TFS_3LEG), (
            f"\nbuilt: {built_hex}\ncapt:  {capt_hex}"
        )

    def test_f19_one_way_is_2(self):
        built = build_tfs_token(
            [[LegSpec("SFO", "2026-09-01", "PHX", "AA", "100")]], is_one_way=True
        )
        raw = _b64url_to_bytes(built)
        # f19 tag: (19 << 3) | 0 = 152 = 0x98 (needs second varint byte 0x01); value = 2
        assert raw[-3:] == bytes([0x98, 0x01, 0x02])

    def test_f19_round_trip_is_1(self):
        segs = [
            [LegSpec("JFK", "2026-09-01", "LAX", "AA", "1")],
            [LegSpec("LAX", "2026-09-08", "JFK", "AA", "2")],
        ]
        built = build_tfs_token(segs, is_one_way=False)
        raw = _b64url_to_bytes(built)
        # f19 tag 0x98 0x01; value = 1
        assert raw[-3:] == bytes([0x98, 0x01, 0x01])

    def test_urlsafe_no_padding(self):
        built = build_tfs_token([[LegSpec("SFO", "2026-09-01", "PHX", "AA", "100")]])
        assert "=" not in built
        assert "+" not in built
        assert "/" not in built

    def test_empty_segments_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            build_tfs_token([])

    def test_empty_leg_list_raises(self):
        with pytest.raises(ValueError, match="no legs"):
            build_tfs_token([[]])

    def test_multi_leg_connection_repeated_f4(self):
        """Three legs in one segment → three repeated f4 fields (verified by byte count)."""
        segments = [
            [
                LegSpec("BOS", "2026-08-15", "DEN", "WN", "739"),
                LegSpec("DEN", "2026-08-15", "SJC", "WN", "389"),
                LegSpec("SJC", "2026-08-15", "SEA", "WN", "389"),
            ]
        ]
        built = build_tfs_token(segments, is_one_way=True)
        raw = _b64url_to_bytes(built)
        assert len(raw) == 159, f"expected 159 bytes, got {len(raw)}"

    def test_f9_airline_code_in_proto(self):
        """Frontier (F9) airline code is correctly encoded in the proto bytes."""
        segments = [[LegSpec("SFO", "2026-09-01", "PHX", "F9", "2638")]]
        built = build_tfs_token(segments)
        raw = _b64url_to_bytes(built)
        assert b"F9" in raw


class TestToUrlsafeB64:
    def test_converts_standard_to_urlsafe(self):
        from fli.search._proto import _to_urlsafe_b64

        # Bytes that produce + and / in standard base64
        data = bytes([0xFB, 0xFF])  # standard b64: +/8=
        result = _to_urlsafe_b64(data)
        assert "+" not in result
        assert "/" not in result
        assert "=" not in result

    def test_round_trips_to_original_bytes(self):
        from fli.search._proto import _to_urlsafe_b64

        data = b"\xde\xad\xbe\xef"
        encoded = _to_urlsafe_b64(data)
        pad = "=" * ((4 - len(encoded) % 4) % 4)
        assert base64.urlsafe_b64decode(encoded + pad) == data


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
