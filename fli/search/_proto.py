"""Minimal protobuf wire-format encoder used to build the GetBookingResults token.

Google's booking-options endpoint accepts a base64-encoded protobuf as
``outer[0][1]``. The structure was reverse-engineered from a live capture
on 2026-05-14 (see ``.reverse-eng/notes/booking_results.md``):

::

    field 1 (length-delim): shopping session id            (response `inner[0][4]`)
    field 2 (length-delim): "{airline}{flight_no}#{idx}"   (selected itinerary)
    field 3 (length-delim, nested):
        field 1 (varint): price in smallest currency unit   (e.g. cents)
        field 2 (varint): 2                                 (constant in our samples)
        field 3 (length-delim): ISO currency code           (e.g. "USD")
    field 7 (varint): 28                                    (stops bucket marker)
    field 14 (varint): same as inner field 1                (price duplicated)

We implement only the protobuf primitives we need here — varint, length-
delimited string/bytes, nested-message — to avoid the protobuf-runtime
dependency.
"""

from __future__ import annotations

import base64
import logging

logger = logging.getLogger(__name__)


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


def extract_booking_token_from_tfu(tfu: str) -> str:
    """Extract the booking token from a booking-page ``tfu`` URL parameter.

    Google Flights' booking page URL has the shape::

        /booking?tfs=<tfs>&tfu=<tfu>...

    where ``tfu`` is a base64-encoded protobuf wrapping the booking token::

        tfu = base64( protobuf {
          field 1 (str): base64( <booking token bytes> )
          field 2 (nested): { ... }
          field 4 (str): "" or other padding
        } )

    This helper accepts either a bare ``tfu`` value or a full URL and
    returns the inner booking token in the same base64 form
    :class:`SearchFlights.get_booking_options` accepts via its
    ``booking_token`` kwarg.

    Args:
        tfu: A ``tfu`` URL parameter value, or a full URL containing one.

    Returns:
        The base64-encoded booking token suitable for
        :meth:`SearchFlights.get_booking_options`.

    Raises:
        ValueError: If the input does not contain a parseable tfu blob.

    """
    # Accept full URL
    if "tfu=" in tfu:
        from urllib.parse import parse_qs, urlparse

        parts = urlparse(tfu)
        qs = parse_qs(parts.query)
        if "tfu" not in qs:
            raise ValueError("URL has no `tfu` query parameter")
        tfu = qs["tfu"][0]

    # Decode the outer protobuf
    padding = "=" * ((4 - len(tfu) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(tfu + padding)
    except (ValueError, base64.binascii.Error) as e:
        raise ValueError(f"tfu is not valid base64: {e}") from e

    # Walk protobuf fields looking for field 1 (length-delim string)
    off = 0
    while off < len(raw):
        tag, off = _read_varint(raw, off)
        field = tag >> 3
        wire = tag & 0x7
        if wire == 0:
            _, off = _read_varint(raw, off)
        elif wire == 2:
            length, off = _read_varint(raw, off)
            data = raw[off : off + length]
            off += length
            if field == 1:
                try:
                    token_b64 = data.decode("ascii")
                except UnicodeDecodeError as e:
                    raise ValueError("tfu field 1 is not ASCII") from e
                # Strip trailing whitespace/padding-like chars and
                # re-normalise to the standard base64 alphabet so the
                # downstream parser accepts it.
                token_b64 = token_b64.strip().rstrip("=")
                return token_b64
        elif wire == 5:
            off += 4
        elif wire == 1:
            off += 8
        else:
            raise ValueError(f"unsupported wire type {wire} at offset {off}")

    raise ValueError("tfu protobuf has no field 1 (booking token)")


def extract_session_id_from_tfu(tfu: str) -> str:
    """Extract the booking session id from a ``tfu`` URL parameter.

    Convenience wrapper that calls :func:`extract_booking_token_from_tfu`
    then decodes the inner token's ``field 1`` (the session id).
    """
    inner_token = extract_booking_token_from_tfu(tfu)
    decoded = decode_booking_token(inner_token)
    session = decoded.get("field_1")
    if not isinstance(session, str):
        raise ValueError("inner booking token has no field 1 (session id)")
    return session
