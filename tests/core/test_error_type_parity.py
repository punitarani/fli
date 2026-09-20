"""CLI `--format json` and MCP tools must agree on `error_type` for every exception.

T10 fix round 1, maintainer ruling V1: a review found
``fli.cli.errors.json_error_payload`` already emitted an ``error_type``
field for the same exceptions with a *different* vocabulary than the
MCP tools' first cut. Both now build on the single shared
:func:`fli.core.errors.classify_error` (see that module's docstring for
the full history and vocabulary table), which makes drift structurally
impossible — but only as long as neither interface stops using it. This
suite proves that by going through each interface's real production
entry point (:func:`fli.cli.errors.json_error_payload` and
:func:`fli.mcp.server._execute_flight_search`) rather than calling
``classify_error`` a second time, so it would catch either surface
silently reverting to its own hardcoded strings.

The ``SearchClientError`` subclass coverage reuses the same
"every subclass must be listed" guard as
``tests/core/test_errors.py::TestEverySearchClientErrorSubclassIsClassified``
— a new subclass shows up in the parametrize list automatically and fails
here until ``_INSTANCES`` is updated for it, same as it does there.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from fli.cli.errors import json_error_payload
from fli.core.parsers import ParseError
from fli.mcp.server import FlightSearchParams, _execute_flight_search
from fli.search.exceptions import (
    SearchClientError,
    SearchConnectionError,
    SearchHTTPError,
    SearchParseError,
    SearchRejectedError,
    SearchTimeoutError,
    SearchUnsupportedError,
)

PINNED_TODAY = "2026-01-01"


@pytest.fixture(autouse=True)
def _pinned_clock(pin_today):
    """Freeze "today" well before the departure date used below."""
    pin_today(PINNED_TODAY)


def _all_subclasses(cls: type) -> set[type]:
    """Recursively collect every currently-defined subclass of ``cls``."""
    seen: set[type] = set()
    stack = [cls]
    while stack:
        current = stack.pop()
        for sub in current.__subclasses__():
            if sub not in seen:
                seen.add(sub)
                stack.append(sub)
    return seen


def _pydantic_validation_error() -> ValidationError:
    class _Model(BaseModel):
        passengers: int

    try:
        _Model(passengers="not-a-number")
    except ValidationError as exc:
        return exc
    raise AssertionError("expected pydantic to raise ValidationError")  # pragma: no cover


# One representative instance per exception class that classify_error()
# handles — every SearchClientError subclass (+ its base) plus the other
# classes the shared classifier is documented to cover.
_INSTANCES: dict[type, BaseException] = {
    SearchClientError: SearchClientError("boom"),
    SearchTimeoutError: SearchTimeoutError("timed out"),
    SearchConnectionError: SearchConnectionError("no route"),
    SearchHTTPError: SearchHTTPError("bad response", status_code=500),
    SearchRejectedError: SearchRejectedError(13),
    SearchUnsupportedError: SearchUnsupportedError("multi-city"),
    SearchParseError: SearchParseError("no ds:1 payload"),
    ParseError: ParseError("unknown airport code 'ZZZ'"),
    ValueError: ValueError("bad date range"),
    ValidationError: _pydantic_validation_error(),
    Exception: Exception("totally unclassified"),
}


class TestEverySearchClientErrorSubclassHasAnInstance:
    """Guards against a new fli.search.exceptions class going untested here."""

    @pytest.mark.parametrize(
        "exc_class",
        sorted(_all_subclasses(SearchClientError) | {SearchClientError}, key=lambda c: c.__name__),
    )
    def test_class_has_instance(self, exc_class):
        assert exc_class in _INSTANCES, (
            f"{exc_class.__name__} is a SearchClientError subclass with no instance in "
            "tests/core/test_error_type_parity.py::_INSTANCES — add one so CLI/MCP "
            "error_type parity is verified for it too."
        )


@pytest.mark.parametrize("exc", list(_INSTANCES.values()), ids=[c.__name__ for c in _INSTANCES])
def test_cli_and_mcp_agree_on_error_type(exc, monkeypatch):
    """The CLI's json_error_payload and the MCP's error response must match."""
    # CLI side: the real json_error_payload entry point.
    _, cli_error_type, _ = json_error_payload(exc)

    # MCP side: the real _execute_flight_search entry point, with the
    # search client stubbed to raise the same exception instance.
    def _raise(self, *args, **kwargs):
        raise exc

    monkeypatch.setattr("fli.mcp.server.SearchFlights.search", _raise)
    params = FlightSearchParams(origin="JFK", destination="LHR", departure_date="2026-12-01")
    mcp_result = _execute_flight_search(params)

    assert mcp_result["success"] is False
    assert mcp_result["error_type"] == cli_error_type
