"""Machine-readable error classification for MCP tool responses.

Before this module, an MCP client (an AI assistant driving the tools) had
no way to react to a failed `search_flights` / `search_dates` /
`get_booking_options` / `find_airports` call other than string-matching the
free-text `error` field — brittle, and liable to break the moment the
message wording changes. This module gives every MCP error response a
stable `error_type` string plus an honest `retryable` flag, computed from
the exception's **type**, never from its message text.

Design lineage: PR #164 (github.com/punitarani/fli/pull/164, @piersonrazzi)
introduced the `error_type` field and its original vocabulary
(`parse_error`, `certificate_error`, `connection_error`, `http_error`,
`search_error`, `unexpected_error`). That branch also bundled CA-bundle
support, which is out of scope here and stays in #164. PR #208
(github.com/punitarani/fli/pull/208, @bjgross10767) reached for a
structured `code` field and a `retryable`-style retry hint; its diagnosis
(labelling the deterministic `SearchRejectedError` gate as "rate limited",
suggesting a 30s retry) was wrong — that gate is not rate limiting, it is
a permanent transport limitation (see `SearchRejectedError`'s docstring) —
so its code is not reused, but its captured error-13 envelope fixture is
(see `tests/search/fixtures/flight_search_error13_rejected.txt` and
`tests/search/test_error_envelope_fixture.py`).

This module lives under `fli.mcp` (not `fli.core`) deliberately: `fli.core`
is documented (see `fli/core/links.py`) to stay free of any dependency on
`fli.search`, and classification necessarily depends on the exception
types defined in `fli.search.exceptions`. `fli.cli.errors` is the CLI's
analogous, independently-evolved module — the two are not unified because
the two interfaces' vocabularies differ (this one adds `retryable` /
`http_status` and gives `SearchUnsupportedError` its own bucket instead of
folding it into `parse_error`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from fli.search.exceptions import (
    SearchClientError,
    SearchConnectionError,
    SearchHTTPError,
    SearchParseError,
    SearchRejectedError,
    SearchTimeoutError,
    SearchUnsupportedError,
)

# Vocabulary reference (kept here so it is easy to grep alongside the
# classification logic below; also documented in CLAUDE.md and
# docs/guides/mcp.md for MCP callers who don't read the source):
#
# | error_type        | retryable          | raised for                              |
# |-------------------|---------------------|------------------------------------------|
# | validation_error  | false               | bad parameters, pydantic ValidationError, |
# |                   |                     | fli.core.parsers.ParseError, bare         |
# |                   |                     | ValueError (e.g. the 93-date cap)         |
# | unsupported_error | false               | SearchUnsupportedError (e.g. multi-city)  |
# | blocked_error     | false               | SearchParseError (page served without     |
# |                   |                     | results: consent/blocked page — see       |
# |                   |                     | FLI_SOCS_COOKIE)                          |
# | rejected_error    | false               | SearchRejectedError (Google refused the   |
# |                   |                     | RPC, e.g. booking options)                |
# | timeout_error     | true                | SearchTimeoutError                        |
# | connection_error  | true                | SearchConnectionError                     |
# | http_error        | true iff 429 or 5xx | SearchHTTPError (status in `http_status`) |
# | search_error      | false               | any other SearchClientError               |
# | unexpected_error  | false               | anything else (a bug, not a known type)   |
_RETRYABLE_HTTP_STATUSES = {429}


@dataclass(frozen=True)
class ErrorClassification:
    """Stable, machine-readable shape describing why an MCP call failed."""

    error_type: str
    retryable: bool
    http_status: int | None = None

    def as_fields(self) -> dict[str, Any]:
        """Return the dict fields to splice into an MCP error response.

        `http_status` is only included when known (i.e. for `http_error`
        responses where the upstream status code was captured), so every
        other response shape stays exactly as additive as `error_type` /
        `retryable` themselves — no caller sees a new key it can't explain.
        """
        fields: dict[str, Any] = {"error_type": self.error_type, "retryable": self.retryable}
        if self.http_status is not None:
            fields["http_status"] = self.http_status
        return fields


def classify_error(exc: BaseException) -> ErrorClassification:
    """Classify ``exc`` into a stable ``error_type`` + ``retryable`` pair.

    Checks run most-specific-subclass first, purely by exception `type`
    (never by message text — wording is free to change without breaking
    callers that key off `error_type`). See the module docstring for the
    full vocabulary table and the design rationale behind each bucket.
    """
    if isinstance(exc, SearchTimeoutError):
        return ErrorClassification("timeout_error", retryable=True)
    if isinstance(exc, SearchConnectionError):
        return ErrorClassification("connection_error", retryable=True)
    if isinstance(exc, SearchHTTPError):
        status = exc.status_code
        retryable = status is not None and (status in _RETRYABLE_HTTP_STATUSES or status >= 500)
        return ErrorClassification("http_error", retryable=retryable, http_status=status)
    if isinstance(exc, SearchRejectedError):
        # Google answered but declined the RPC outright (e.g. booking
        # options without a browser-signed header). Deterministic for a
        # plain HTTP client — retrying the same request will not help.
        return ErrorClassification("rejected_error", retryable=False)
    if isinstance(exc, SearchUnsupportedError):
        # The query is well formed but this transport has no path to
        # answer it (e.g. multi-city). Retrying will not help; the
        # request itself needs to change.
        return ErrorClassification("unsupported_error", retryable=False)
    if isinstance(exc, SearchParseError):
        # A page arrived but couldn't be read — most often a regional
        # consent/blocked interstitial. Not retryable *as-is*: the caller
        # needs to set FLI_SOCS_COOKIE (EU/EEA consent) or otherwise
        # change the request, not just retry the same one.
        return ErrorClassification("blocked_error", retryable=False)
    if isinstance(exc, SearchClientError):
        # Catch-all for any other/future SearchClientError subclass that
        # doesn't have a more specific bucket above yet. Deterministic
        # until proven otherwise.
        return ErrorClassification("search_error", retryable=False)
    if isinstance(exc, ValidationError | ValueError):
        # Covers pydantic ValidationError, fli.core.parsers.ParseError
        # (a ValueError subclass used for bad airport/airline/etc. input),
        # and bare ValueError — notably the 93-date-per-search cap raised
        # by SearchDates.search(). All three mean "the request itself is
        # invalid", which the caller must fix before retrying, so they
        # share validation_error/not-retryable.
        return ErrorClassification("validation_error", retryable=False)
    return ErrorClassification("unexpected_error", retryable=False)
