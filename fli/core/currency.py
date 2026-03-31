"""Utilities for extracting and formatting price currencies."""

from __future__ import annotations

import base64
from collections.abc import Iterable

from babel.numbers import format_currency as babel_format_currency


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


def _extract_currency_from_message(data: bytes) -> str | None:
    """Extract the nested ISO currency code from a decoded token."""
    offset = 0

    while offset < len(data):
        tag, offset = _read_varint(data, offset)
        field_number = tag >> 3
        wire_type = tag & 0x07

        if field_number == 3 and wire_type == 2:
            nested_message, offset = _read_length_delimited(data, offset)
            nested_offset = 0
            while nested_offset < len(nested_message):
                nested_tag, nested_offset = _read_varint(nested_message, nested_offset)
                nested_field = nested_tag >> 3
                nested_wire_type = nested_tag & 0x07

                if nested_field == 3 and nested_wire_type == 2:
                    currency_bytes, nested_offset = _read_length_delimited(
                        nested_message, nested_offset
                    )
                    return currency_bytes.decode("utf-8").upper()

                nested_offset = _skip_field(nested_message, nested_offset, nested_wire_type)
            continue

        offset = _skip_field(data, offset, wire_type)

    return None


def extract_currency_from_price_token(token: str | None) -> str | None:
    """Extract the ISO currency code from a Google Flights price token."""
    if not token:
        return None

    try:
        padded_token = token + ("=" * (-len(token) % 4))
        decoded = base64.urlsafe_b64decode(padded_token)
        return _extract_currency_from_message(decoded)
    except (UnicodeDecodeError, ValueError, base64.binascii.Error):
        return None


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
