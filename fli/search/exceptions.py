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


class SearchBackendError(SearchClientError):
    """Google Flights answered HTTP 200 with an error envelope, not results.

    A rejected request comes back as ``HTTP 200`` carrying a payload-less
    ``wrb.fr`` row of the shape ``["wrb.fr", null, null, null, null,
    [code]]``. Without this error the response is indistinguishable from
    "this route genuinely has no flights".

    Richer rejections carry a status message and/or a ``google.rpc``-style
    detail block after the code, which is preserved verbatim (truncated) in
    ``error_detail`` — the code alone is often too coarse to debug with. An
    ``INTERNAL`` (13), for instance, can mean either "Google declined to
    serve this" or "a required request header was missing", and only the
    detail block tells the two apart.
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: int | None = None,
        error_detail: str | None = None,
    ):
        """Store the backend status code and detail alongside the message."""
        super().__init__(message)
        self.error_code = error_code
        self.error_detail = error_detail
