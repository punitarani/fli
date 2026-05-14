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

This module centralises that reader and exposes :func:`iter_wrb_chunks` which
yields the decoded inner JSON of each ``wrb.fr`` chunk.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any  # noqa: F401  (used in annotations)

_PREFIX = ")]}'"


def iter_wrb_chunks(body: str) -> Iterator[Any]:
    """Yield the inner JSON object of every ``wrb.fr`` chunk in ``body``.

    Robust to single-chunk responses with no length headers (the older
    ``GetShoppingResults`` / ``GetCalendarGraph`` shape) — those are parsed
    by falling back to a single JSON load over the trimmed body.
    """
    text = body.lstrip().removeprefix(_PREFIX).lstrip()

    # Fast path: no length headers (legacy single-chunk responses).
    if not text or not text[0].isdigit():
        try:
            outer = json.loads(text)
        except (ValueError, json.JSONDecodeError):
            return
        for chunk in _chunks_from_outer(outer):
            yield chunk
        return

    # Chunked format: <len>\n<payload>\n<len>\n<payload>... where <len> is the
    # decimal byte length of the upcoming payload line.
    cursor = 0
    while cursor < len(text):
        # Read the digit prefix
        end = text.find("\n", cursor)
        if end == -1:
            break
        try:
            length = int(text[cursor:end])
        except ValueError:
            break
        cursor = end + 1
        payload = text[cursor : cursor + length]
        cursor += length
        # Trim a possible trailing newline between chunks.
        if cursor < len(text) and text[cursor] == "\n":
            cursor += 1
        try:
            outer = json.loads(payload)
        except (ValueError, json.JSONDecodeError):
            continue
        for chunk in _chunks_from_outer(outer):
            yield chunk


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
            continue


def parse_first_wrb_payload(body: str) -> Any:
    """Return the inner JSON of the first ``wrb.fr`` chunk, or None."""
    for chunk in iter_wrb_chunks(body):
        return chunk
    return None
