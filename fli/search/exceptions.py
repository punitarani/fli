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
    """Google Flights answered HTTP 200 with a typed ``ErrorResponse`` envelope.

    The FlightsFrontendService intermittently returns a gRPC error (e.g.
    ``INTERNAL`` / status 13) instead of results, while still using a 200
    status code — so the HTTP layer can't see it. Before this was detected
    the response decoded to an empty result and a transient Google-side
    outage looked like "no flights found" (issue #200).

    ``code`` is the canonical gRPC status from the envelope. Transient
    server-side codes are retried by the client; codes that signal a bad
    request (the ``NON_RETRYABLE`` set below) are surfaced immediately so
    we don't hammer Google with a request it will always reject.
    """

    # Canonical gRPC codes that mean "the request itself is wrong" — no
    # amount of retrying will help, so fail fast. Everything else
    # (INTERNAL, UNAVAILABLE, unknown, ...) is treated as transient.
    NON_RETRYABLE: frozenset[int] = frozenset(
        {
            3,  # INVALID_ARGUMENT
            5,  # NOT_FOUND
            7,  # PERMISSION_DENIED
            9,  # FAILED_PRECONDITION
            11,  # OUT_OF_RANGE
            16,  # UNAUTHENTICATED
        }
    )

    def __init__(self, message: str, *, code: int | None = None):
        """Store the gRPC status code alongside the message."""
        super().__init__(message)
        self.code = code

    @property
    def retryable(self) -> bool:
        """Whether this error is worth retrying (transient server-side fault)."""
        return self.code not in self.NON_RETRYABLE
