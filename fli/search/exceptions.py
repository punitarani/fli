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


class SearchRejectedError(SearchClientError):
    """Google answered HTTP 200 but declined to serve results.

    The response carries a ``wrb.fr`` row with no payload and an error
    code (13 = INTERNAL). Since 2026-08 ``GetShoppingResults`` requires an
    ``x-goog-batchexecute-bgr`` header signed by the page's own JavaScript
    over the exact request bytes, so a plain HTTP client always lands here.
    Without this error the caller saw an empty list and reported "no
    flights found", which is indistinguishable from a route with no service.
    """

    def __init__(self, code: int | None = None):
        """Record the numeric error code alongside the user-facing message."""
        self.code = code
        suffix = f" (error {code})" if code is not None else ""
        super().__init__(
            f"Google Flights declined the request{suffix} and returned no data. "
            "Its API now requires a browser-signed x-goog-batchexecute-bgr header, "
            "which this client cannot produce. See github.com/punitarani/fli#223."
        )


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
