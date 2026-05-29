"""Minimal protobuf wire-format encoder used to build booking tokens and URLs.

Two token types are implemented:

1. **GetBookingResults token** (``outer[0][1]``) — used for the vendor-list
   API call.  Structure reverse-engineered 2026-05-14 (see
   ``.reverse-eng/notes/booking_results.md``):

   ::

       field 1 (length-delim): shopping session id            (response ``inner[0][4]``)
       field 2 (length-delim): "{airline}{flight_no}#{idx}"   (selected itinerary)
       field 3 (length-delim, nested):
           field 1 (varint): price in smallest currency unit   (e.g. cents)
           field 2 (varint): 2                                 (constant)
           field 3 (length-delim): ISO currency code           (e.g. "USD")
       field 7 (varint): 28                                    (stops bucket marker)
       field 14 (varint): same as inner field 1                (price duplicated)

2. **Deep-link itinerary token** (``tfs``) — embedded in
   ``https://www.google.com/travel/flights/booking?tfs=…`` to open a specific
   itinerary's booking page (vendor fares + "Continue" CTA included). The
   ``tfs`` token alone is sufficient; the companion ``tfu`` token Google's UI
   also emits is not needed and is intentionally not built. Structure
   reverse-engineered 2026-05-28 (see ``.reverse-eng/notes/booking_results.md``).

We implement only the protobuf primitives we need here — varint, length-
delimited string/bytes, nested-message — to avoid the protobuf-runtime
dependency.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# tfs deep-link helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LegSpec:
    """One physical leg within a booking-URL segment.

    Attributes:
        origin: IATA code of the departure airport (e.g. ``"SFO"``).
        dep_date: Departure date in ``YYYY-MM-DD`` format.
        dest: IATA code of the arrival airport (e.g. ``"PHX"``).
        airline: Airline IATA code (e.g. ``"AA"``).
        flight_number: Flight number string (e.g. ``"2413"``).

    """  # noqa: D413 — blank-line-after-last-section false-positive on frozen dataclass

    origin: str
    dep_date: str
    dest: str
    airline: str
    flight_number: str


def _varint(value: int) -> bytes:
    """Encode an unsigned integer as a protobuf varint."""
    if value < 0:
        raise ValueError("varint encoder takes non-negative ints only")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    """Encode a protobuf field tag (field_number << 3 | wire_type)."""
    return _varint((field << 3) | wire)


def _length_delim(field: int, payload: bytes) -> bytes:
    """Encode a length-delimited field (wire type 2)."""
    return _tag(field, 2) + _varint(len(payload)) + payload


def _varint_field(field: int, value: int) -> bytes:
    """Encode a varint field (wire type 0)."""
    return _tag(field, 0) + _varint(value)


def build_booking_token(
    session_id: str,
    airline_code: str,
    flight_number: str,
    leg_index: int,
    price_cents: int,
    currency: str = "USD",
) -> str:
    """Construct the GetBookingResults outer[0][1] token.

    Args:
        session_id: Shopping session id from a prior search response
            (``inner[0][4]`` — a 50-ish-byte opaque string).
        airline_code: IATA code of the airline carrying the *last leg* of
            the selected itinerary (e.g. ``"AA"``).
        flight_number: Flight number of the last leg (e.g. ``"28"``).
        leg_index: 1-based position of the leg in the itinerary. For
            one-way, ``1``. For round-trip, use ``1`` for the return leg.
        price_cents: Booking price in the smallest unit of ``currency``
            (e.g. cents, pence, yen — for USD multiply dollars by 100).
        currency: ISO 4217 currency code; defaults to ``"USD"``.

    Returns:
        The base64-encoded protobuf token, suitable for use as
        ``outer[0][1]`` in a GetBookingResults POST.

    Raises:
        ValueError: ``price_cents`` is negative, or one of the string
            arguments is empty.

    """
    if price_cents < 0:
        raise ValueError("price_cents must be non-negative")
    if not session_id:
        raise ValueError("session_id must be non-empty")
    if not airline_code:
        raise ValueError("airline_code must be non-empty")
    if not flight_number:
        raise ValueError("flight_number must be non-empty")
    if not currency:
        raise ValueError("currency must be non-empty")

    # Protobuf length-delimited fields can hold arbitrary bytes; UTF-8 is
    # the lingua-franca encoding and round-trips ASCII transparently. The
    # earlier ``.encode("ascii")`` hard-crashed on any non-ASCII byte from
    # Google — even though all current values are ASCII, that brittleness
    # would surface as an opaque crash if Google ever shipped a non-ASCII
    # session id. UTF-8 sidesteps that without changing live behaviour.
    nested = (
        _varint_field(1, price_cents)
        + _varint_field(2, 2)
        + _length_delim(3, currency.encode("utf-8"))
    )

    payload = (
        _length_delim(1, session_id.encode("utf-8"))
        + _length_delim(2, f"{airline_code}{flight_number}#{leg_index}".encode())
        + _length_delim(3, nested)
        + _varint_field(7, 28)
        + _varint_field(14, price_cents)
    )

    # base64 (standard alphabet — the captured token uses + and /)
    return base64.b64encode(payload).decode("ascii")


def decode_booking_token(token: str) -> dict:
    """Decode a booking token for debugging / round-trip tests.

    Mirrors :func:`build_booking_token` — useful for assertions in tests
    and for displaying captured tokens in human-readable form.
    """
    padded = token + "=" * ((4 - len(token) % 4) % 4)
    raw = base64.urlsafe_b64decode(padded.replace("+", "-").replace("/", "_"))
    result: dict = {}
    offset = 0
    while offset < len(raw):
        tag, offset = _read_varint(raw, offset)
        field = tag >> 3
        wire = tag & 0x7
        if wire == 0:
            value, offset = _read_varint(raw, offset)
            result[f"field_{field}"] = value
        elif wire == 2:
            length, offset = _read_varint(raw, offset)
            data = raw[offset : offset + length]
            offset += length
            # Try string
            try:
                s = data.decode("ascii")
                if all(0x20 <= ord(c) <= 0x7E for c in s):
                    result[f"field_{field}"] = s
                    continue
            except UnicodeDecodeError:
                pass
            # Otherwise nested
            try:
                nested = {}
                noff = 0
                while noff < len(data):
                    tag, noff = _read_varint(data, noff)
                    nfield = tag >> 3
                    nwire = tag & 0x7
                    if nwire == 0:
                        v, noff = _read_varint(data, noff)
                        nested[f"field_{nfield}"] = v
                    elif nwire == 2:
                        nl, noff = _read_varint(data, noff)
                        nested[f"field_{nfield}"] = data[noff : noff + nl].decode(
                            "ascii", errors="replace"
                        )
                        noff += nl
                    else:
                        nested[f"field_{nfield}"] = f"<wire {nwire}>"
                result[f"field_{field}"] = nested
            except (IndexError, UnicodeDecodeError, ValueError):
                # Not a nested message — fall back to raw hex for debugging.
                logger.debug("Field %d not a nested message; storing as hex", field)
                result[f"field_{field}"] = data.hex()
        else:
            raise ValueError(f"unsupported wire type {wire} at offset {offset}")
    return result


def _read_varint(buf: bytes, off: int) -> tuple[int, int]:
    value, shift = 0, 0
    while True:
        byte = buf[off]
        off += 1
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return value, off
        shift += 7


# ---------------------------------------------------------------------------
# Deep-link URL parameter builder (tfs)
# ---------------------------------------------------------------------------


def _to_urlsafe_b64(data: bytes) -> str:
    """Encode *data* as URL-safe base64 without ``=`` padding.

    The ``tfs`` query parameter uses the urlsafe alphabet (``-`` / ``_``) with
    padding stripped.
    """
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def build_tfs_token(
    segments: list[list[LegSpec]],
    *,
    is_one_way: bool = True,
) -> str:
    """Build the ``tfs`` query parameter for a Google Flights deep-link URL.

    The ``tfs`` token encodes the complete itinerary — one segment per travel
    direction, each segment containing one leg per physical flight.  It is
    deterministic (no session id required) and can be constructed purely from
    search-result data.

    Reverse-engineered 2026-05-28 from live browser captures of one-way
    nonstop, one-way connection (2-stop), and round-trip booking pages (see
    ``.reverse-eng/notes/booking_results.md``).

    Args:
        segments: Ordered list of travel directions.  Each element is a list
            of :class:`LegSpec` describing every physical leg in that
            direction (one leg for nonstop, two or more for connections).
        is_one_way: ``True`` for one-way (including multi-city); ``False``
            for round-trip.  Controls the ``f19`` constant.

    Returns:
        URL-safe base64 string (no ``=`` padding) suitable for use as the
        ``tfs=`` query parameter.

    Raises:
        ValueError: *segments* is empty or any segment has no legs.

    """
    if not segments:
        raise ValueError("segments must be non-empty")
    for i, seg in enumerate(segments):
        if not seg:
            raise ValueError(f"segment {i} has no legs")

    segment_protos = b""
    for seg in segments:
        # Each leg becomes a repeated f4 within this segment.
        legs_proto = b""
        for leg in seg:
            leg_proto = (
                _length_delim(1, leg.origin.encode())
                + _length_delim(2, leg.dep_date.encode())
                + _length_delim(3, leg.dest.encode())
                + _length_delim(5, leg.airline.encode())
                + _length_delim(6, leg.flight_number.encode())
            )
            legs_proto += _length_delim(4, leg_proto)

        origin_iata = seg[0].origin
        dest_iata = seg[-1].dest
        seg_date = seg[0].dep_date

        seg_proto = (
            _length_delim(2, seg_date.encode())
            + legs_proto
            + _length_delim(13, _varint_field(1, 1) + _length_delim(2, origin_iata.encode()))
            + _length_delim(14, _varint_field(1, 1) + _length_delim(2, dest_iata.encode()))
        )
        segment_protos += _length_delim(3, seg_proto)

    # f16 constant: max uint64 (0xFFFFFFFFFFFFFFFF)
    _MAX_U64 = (1 << 64) - 1

    # f19: 2 = one-way / multi-city, 1 = round-trip
    f19 = 2 if is_one_way else 1

    payload = (
        _varint_field(1, 28)
        + _varint_field(2, 2)
        + segment_protos
        + _varint_field(8, 1)
        + _varint_field(9, 1)
        + _varint_field(14, 1)
        + _length_delim(16, _varint_field(1, _MAX_U64))
        + _varint_field(19, f19)
    )
    return _to_urlsafe_b64(payload)
