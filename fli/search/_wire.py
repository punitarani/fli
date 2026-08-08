r"""Parsing helpers for Google Flights' FlightsFrontendService wire format.

The Service returns JSONP-flavoured responses of the form::

    )]}'\n\n
    <chunk1_len>\n
    [["wrb.fr", null, "<inner JSON string>"]]
    <chunk2_len>\n
    [["wrb.fr", null, "<inner JSON string>"]]
    ...

`GetShoppingResults` and `GetCalendarGraph` happen to emit a single chunk so
the legacy parsers in this package could get away with `lstrip(")]}'")`.
`GetBookingResults` emits two chunks, so we need a proper multi-chunk reader.

Important quirk: the length headers are **not** a dependable frame
delimiter. They count the chunk plus its two surrounding newlines, but in
characters rather than UTF-8 bytes, so any response carrying non-ASCII text
(accented airport or airline names) desynchronises a byte-oriented reader —
and an ASCII response hides the difference entirely. Rather than encode a
guess about Google's convention, this reader ignores the announced length
and lets the JSON grammar delimit each chunk, which is correct either way.
The headers are still used to re-synchronise after a malformed chunk.

This module centralises that reader and exposes :func:`iter_wrb_chunks` which
yields the decoded inner JSON of each ``wrb.fr`` chunk.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from typing import Any

from fli.search.exceptions import SearchBackendError

logger = logging.getLogger(__name__)

_PREFIX = ")]}'"

# Framing noise between two chunks: the length header and the newlines
# around it. Skipped wholesale — the header's value is never trusted.
_FRAMING_CHARS = "0123456789 \t\r\n"

# A chunk boundary in the raw stream: newline, decimal length header,
# newline, then the "[" that opens the next chunk. Literal newlines are
# escaped inside JSON strings, so this can never match within a payload.
_CHUNK_BOUNDARY = re.compile(r"\n\d+\n(?=\[)")

# Google reports rejected requests with gRPC's canonical status codes.
_STATUS_NAMES = {
    1: "CANCELLED",
    2: "UNKNOWN",
    3: "INVALID_ARGUMENT",
    4: "DEADLINE_EXCEEDED",
    5: "NOT_FOUND",
    6: "ALREADY_EXISTS",
    7: "PERMISSION_DENIED",
    8: "RESOURCE_EXHAUSTED",
    9: "FAILED_PRECONDITION",
    10: "ABORTED",
    11: "OUT_OF_RANGE",
    12: "UNIMPLEMENTED",
    13: "INTERNAL",
    14: "UNAVAILABLE",
    15: "DATA_LOSS",
    16: "UNAUTHENTICATED",
}


def iter_wrb_chunks(body: str | bytes) -> Iterator[Any]:
    """Yield the inner JSON object of every ``wrb.fr`` chunk in ``body``.

    Robust to single-chunk responses with no length headers (the older
    ``GetShoppingResults`` / ``GetCalendarGraph`` shape) — those parse the
    same way, since chunk boundaries are derived from the JSON itself.

    Raises:
        SearchBackendError: If Google answered with an error envelope
            instead of a payload. See :func:`_error_code`.

    """
    # ``errors="replace"`` keeps a corrupted transfer from raising here;
    # the resulting chunk simply fails to parse and is reported below.
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body

    text = text.lstrip()
    if text.startswith(_PREFIX):
        text = text[len(_PREFIX) :]
    text = text.lstrip()

    decoder = json.JSONDecoder()
    cursor = 0
    while cursor < len(text):
        while cursor < len(text) and text[cursor] in _FRAMING_CHARS:
            cursor += 1
        if cursor >= len(text):
            return
        try:
            outer, cursor = decoder.raw_decode(text, cursor)
        except ValueError:
            logger.warning("Discarding malformed wrb.fr chunk", exc_info=True)
            boundary = _CHUNK_BOUNDARY.search(text, cursor)
            if boundary is None:
                return
            cursor = boundary.end()
            continue
        yield from _chunks_from_outer(outer)


def _error_code(row: list[Any]) -> int | None:
    """Return the status code of an error-envelope ``wrb.fr`` row, if any.

    Google reports a rejected request with ``HTTP 200`` and a payload-less
    row of the shape ``["wrb.fr", null, null, null, null, [code]]``, e.g.
    ``3`` (``INVALID_ARGUMENT``) for a payload it cannot decode or ``13``
    (``INTERNAL``) for a request it declines to serve.
    """
    if len(row) < 6:
        return None
    status = row[5]
    if isinstance(status, list) and status and isinstance(status[0], int):
        return status[0]
    return None


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
            code = _error_code(row)
            if code is not None:
                name = _STATUS_NAMES.get(code)
                detail = f"{code} ({name})" if name else str(code)
                raise SearchBackendError(
                    f"Google Flights returned error {detail} instead of results",
                    error_code=code,
                )
            continue
        try:
            yield json.loads(inner)
        except (ValueError, json.JSONDecodeError):
            logger.warning("Failed to decode wrb.fr inner JSON payload", exc_info=True)
            continue


def parse_first_wrb_payload(body: str | bytes) -> Any:
    """Return the inner JSON of the first ``wrb.fr`` chunk, or None.

    Raises:
        SearchBackendError: If Google answered with an error envelope
            instead of a payload.

    """
    for chunk in iter_wrb_chunks(body):
        return chunk
    return None
