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

T10 fix round 2, maintainer ruling U3: ``TestCliCommandAndMcpToolAgreeOnErrorType``
below extends this to the COMMAND level — a real ``CliRunner`` invocation
of ``fli flights`` / ``fli dates --format json`` compared against the
matching MCP tool executor for the same input. This is the layer where
round 1's parity test could not have caught U1 (the CLI commands'
``except (AttributeError, ValueError)`` blocks hardcoding
``error_type="search_error"`` independently of ``json_error_payload``,
which they never called for that branch).
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ValidationError
from typer.testing import CliRunner

from fli.cli.errors import json_error_payload
from fli.cli.main import app
from fli.core.parsers import ParseError
from fli.mcp.server import (
    DateSearchParams,
    FlightSearchParams,
    _execute_date_search,
    _execute_flight_search,
)
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
    cli_payload = json_error_payload(exc)

    # MCP side: the real _execute_flight_search entry point, with the
    # search client stubbed to raise the same exception instance.
    def _raise(self, *args, **kwargs):
        raise exc

    monkeypatch.setattr("fli.mcp.server.SearchFlights.search", _raise)
    params = FlightSearchParams(origin="JFK", destination="LHR", departure_date="2026-12-01")
    mcp_result = _execute_flight_search(params)

    assert mcp_result["success"] is False
    assert mcp_result["error_type"] == cli_payload.error_type
    assert mcp_result["retryable"] == cli_payload.retryable


class TestCliCommandAndMcpToolAgreeOnErrorType:
    """Command-level parity (U3): a real CliRunner invocation vs. the MCP executor.

    ``fli.mcp.server.SearchFlights`` / ``SearchDates`` and
    ``fli.cli.commands.flights`` / ``dates``' ``SearchFlights`` / ``SearchDates``
    are literally the same class objects (both re-exported from
    ``fli.search``), so patching ``fli.search.flights.SearchFlights.search``
    (or ``fli.search.dates.SearchDates.search``) affects both surfaces at
    once — no separate CLI-specific mock needed.
    """

    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_invalid_airport_code(self, runner):
        """Bad origin code: ParseError -> validation_error on both surfaces."""
        cli_result = runner.invoke(
            app, ["flights", "ZZZZ", "LHR", "2026-12-01", "--format", "json"]
        )
        cli_payload = json.loads(cli_result.stdout)

        mcp_result = _execute_flight_search(
            FlightSearchParams(origin="ZZZZ", destination="LHR", departure_date="2026-12-01")
        )

        assert cli_payload["success"] is False
        assert mcp_result["success"] is False
        assert cli_payload["error"]["type"] == mcp_result["error_type"] == "validation_error"
        assert cli_payload["error"]["retryable"] == mcp_result["retryable"] is False

    def test_date_range_over_93_day_cap(self, runner):
        """A >93-date range: bare ValueError -> validation_error on both surfaces.

        This is exactly the U1 regression: the CLI's dates command used to
        hardcode "search_error" for this bare ValueError while the MCP tool
        already said "validation_error" — the drift this whole task exists
        to prevent, and the one round 1's parity test (which only compared
        json_error_payload against the MCP executor, not the full CLI
        command) could not catch.
        """
        cli_result = runner.invoke(
            app,
            [
                "dates",
                "JFK",
                "LAX",
                "--from",
                "2026-02-01",
                "--to",
                "2026-12-01",
                "--format",
                "json",
            ],
        )
        cli_payload = json.loads(cli_result.stdout)

        mcp_result = _execute_date_search(
            DateSearchParams(
                origin="JFK", destination="LAX", start_date="2026-02-01", end_date="2026-12-01"
            )
        )

        assert cli_payload["success"] is False
        assert mcp_result["success"] is False
        assert cli_payload["error"]["type"] == mcp_result["error_type"] == "validation_error"
        assert cli_payload["error"]["retryable"] == mcp_result["retryable"] is False

    def test_invalid_passenger_mix(self, runner):
        """1 adult + 2 lap infants (each needs its own adult): pydantic ValidationError."""
        cli_result = runner.invoke(
            app,
            [
                "flights",
                "JFK",
                "LHR",
                "2026-12-01",
                "--passengers",
                "1",
                "--infants-on-lap",
                "2",
                "--format",
                "json",
            ],
        )
        cli_payload = json.loads(cli_result.stdout)

        mcp_result = _execute_flight_search(
            FlightSearchParams(
                origin="JFK",
                destination="LHR",
                departure_date="2026-12-01",
                passengers=1,
                infants_on_lap=2,
            )
        )

        assert cli_payload["success"] is False
        assert mcp_result["success"] is False
        assert cli_payload["error"]["type"] == mcp_result["error_type"] == "validation_error"
        assert cli_payload["error"]["retryable"] == mcp_result["retryable"] is False

    def test_stubbed_blocked_page(self, runner, monkeypatch):
        """SearchParseError (consent/blocked page): parse_error, not retryable as-is."""
        monkeypatch.setattr(
            "fli.search.flights.SearchFlights.search",
            lambda self, *a, **k: (_ for _ in ()).throw(
                SearchParseError("no ds:1 payload — consent/blocked page")
            ),
        )

        cli_result = runner.invoke(app, ["flights", "JFK", "LHR", "2026-12-01", "--format", "json"])
        cli_payload = json.loads(cli_result.stdout)

        mcp_result = _execute_flight_search(
            FlightSearchParams(origin="JFK", destination="LHR", departure_date="2026-12-01")
        )

        assert cli_payload["success"] is False
        assert mcp_result["success"] is False
        assert cli_payload["error"]["type"] == mcp_result["error_type"] == "parse_error"
        assert cli_payload["error"]["retryable"] == mcp_result["retryable"] is False

    def test_stubbed_connection_error(self, runner, monkeypatch):
        """SearchConnectionError: connection_error, retryable — a released CLI value."""
        monkeypatch.setattr(
            "fli.search.flights.SearchFlights.search",
            lambda self, *a, **k: (_ for _ in ()).throw(
                SearchConnectionError("Could not reach Google Flights")
            ),
        )

        cli_result = runner.invoke(app, ["flights", "JFK", "LHR", "2026-12-01", "--format", "json"])
        cli_payload = json.loads(cli_result.stdout)

        mcp_result = _execute_flight_search(
            FlightSearchParams(origin="JFK", destination="LHR", departure_date="2026-12-01")
        )

        assert cli_payload["success"] is False
        assert mcp_result["success"] is False
        assert cli_payload["error"]["type"] == mcp_result["error_type"] == "connection_error"
        assert cli_payload["error"]["retryable"] == mcp_result["retryable"] is True
