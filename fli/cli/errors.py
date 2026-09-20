"""CLI error reporting helpers.

Turns ugly tracebacks into a one-line message for the user plus a
self-contained log file under ~/.fli/logs/ that captures the full
traceback for debugging.
"""

from __future__ import annotations

import logging
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import typer

from fli.cli.console import console
from fli.core.errors import classify_error
from fli.search.exceptions import (
    SearchClientError,
    SearchConnectionError,
    SearchHTTPError,
    SearchParseError,
    SearchRejectedError,
    SearchTimeoutError,
)

_LOG_DIR = Path.home() / ".fli" / "logs"
_logger = logging.getLogger("fli")


def _friendly_message(exc: BaseException) -> str:
    """Return the short, user-facing message for ``exc``."""
    if isinstance(exc, SearchTimeoutError):
        return f"Request timed out. {exc}"
    if isinstance(exc, SearchConnectionError):
        return f"Network error. {exc}"
    if isinstance(exc, SearchHTTPError):
        return f"Google Flights error. {exc}"
    if isinstance(exc, SearchRejectedError):
        return f"Google Flights declined the request. {exc}"
    if isinstance(exc, SearchParseError):
        return (
            f"Could not read Google Flights' response. {exc} "
            "This is usually a transient page variant or a regional consent "
            "interstitial — retry, or set FLI_SOCS_COOKIE if you are in the EU/EEA."
        )
    if isinstance(exc, SearchClientError):
        return f"Search failed. {exc}"
    return f"Unexpected error: {exc.__class__.__name__}: {exc}"


def _write_log(exc: BaseException, *, command: str | None = None) -> Path:
    """Write the full traceback for ``exc`` to a log file and return the path."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    # Microsecond precision so rapid-fire errors (e.g. tests, parallel
    # legs) don't collide on the same filename and silently overwrite.
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    log_path = _LOG_DIR / f"fli-error-{timestamp}.log"

    lines: list[str] = []
    lines.append(f"timestamp: {datetime.now(timezone.utc).isoformat()}")
    if command:
        lines.append(f"command: {command}")
    lines.append(f"argv: {sys.argv}")
    lines.append(f"error_type: {exc.__class__.__module__}.{exc.__class__.__name__}")
    lines.append(f"error_message: {exc}")
    lines.append("")
    lines.append("traceback:")
    lines.append("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))

    log_path.write_text("\n".join(lines), encoding="utf-8")
    return log_path


def report_cli_error(
    exc: BaseException,
    *,
    command: str | None = None,
    exit_code: int = 1,
) -> typer.Exit:
    """Print a clean message for ``exc``, write a log file, and return a ``typer.Exit``.

    Callers should ``raise`` the returned :class:`typer.Exit` so typer
    handles the exit code (and the original exception is suppressed from
    the user's terminal).
    """
    log_path = _write_log(exc, command=command)
    message = _friendly_message(exc)

    console.print(f"[red]Error:[/red] {message}")
    console.print(f"[dim]Full traceback written to {log_path}[/dim]")

    # Still log at debug for anyone who wired up python logging.
    _logger.debug("CLI error", exc_info=exc)

    return typer.Exit(exit_code)


@dataclass(frozen=True)
class JsonErrorPayload:
    """Everything a CLI ``--format json`` error path needs, from one classification.

    A named structure (rather than a positional tuple) on purpose: T10 fix
    round 2 added ``retryable``/``http_status`` alongside the original
    ``message``/``error_type``/``log_path`` triple, and a wider tuple would
    have made every call site's unpacking order a silent trap. Use
    attribute access (``payload.error_type``, ...) at call sites.
    """

    message: str
    error_type: str
    retryable: bool
    http_status: int | None
    log_path: Path


def json_error_payload(exc: BaseException, *, command: str | None = None) -> JsonErrorPayload:
    """Return the classified JSON-mode error payload for ``exc``.

    ``error_type`` (and, since T10 fix round 2, ``retryable``/``http_status``)
    come from the shared :func:`fli.core.errors.classify_error` classifier —
    the same one ``fli.mcp.server`` uses for MCP tool error responses — so a
    CLI ``--format json`` error and an MCP error for the same exception
    always agree. See that module's docstring for the full vocabulary table
    and retry guidance.

    The message formatting is unchanged from before this classifier existed:
    ``str(exc)`` for any :class:`SearchClientError`, and
    ``f"{type}: {exc}"`` for anything else — only ``error_type`` itself was
    ever hand-rolled here, and it has moved to the shared classifier.
    """
    log_path = _write_log(exc, command=command)
    classification = classify_error(exc)
    message = str(exc) if isinstance(exc, SearchClientError) else f"{exc.__class__.__name__}: {exc}"
    return JsonErrorPayload(
        message=message,
        error_type=classification.error_type,
        retryable=classification.retryable,
        http_status=classification.http_status,
        log_path=log_path,
    )
