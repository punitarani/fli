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
Since the flight/date searches moved to the public page transport
(:mod:`fli.search._tfs`), `SearchFlights.get_booking_options` is the only
live consumer of this module.

Important quirk: the length headers are **not** a dependable frame
delimiter. They count the chunk plus its two surrounding newlines, but in
characters rather than UTF-8 bytes, so any response carrying non-ASCII text
(accented airport or airline names) desynchronises a byte-oriented reader —
and an ASCII response hides the difference entirely. Rather than encode a
guess about Google's convention, this reader ignores the announced length
and lets the JSON grammar delimit each chunk, which is correct either way.
The headers' *positions* are still used — to re-synchronise after a
malformed chunk, and to bound each decode to one chunk's worth of text —
but their values never are.

This module centralises that reader and exposes :func:`iter_wrb_chunks` which
yields the decoded inner JSON of each ``wrb.fr`` chunk.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from typing import Any, NamedTuple

from fli.search.exceptions import _GRPC_STATUS_NAMES, SearchRejectedError

logger = logging.getLogger(__name__)

_PREFIX = ")]}'"

# Framing noise between two chunks: the length header and the newlines
# around it. Skipped wholesale — the header's value is never trusted.
_FRAMING_CHARS = "0123456789 \t\r\n"

# A chunk boundary in the raw stream: line break, decimal length header,
# line break, then the "[" that opens the next chunk. CRLF is accepted so
# a CRLF-framed body gets the same bounded decode as an LF-framed one —
# but only as the trailing ``\r?``. A CRLF ends in "\n", so anchoring the
# pattern on a literal "\n" still matches "\r\n<digits>\r\n[" (one
# character later, which only leaves the "\r" in the window as trailing
# whitespace the decoder ignores) while keeping the engine's literal-prefix
# scan. Spelling the first break "\r?\n" instead costs it: a 20 MB body
# went from 61 ms to 172 ms purely on that.
#
# This pattern cannot occur inside a well-formed JSON document, so the
# next match is always at or after the current chunk's end. CR and LF are
# both illegal unescaped inside a JSON string, so the digits would have to
# be a number token surrounded by whitespace — and a number followed by
# "[" with only whitespace between them is not valid JSON in any container
# (an array needs a comma, an object a comma or colon, and a top-level
# document ends after its one value). That makes the match position a safe
# upper bound for where the current chunk ends, which is what lets the
# decode below work on a bounded window. Only the header's *position* is
# used; its value is still never trusted.
# ``TestChunkBoundaryCannotSplitAValue`` enumerates the claim.
_CHUNK_BOUNDARY = re.compile(r"\n\d+\r?\n(?=\[)")

# Error details are echoed into the exception message, so cap them.
_MAX_DETAIL_CHARS = 200

# A body of nothing but bad chunks would otherwise emit one warning per
# chunk. Warn on the first few, then say how many there were in total.
_MAX_MALFORMED_WARNINGS = 5

# Row kinds emitted by :func:`_rows_from_outer`.
_ROW_CHUNK = "chunk"
_ROW_ERROR = "error"


class _RejectionStatus(NamedTuple):
    """A rejection reported by an error-envelope ``wrb.fr`` row."""

    code: int
    detail: str | None


