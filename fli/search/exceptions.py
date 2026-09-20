"""Typed errors raised by the search client.

These exist so the CLI (and library consumers) can react to network
failures with a clear, user-facing message instead of a raw curl-cffi
traceback. They are intentionally light wrappers — the original
exception is kept as ``__cause__`` for logging.
"""

from __future__ import annotations


class SearchClientError(Exception):
    """Base class for errors talking to the Google Flights backend."""


class SearchTimeoutError(SearchClientError):
    """The request to Google Flights timed out before any data arrived."""


class SearchConnectionError(SearchClientError):
    """A network/DNS issue prevented us from reaching Google Flights."""


class SearchHTTPError(SearchClientError):
    """Google Flights returned a non-2xx HTTP response."""

    def __init__(self, message: str, *, status_code: int | None = None):
        """Store the HTTP status alongside the message for richer logging."""
        super().__init__(message)
        self.status_code = status_code


# Google reports a rejected request with gRPC's canonical status codes, so
# the bare number can be named instead of left for the reader to look up.
_GRPC_STATUS_NAMES = {
    0: "OK",
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


class SearchRejectedError(SearchClientError):
    """Google answered HTTP 200 but declined to serve results.

    The response carries a ``wrb.fr`` row with no payload and an error
    code (13 = INTERNAL). Since 2026-08 ``GetShoppingResults`` requires an
    ``x-goog-batchexecute-bgr`` header signed by the page's own JavaScript
    over the exact request bytes, so a plain HTTP client always lands here.
    Without this error the caller saw an empty list and reported "no
    flights found", which is indistinguishable from a route with no service.

    A richer rejection carries a status message and/or a ``google.rpc``-style
    detail block after the code, kept verbatim (truncated) in ``detail`` —
    the code alone is often too coarse to debug with. An ``INTERNAL`` (13),
    for instance, can mean either "Google declined to serve this" or "a
    required request header was missing", and only the detail tells the two
    apart.
    """

    def __init__(self, code: int | None = None, *, detail: str | None = None):
        """Record the status code, its gRPC name and any detail block."""
        self.code = code
        self.detail = detail
        self.status_name = _GRPC_STATUS_NAMES.get(code) if code is not None else None
        named = f"{code} ({self.status_name})" if self.status_name else code
        # ``0`` is gRPC's OK, so there is no error number to name — it reads
        # the same as no code at all rather than claiming "error 0".
        suffix = f" with error {named}" if code else ""
        message = (
            f"Google Flights declined the request{suffix} and returned no data. "
            "Its API now requires a browser-signed x-goog-batchexecute-bgr header, "
            "which this client cannot produce. See github.com/punitarani/fli#223."
        )
        if detail:
            message = f"{message} Details: {detail}"
        super().__init__(message)


class SearchUnsupportedError(SearchClientError):
    """The requested search cannot be served by the current transport.

    Distinct from an empty result: the query is well formed and Google
    would answer it in a browser, but the public search page carries no
    inline payload for it, so this client has nothing to read.
    """


class SearchParseError(SearchClientError):
    """A successful HTTP response could not be parsed into flights.

    Distinct from network / HTTP errors: this says "Google responded but
    the shape changed", not "Google didn't respond". In practice it is
    either a consent/blocked page (no ``ds:1`` blob at all) or a change in
    the flight rows themselves.

    It belongs to the :class:`SearchClientError` family so that callers
    already catching search failures — the CLI's error reporter among them
    — classify it as one instead of an unexpected crash.
    """
