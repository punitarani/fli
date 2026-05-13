"""Utilities for extracting and formatting price currencies."""

from __future__ import annotations

import base64
from collections.abc import Iterable

from babel.numbers import format_currency as babel_format_currency
from babel.numbers import get_currency_precision


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    """Read a protobuf-style varint value."""
    value = 0
    shift = 0

    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset

        shift += 7
        if shift >= 64:
            raise ValueError("Varint is too large to decode")

    raise ValueError("Unexpected end of data while decoding varint")


def _read_length_delimited(data: bytes, offset: int) -> tuple[bytes, int]:
    """Read a protobuf-style length-delimited field."""
    length, offset = _read_varint(data, offset)
    end = offset + length
    if end > len(data):
        raise ValueError("Length-delimited field exceeds payload size")
    return data[offset:end], end


def _skip_field(data: bytes, offset: int, wire_type: int) -> int:
    """Skip over a protobuf field we do not need."""
    if wire_type == 0:
        _, offset = _read_varint(data, offset)
        return offset
    if wire_type == 1:
        end = offset + 8
        if end > len(data):
            raise ValueError("Fixed64 field exceeds payload size")
        return end
    if wire_type == 2:
        _, offset = _read_length_delimited(data, offset)
        return offset
    if wire_type == 5:
        end = offset + 4
        if end > len(data):
            raise ValueError("Fixed32 field exceeds payload size")
        return end
    raise ValueError(f"Unsupported wire type: {wire_type}")


# Field numbers within the outer ItinerarySummary message returned by
# Google Flights. The nested Price message lives at field 3, and contains:
#   field 1: int32 price (in minor currency units, e.g. cents for USD)
#   field 3: string currency (ISO code, e.g. "USD")
_PRICE_FIELD_NUMBER = 3
_PRICE_INNER_AMOUNT_FIELD = 1
_PRICE_INNER_CURRENCY_FIELD = 3


def _extract_price_info_from_message(data: bytes) -> tuple[int | None, str | None]:
    """Extract the raw price (minor units) and currency code from a decoded token."""
    offset = 0
    raw_price: int | None = None
    currency: str | None = None

    while offset < len(data):
        tag, offset = _read_varint(data, offset)
        field_number = tag >> 3
        wire_type = tag & 0x07

        if field_number == _PRICE_FIELD_NUMBER and wire_type == 2:
            nested_message, offset = _read_length_delimited(data, offset)
            nested_offset = 0
            while nested_offset < len(nested_message):
                nested_tag, nested_offset = _read_varint(nested_message, nested_offset)
                nested_field = nested_tag >> 3
                nested_wire_type = nested_tag & 0x07

                if (
                    nested_field == _PRICE_INNER_AMOUNT_FIELD
                    and nested_wire_type == 0
                    and raw_price is None
                ):
                    raw_price, nested_offset = _read_varint(nested_message, nested_offset)
                elif (
                    nested_field == _PRICE_INNER_CURRENCY_FIELD
                    and nested_wire_type == 2
                    and currency is None
                ):
                    currency_bytes, nested_offset = _read_length_delimited(
                        nested_message, nested_offset
                    )
                    currency = currency_bytes.decode("utf-8").upper()
                else:
                    nested_offset = _skip_field(nested_message, nested_offset, nested_wire_type)

            if raw_price is not None or currency is not None:
                return raw_price, currency
            continue

        offset = _skip_field(data, offset, wire_type)

    return raw_price, currency


def _decode_price_token(token: str | None) -> tuple[int | None, str | None]:
    """Decode a Google Flights price token to (raw_price, currency)."""
    if not token:
        return None, None

    try:
        padded_token = token + ("=" * (-len(token) % 4))
        decoded = base64.urlsafe_b64decode(padded_token)
        return _extract_price_info_from_message(decoded)
    except (UnicodeDecodeError, ValueError, base64.binascii.Error):
        return None, None


def _scale_price(raw_price: int, currency: str | None) -> float:
    """Scale a protobuf raw price (minor units) to display units using ISO precision."""
    precision = 2
    if currency:
        try:
            precision = get_currency_precision(currency.upper())
        except Exception:
            pass
    return raw_price / (10**precision)


def extract_currency_from_price_token(token: str | None) -> str | None:
    """Extract the ISO currency code from a Google Flights price token."""
    _, currency = _decode_price_token(token)
    return currency


def extract_price_from_price_token(token: str | None) -> float | None:
    """Extract the display price from a Google Flights price token.

    Google Flights stores prices in the protobuf token at field 3 → field 1
    in minor currency units (e.g. cents for USD), with the ISO currency at
    field 3 → field 3. The amount is scaled back to display units using the
    currency's standard precision (2 for USD/EUR, 0 for KRW/JPY).

    Returns ``None`` if the token is missing, malformed, or contains no price.
    Used as a fallback when the direct integer price at ``data[1][0][-1]`` is
    absent — common for LCC carriers that don't sell through Google's booking
    partners (e.g. Eastar Jet, Aero K, Wizz Air).
    """
    raw_price, currency = _decode_price_token(token)
    if raw_price is None:
        return None
    return _scale_price(raw_price, currency)


def format_price(amount: float, currency_code: str | None) -> str:
    """Format a price using its ISO currency code."""
    if not currency_code:
        return f"{amount:,.2f}"

    normalized_currency = currency_code.upper()
    try:
        return babel_format_currency(amount, normalized_currency, locale="en_US")
    except (TypeError, ValueError):
        return f"{normalized_currency} {amount:,.2f}"


def format_price_axis_label(currencies: Iterable[str | None]) -> str:
    """Build a chart axis label for one or more result currencies."""
    normalized = {currency.upper() for currency in currencies if currency}
    if len(normalized) == 1:
        return f"Price ({normalized.pop()})"
    return "Price"