def iter_wrb_chunks(body: str | bytes) -> Iterator[Any]:
    """Yield the inner JSON object of every ``wrb.fr`` chunk in ``body``.

    Robust to single-chunk responses with no length headers (the older
    ``GetShoppingResults`` / ``GetCalendarGraph`` shape) — those parse the
    same way, since chunk boundaries are derived from the JSON itself.

    A response may mix payload chunks and an error row, and where the error
    sits decides what happens:

    * an error row reached **before** any usable chunk means the request
      itself was rejected, so it raises immediately — handing the caller
      the chunks behind it would pass off a partial answer as a whole one;
    * an error row **trailing** chunks that already parsed keeps those
      chunks and logs the rejection, so the outcome does not depend on how
      far the caller happens to drain the generator.

    Nothing else escapes: a chunk that cannot be decoded — malformed,
    truncated or nested past the decoder's recursion limit — is skipped
    with a warning.

    Raises:
        SearchRejectedError: If Google answered with an error envelope
            before any usable chunk. See :func:`_error_status`.

    """
    # ``errors="replace"`` keeps a corrupted transfer from raising here;
    # the resulting chunk simply fails to parse and is reported below.
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body

    text = text.lstrip()
    if text.startswith(_PREFIX):
        text = text[len(_PREFIX) :]
    text = text.lstrip()

    decoder = json.JSONDecoder()
    trailing: list[_RejectionStatus] = []
    malformed = 0
    yielded = 0
    cursor = 0
    size = len(text)
    # Lookahead and window state, carried across chunks on purpose — see below.
    boundary: re.Match[str] | None = None
    no_more_boundaries = False
    region = text
    region_start = 0
    while cursor < size:
        while cursor < size and text[cursor] in _FRAMING_CHARS:
            cursor += 1
        if cursor >= size:
            break

        # Decode within the region ending at the next boundary rather than
        # over the whole body. A failed decode builds a ``JSONDecodeError``,
        # and that constructor counts the newlines before the error position
        # — O(offset) over whatever string it was handed. Passing the full
        # body made a stream of bad chunks quadratic; a bounded region keeps
        # every failure proportional to the region, and a failure jumps
        # straight to the region's end, so there is at most one per region.
        #
        # Both the lookahead and the slice are computed per REGION, not per
        # chunk, and that is what keeps this linear:
        #
        # * the search is cached because boundaries only move forward. A
        #   match found for an earlier cursor is still the next one until the
        #   cursor passes it (there can be nothing between them, or the
        #   search would have returned that instead), and once a search comes
        #   back empty there is nothing ahead to find again. Without both, a
        #   body with no boundary at all — CRLF framing, or chunks written
        #   back to back with no headers — pays a scan to the end of the
        #   document once per chunk.
        # * the slice is cached with it, and the cursor is translated into
        #   it, because re-slicing ``text[cursor:boundary.start()]`` per
        #   chunk copies the whole remaining region every time. With one
        #   boundary at the end of an 80k-chunk body that came to ~105 GB of
        #   copying, 1.6 s against 81 ms for the reader that never sliced.
        #
        # Both hazards are invisible on the shape Google actually sends,
        # where every chunk has a boundary right behind it and the region is
        # one chunk long.
        if not no_more_boundaries and (boundary is None or boundary.start() < cursor):
            boundary = _CHUNK_BOUNDARY.search(text, cursor)
            no_more_boundaries = boundary is None
            if boundary is None:
                region, region_start = text, 0
            else:
                region, region_start = text[cursor : boundary.start()], cursor

        try:
            outer, consumed = decoder.raw_decode(region, cursor - region_start)
        except (ValueError, RecursionError) as exc:
            # ``RecursionError`` is a ``RuntimeError``: deeply nested input
            # would otherwise escape the generator entirely.
            malformed += 1
            if malformed <= _MAX_MALFORMED_WARNINGS:
                logger.warning("Discarding malformed wrb.fr chunk: %s", exc)
                logger.debug("malformed wrb.fr chunk", exc_info=True)
            if boundary is None:
                break
            cursor = boundary.end()
            continue
        cursor = region_start + consumed

        for kind, value in _rows_from_outer(outer):
            if kind is _ROW_ERROR:
                if not yielded:
                    raise _rejection(value)
                trailing.append(value)
                continue
            yielded += 1
            yield value

    if malformed > _MAX_MALFORMED_WARNINGS:
        logger.warning("Discarded %d malformed wrb.fr chunks in total", malformed)

    if trailing:
        status = trailing[0]
        logger.warning(
            "Google Flights reported error %d (%s) alongside %d usable chunk(s); "
            "keeping the partial payload",
            status.code,
            status.detail or _GRPC_STATUS_NAMES.get(status.code) or "unknown",
            yielded,
        )


def _rejection(status: _RejectionStatus) -> SearchRejectedError:
    """Build the exception describing a rejected request."""
    return SearchRejectedError(status.code, detail=status.detail)


def _error_status(row: list[Any]) -> _RejectionStatus | None:
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
    return _RejectionStatus(code, _error_detail(status))


def _error_detail(status: list[Any]) -> str | None:
    """Summarise the message and detail block trailing a status code.

    Every part of this is Google-controlled text of unbounded length, and
    it ends up in the exception message, in a warning record and — via the
    CLI's error reporter — in a file under ``~/.fli/logs``. Both halves are
    capped, and so is the join, so nothing downstream has to defend itself.
    """
    parts: list[str] = []
    message = status[1] if len(status) > 1 else None
    if isinstance(message, str) and message:
        parts.append(_truncate(message))
    details = status[2] if len(status) > 2 else None
    if details:
        parts.append(_compact(details))
    return _truncate("; ".join(parts)) or None


def _truncate(text: str) -> str:
    """Cap ``text`` at :data:`_MAX_DETAIL_CHARS`, marking the cut with an ellipsis."""
    if len(text) > _MAX_DETAIL_CHARS:
        return text[: _MAX_DETAIL_CHARS - 1] + "…"
    return text


def _compact(value: Any) -> str:
    """Render a decoded JSON value as a compact, length-capped string."""
    try:
        text = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError):  # pragma: no cover - values come from json.loads
        text = repr(value)
    return _truncate(text)


def _rows_from_outer(outer: Any) -> Iterator[tuple[str, Any]]:
    """Yield a top-level chunk list's rows in order, tagged by kind.

    Emits ``(_ROW_CHUNK, payload)`` for a decoded inner payload and
    ``(_ROW_ERROR, status)`` for an error envelope. The caller needs the
    original order to tell a rejection from a trailing error, so the two
    cannot be collected separately.
    """
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
                yield _ROW_ERROR, status
            continue
        try:
            payload = json.loads(inner)
        except (ValueError, RecursionError) as exc:
            # ``RecursionError`` for pathologically nested inner JSON; it is
            # a ``RuntimeError``, so ``ValueError`` alone would let it out.
            logger.warning("Failed to decode wrb.fr inner JSON payload: %s", exc)
            logger.debug("wrb.fr inner JSON decode failed", exc_info=True)
            continue
        yield _ROW_CHUNK, payload


def parse_first_wrb_payload(body: str | bytes) -> Any:
    """Return the inner JSON of the first ``wrb.fr`` chunk, or None.

    An error row trailing a usable chunk never raises: the first chunk is
    returned and the generator is abandoned. See :func:`iter_wrb_chunks`.

    Raises:
        SearchRejectedError: If Google answered with an error envelope and
            no usable chunk at all.

    """
    for chunk in iter_wrb_chunks(body):
        return chunk
    return None
