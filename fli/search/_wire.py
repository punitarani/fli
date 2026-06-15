r"""Parsing helpers for Google Flights' FlightsFrontendService wire format.

The Service returns JSONP-flavoured responses of the form::

    )]}'\n\n
    <chunk1_byte_len>\n
    [["wrb.fr", null, "<inner JSON string>"]]
    <chunk2_byte_len>\n
    [["wrb.fr", null, "<inner JSON string>"]]
    ...

`GetShoppingResults` and `GetCalendarGraph` happen to emit a single chunk so
the legacy parsers in this package could get away with `lstrip(")]}'")`.
`GetBookingResults` emits two chunks, so we need a proper multi-chunk reader.

Important quirk: the length headers count UTF-8 **bytes**, not Python string
characters. When the response contains any non-ASCII characters (which it
sometimes does — airport names, airline names) the offsets diverge, so the
reader must operate over the byte representation of the body.

This module centralises that reader and exposes :func:`iter_wrb_chunks` which
yields the decoded inner JSON of each ``wrb.fr`` chunk.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

_PREFIX = b")]}'"


def _iter_outer(body: str | bytes) -> Iterator[Any]:
    """Yield each top-level parsed list (one per response chunk) in ``body``.

    This is the raw framing layer: it strips the JSONP prefix, walks the
    byte-length-prefixed chunk stream and JSON-decodes each chunk's outer
    array — but does *not* descend into ``wrb.fr`` rows. Callers that want
    the decoded inner payloads use :func:`iter_wrb_chunks`; callers that
    need to inspect the row shape itself (e.g. to detect Google's error
    envelope) iterate the outer rows directly.
    """
    if isinstance(body, str):
        raw = body.encode("utf-8")
    else:
        raw = body

    raw = raw.lstrip()
    if raw.startswith(_PREFIX):
        raw = raw[len(_PREFIX) :]
    raw = raw.lstrip()

    if not raw:
        return

    # Fast path: no length headers (legacy single-chunk responses).
    if not (b"0" <= raw[:1] <= b"9"):
        try:
            yield json.loads(raw.decode("utf-8"))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("Failed to decode single-chunk wrb.fr body as JSON", exc_info=True)
        return

    cursor = 0
    while cursor < len(raw):
        # Read the decimal length prefix terminated by \n.
        end = raw.find(b"\n", cursor)
        if end == -1:
            break
        try:
            length = int(raw[cursor:end])
        except ValueError:
            logger.warning(
                "Malformed length header at offset %d; truncating chunk stream",
                cursor,
            )
            break
        # Google's length header counts the leading newline after the header
        # AND the trailing newline that separates this chunk from the next.
        # We've already consumed the leading newline (it terminated the header),
        # so we read `length - 1` bytes which gives JSON + trailing \n.
        cursor = end + 1
        chunk_bytes = max(length - 1, 0)
        payload = raw[cursor : cursor + chunk_bytes]
        cursor += chunk_bytes
        try:
            yield json.loads(payload.strip().decode("utf-8"))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("Discarding malformed wrb.fr chunk", exc_info=True)
            continue


def iter_wrb_chunks(body: str | bytes) -> Iterator[Any]:
    """Yield the inner JSON object of every ``wrb.fr`` chunk in ``body``.

    Robust to single-chunk responses with no length headers (the older
    ``GetShoppingResults`` / ``GetCalendarGraph`` shape) — those are parsed
    by falling back to a single JSON load over the trimmed body.
    """
    for outer in _iter_outer(body):
        yield from _chunks_from_outer(outer)


def wrb_error_code(body: str | bytes) -> int | None:
    """Return the gRPC status code if the first ``wrb.fr`` row is an error envelope.

    Google's FlightsFrontendService sometimes answers an otherwise valid
    request with **HTTP 200** whose ``wrb.fr`` row carries no inner data
    payload but instead a typed ``ErrorResponse`` block::

        ["wrb.fr", null, null, null, null, [13, null,
            [["type.googleapis.com/travel.frontend.flights.ErrorResponse", ...]]]]

    The ``13`` is a canonical gRPC status code (``INTERNAL``). Left
    undetected this row decodes to "no inner string" and the search
    silently looks like an empty result — see issue #200, where a transient
    Google-side outage made every query return zero flights with no error.

    Returns the integer status code (or ``-1`` if the code field isn't an
    int) when the first ``wrb.fr`` row is an error envelope; ``None`` when
    the first row carries a normal data payload or no envelope is present.
    """
    for outer in _iter_outer(body):
        if not isinstance(outer, list):
            continue
        for row in outer:
            if not (isinstance(row, list) and len(row) >= 3 and row[0] == "wrb.fr"):
                continue
            # A normal data row carries the inner payload as a JSON string.
            if isinstance(row[2], str) and row[2]:
                return None
            # An error envelope carries [code, null, [[type_url, ...]]] at row[5].
            if len(row) >= 6 and isinstance(row[5], list) and row[5] and _is_error_block(row[5]):
                code = row[5][0]
                return code if isinstance(code, int) else -1
            # First wrb.fr row is neither data nor a recognisable error.
            return None
    return None


def _is_error_block(block: Any) -> bool:
    """Return True when ``block`` is ``[code, null, [[type_url, ...]]]`` with an Error type."""
    try:
        details = block[2]
    except (IndexError, TypeError):
        return False
    if not isinstance(details, list):
        return False
    for entry in details:
        if isinstance(entry, list) and entry and isinstance(entry[0], str) and "Error" in entry[0]:
            return True
    return False


def _chunks_from_outer(outer: Any) -> Iterator[Any]:
    """Walk a top-level chunk list and yield decoded inner-JSON payloads."""
    if not isinstance(outer, list):
        return
    for row in outer:
        if not isinstance(row, list) or len(row) < 3:
            continue
        if row[0] != "wrb.fr":
            continue
        inner = row[2]
        if not isinstance(inner, str) or not inner:
            continue
        try:
            yield json.loads(inner)
        except (ValueError, json.JSONDecodeError):
            logger.warning("Failed to decode wrb.fr inner JSON payload", exc_info=True)
            continue


def parse_first_wrb_payload(body: str | bytes) -> Any:
    """Return the inner JSON of the first ``wrb.fr`` chunk, or None."""
    for chunk in iter_wrb_chunks(body):
        return chunk
    return None
