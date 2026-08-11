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
from typing import Any, NamedTuple

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

# Error details are echoed into the exception message, so cap them.
_MAX_DETAIL_CHARS = 200


class _BackendStatus(NamedTuple):
    """A rejection reported by an error-envelope ``wrb.fr`` row."""

    code: int
    detail: str | None


def iter_wrb_chunks(body: str | bytes) -> Iterator[Any]:
    """Yield the inner JSON object of every ``wrb.fr`` chunk in ``body``.

    Robust to single-chunk responses with no length headers (the older
    ``GetShoppingResults`` / ``GetCalendarGraph`` shape) — those parse the
    same way, since chunk boundaries are derived from the JSON itself.

    A response may mix payload chunks and an error row. Raising the moment
    the error row is read would make the outcome depend on how far the
    caller drains the generator: a caller taking only the first chunk would
    never see an error that trails it, while a caller draining fully would
    lose every chunk it had already accumulated to the exception. So an
    error is recorded and only raised once the body is exhausted without a
    single chunk — whatever Google did send is always delivered.

    Raises:
        SearchBackendError: If Google answered with an error envelope and no
            usable chunk at all. See :func:`_error_status`.

    """
    # ``errors="replace"`` keeps a corrupted transfer from raising here;
    # the resulting chunk simply fails to parse and is reported below.
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body

    text = text.lstrip()
    if text.startswith(_PREFIX):
        text = text[len(_PREFIX) :]
    text = text.lstrip()

    decoder = json.JSONDecoder()
    errors: list[_BackendStatus] = []
    yielded = 0
    cursor = 0
    while cursor < len(text):
        while cursor < len(text) and text[cursor] in _FRAMING_CHARS:
            cursor += 1
        if cursor >= len(text):
            break
        try:
            outer, cursor = decoder.raw_decode(text, cursor)
        except ValueError:
            logger.warning("Discarding malformed wrb.fr chunk", exc_info=True)
            boundary = _CHUNK_BOUNDARY.search(text, cursor)
            if boundary is None:
                break
            cursor = boundary.end()
            continue
        for chunk in _chunks_from_outer(outer, errors):
            yielded += 1
            yield chunk

    if not errors:
        return
    if not yielded:
        raise _backend_error(errors[0])
    logger.warning(
        "Google Flights reported error %d (%s) alongside %d usable chunk(s); "
        "keeping the partial payload",
        errors[0].code,
        errors[0].detail or _STATUS_NAMES.get(errors[0].code, "unknown"),
        yielded,
    )


def _error_status(row: list[Any]) -> _BackendStatus | None:
    """Return the status of an error-envelope ``wrb.fr`` row, if any.

    Google reports a rejected request with ``HTTP 200`` and a payload-less
    row of the shape ``["wrb.fr", null, null, null, null, [code]]``, e.g.
    ``3`` (``INVALID_ARGUMENT``) for a payload it cannot decode or ``13``
    (``INTERNAL``) for a request it declines to serve. The status may carry
    a message and a ``google.rpc``-style detail block after the code::

        [13, null, [["type.googleapis.com/…ErrorResponse", [[…, "<req-id>"], 0]]]]

    Only a strictly positive integer code counts as a rejection: ``0`` is
    gRPC's ``OK`` and would otherwise raise a spurious "error 0", and
    ``bool`` is excluded because it is a subclass of ``int``.
    """
    if len(row) < 6:
        return None
    status = row[5]
    if not isinstance(status, list) or not status:
        return None
    code = status[0]
    if isinstance(code, bool) or not isinstance(code, int) or code <= 0:
        return None
    return _BackendStatus(code, _error_detail(status))


def _error_detail(status: list[Any]) -> str | None:
    """Summarise the message and detail block trailing a status code."""
    parts: list[str] = []
    message = status[1] if len(status) > 1 else None
    if isinstance(message, str) and message:
        parts.append(message)
    details = status[2] if len(status) > 2 else None
    if details:
        parts.append(_compact(details))
    return "; ".join(parts) or None


def _compact(value: Any) -> str:
    """Render a decoded JSON value as a compact, length-capped string."""
    try:
        text = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError):  # pragma: no cover - values come from json.loads
        text = repr(value)
    if len(text) > _MAX_DETAIL_CHARS:
        text = text[: _MAX_DETAIL_CHARS - 1] + "…"
    return text


def _backend_error(status: _BackendStatus) -> SearchBackendError:
    """Build the exception describing a backend rejection."""
    name = _STATUS_NAMES.get(status.code)
    code_text = f"{status.code} ({name})" if name else str(status.code)
    message = f"Google Flights returned error {code_text} instead of results"
    if status.detail:
        message = f"{message}: {status.detail}"
    return SearchBackendError(message, error_code=status.code, error_detail=status.detail)


def _chunks_from_outer(outer: Any, errors: list[_BackendStatus]) -> Iterator[Any]:
    """Yield a top-level chunk list's payloads, recording rejections into ``errors``."""
    if not isinstance(outer, list):
        return
    for row in outer:
        if not isinstance(row, list) or len(row) < 3:
            continue
        if row[0] != "wrb.fr":
            continue
        inner = row[2]
        if not isinstance(inner, str) or not inner:
            status = _error_status(row)
            if status is not None:
                errors.append(status)
            continue
        try:
            yield json.loads(inner)
        except (ValueError, json.JSONDecodeError):
            logger.warning("Failed to decode wrb.fr inner JSON payload", exc_info=True)
            continue


def parse_first_wrb_payload(body: str | bytes) -> Any:
    """Return the inner JSON of the first ``wrb.fr`` chunk, or None.

    An error row trailing a usable chunk never raises: the first chunk is
    returned and the generator is abandoned. See :func:`iter_wrb_chunks`.

    Raises:
        SearchBackendError: If Google answered with an error envelope and no
            usable chunk at all.

    """
    for chunk in iter_wrb_chunks(body):
        return chunk
    return None
