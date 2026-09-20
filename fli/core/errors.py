"""Shared error-formatting and error-classification utilities.

Two related jobs live here, both shared verbatim between the CLI and the
MCP interfaces so the two surfaces can never drift apart:

1. ``format_validation_error`` flattens pydantic's multi-line
   ``ValidationError`` dump into one actionable line.
2. ``classify_error`` maps any exception a search can raise into a stable,
   machine-readable ``(error_type, retryable[, http_status])`` triple.

Design note on (2) — why this lives in ``fli.core`` and not ``fli.mcp`` or
``fli.cli``: a review of the first cut of this classifier found that
``fli.cli.errors.json_error_payload`` already emitted a field literally
named ``error_type`` for the same exceptions, with a *different* string
for some of them (``"timeout"`` shipped in the CLI since v0.9.0 vs.
``"timeout_error"`` in the first MCP-only cut). Two vocabularies under one
field name is a trap for anyone building against both surfaces. The fix is
one classifier, used by both ``fli.mcp.server`` and
``fli.cli.errors.json_error_payload`` — which means it cannot live in
either interface package. This is a deliberate, narrow exception to the
general rule (see ``fli/core/links.py``) that ``fli.core`` stays free of a
dependency on ``fli.search``: unlike ``with_locale_params``,
``classify_error`` has no way to exist without knowing the
``fli.search.exceptions`` type hierarchy, and duplicating it per interface
is exactly what caused the drift this module now prevents.

**Vocabulary.** Released values (shipped in the CLI's ``--format json``
error output before this module existed) are a contract and were kept
as-is: ``"timeout"``, ``"connection_error"``, ``"http_error"``,
``"search_error"``, ``"unexpected_error"``. Everything else was free to
pick: ``"parse_error"`` (not ``"blocked_error"``) matches what the CLI and
PR #164 already independently converged on, and names *what happened*
(a page arrived but couldn't be read) rather than asserting *why*
(usually, but not always, a consent/blocked interstitial — see
``FLI_SOCS_COOKIE`` below). ``"rejected_error"``, ``"unsupported_error"``
and ``"validation_error"`` are new additions both surfaces now share.

- ``validation_error`` (not retryable): bad parameters — pydantic
  ``ValidationError``, ``fli.core.parsers.ParseError``, or a bare
  ``ValueError`` (e.g. the 93-date search-range cap).
- ``unsupported_error`` (not retryable): ``SearchUnsupportedError``, e.g.
  multi-city.
- ``parse_error`` (not retryable as-is): ``SearchParseError`` — a page
  arrived but couldn't be read, usually a regional consent/blocked
  interstitial. Set ``FLI_SOCS_COOKIE`` (EU/EEA) and retry; don't just
  retry the same request unchanged.
- ``rejected_error`` (not retryable): ``SearchRejectedError`` — Google
  refused the RPC outright (e.g. booking options); deterministic,
  retrying will not help.
- ``timeout`` (retryable): ``SearchTimeoutError``.
- ``connection_error`` (retryable): ``SearchConnectionError``.
- ``http_error`` (retryable iff ``http_status`` is 429 or 5xx):
  ``SearchHTTPError``, with the status in ``http_status`` when known.
- ``search_error`` (not retryable): any other ``SearchClientError``.
- ``unexpected_error`` (not retryable): anything else — a bug, not a
  known failure mode.

**Retry guidance for ``retryable: true``.** Both the CLI's HTTP client and
the search layer it wraps have *already* retried internally with backoff
before ever raising — see ``fli/search/client.py``'s ``tenacity`` retry
decorator. A caller (human or agent) that sees ``retryable: true`` should
retry **at most once or twice more**, with its own exponential backoff
measured in seconds (not milliseconds) between attempts — not hammer the
endpoint immediately. For ``http_error`` with ``http_status: 429``
specifically, that status *is* Google explicitly saying "slow down":
back off more, not less.
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

_RETRYABLE_HTTP_STATUSES = {429}


def format_validation_error(exc: ValidationError) -> str:
    """Flatten a pydantic ``ValidationError`` into one actionable message.

    The underlying validators already say exactly what is wrong (e.g. "Total
    passengers must be between 1 and 9"); without this, callers only ever saw
    a multi-line pydantic dump, which gives nothing to act on.
    """
    problems = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "input"
        problems.append(f"{location}: {error['msg']}")
    return f"Invalid parameter value - {'; '.join(problems)}"


@dataclass(frozen=True)
class ErrorClassification:
    """Stable, machine-readable shape describing why a search call failed."""

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

    Checks run most-specific-subclass first, purely by exception **type**
    (never by message text — wording is free to change without breaking
    callers that key off `error_type`). See the module docstring for the
    full vocabulary table, the CLI/MCP-parity rationale, and retry guidance.
    """
    if isinstance(exc, SearchTimeoutError):
        return ErrorClassification("timeout", retryable=True)
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
        return ErrorClassification("parse_error", retryable=False)
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
