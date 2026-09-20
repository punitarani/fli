"""CLI parsing tests for ``fli flights --top-n`` (issue #142).

``--top-n`` controls how many outbound options a round-trip search expands
into return-flight combinations; the default sort otherwise only ever
expands the cheapest 5 outbounds, which are often all the same carrier.
It only matters for round trips: left at its Typer default it is silently
ignored on a one-way search, but explicitly set on a one-way search it is a
clear, single-line error.

These tests mock ``SearchFlights`` (via the shared ``mock_search_flights``
fixture) for the "value reaches search()" and "echoed in JSON query"
assertions, and fall back to the *real* ``SearchFlights.search`` (with only
``_fetch_flights`` stubbed, never actually reached) for the bounds-rejection
assertions — the point of those is that the shared
``fli.core.errors.classify_error`` bound-check ``ValueError`` from
``fli/search/flights.py`` is what the CLI's ``--format json`` path surfaces,
not a mocked stand-in that would never raise it.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from typer.testing import CliRunner

from fli.cli.main import app
from fli.search.flights import SearchFlights


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _future(days: int) -> str:
    """Return a YYYY-MM-DD date ``days`` from now — never a literal calendar date."""
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


def _round_trip_args(*extra: str) -> list[str]:
    return [
        "flights",
        "JFK",
        "LHR",
        _future(35),
        "--return",
        _future(42),
        *extra,
    ]


def _one_way_args(*extra: str) -> list[str]:
    return ["flights", "JFK", "LHR", _future(35), *extra]


class TestTopNReachesSearch:
    def test_default_top_n_is_5_for_round_trip(self, runner, mock_search_flights, mock_console):
        result = runner.invoke(app, _round_trip_args())
        assert result.exit_code == 0
        _, kwargs = mock_search_flights.search.call_args
        assert kwargs["top_n"] == 5

    def test_explicit_top_n_reaches_search(self, runner, mock_search_flights, mock_console):
        result = runner.invoke(app, _round_trip_args("--top-n", "8"))
        assert result.exit_code == 0
        _, kwargs = mock_search_flights.search.call_args
        assert kwargs["top_n"] == 8

    def test_default_top_n_reaches_search_for_one_way_too(
        self, runner, mock_search_flights, mock_console
    ):
        """Left at its default, top_n is passed through (and ignored downstream)."""
        result = runner.invoke(app, _one_way_args())
        assert result.exit_code == 0
        _, kwargs = mock_search_flights.search.call_args
        assert kwargs["top_n"] == 5


class TestTopNJsonQueryEcho:
    def test_round_trip_echoes_top_n_in_query(self, runner, mock_search_flights, mock_console):
        result = runner.invoke(app, _round_trip_args("--top-n", "7", "--format", "json"))
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["query"]["top_n"] == 7

    def test_round_trip_default_top_n_echoed_too(self, runner, mock_search_flights, mock_console):
        result = runner.invoke(app, _round_trip_args("--format", "json"))
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["query"]["top_n"] == 5

    def test_one_way_omits_top_n_from_query(self, runner, mock_search_flights, mock_console):
        result = runner.invoke(app, _one_way_args("--format", "json"))
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert "top_n" not in payload["query"]


class TestTopNOneWayRejection:
    def test_explicit_top_n_on_one_way_is_rejected(self, runner, mock_search_flights, mock_console):
        result = runner.invoke(app, _one_way_args("--top-n", "3"))
        assert result.exit_code == 1
        assert "--top-n" in result.output
        assert "one-way" in result.output
        mock_search_flights.search.assert_not_called()

    def test_explicit_top_n_on_one_way_json_error_is_validation_error(
        self, runner, mock_search_flights, mock_console
    ):
        result = runner.invoke(app, _one_way_args("--top-n", "3", "--format", "json"))
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["success"] is False
        assert payload["error"]["type"] == "validation_error"
        assert payload["error"]["retryable"] is False
        mock_search_flights.search.assert_not_called()

    def test_default_top_n_on_one_way_is_not_rejected(
        self, runner, mock_search_flights, mock_console
    ):
        """Left at its default (not passed on the command line), no rejection."""
        result = runner.invoke(app, _one_way_args())
        assert result.exit_code == 0
        assert "--top-n" not in result.output
        mock_search_flights.search.assert_called_once()


class TestTopNBoundsRejectedByCli:
    """Bounds are enforced by the real SearchFlights.search() bound-check.

    See fli/search/flights.py, which raises before any network call. Stub
    _fetch_flights to fail the test loudly if that assumption ever breaks,
    instead of the test silently attempting a real network request.
    """

    @pytest.fixture(autouse=True)
    def _guard_against_network(self, monkeypatch):
        def _unexpected_call(*_args, **_kwargs):
            raise AssertionError("_fetch_flights should not be reached for a bad top_n")

        monkeypatch.setattr(SearchFlights, "_fetch_flights", _unexpected_call)

    @pytest.mark.parametrize("bad_top_n", ["0", "11"])
    def test_out_of_range_top_n_is_a_clean_error(self, runner, mock_console, bad_top_n):
        result = runner.invoke(app, _round_trip_args("--top-n", bad_top_n))
        assert result.exit_code == 1
        assert "top_n" in result.output

    @pytest.mark.parametrize("bad_top_n", ["0", "11"])
    def test_out_of_range_top_n_json_error_is_validation_error(
        self, runner, mock_console, bad_top_n
    ):
        result = runner.invoke(app, _round_trip_args("--top-n", bad_top_n, "--format", "json"))
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["success"] is False
        assert payload["error"]["type"] == "validation_error"
        assert payload["error"]["retryable"] is False
        assert "top_n" in payload["error"]["message"]
