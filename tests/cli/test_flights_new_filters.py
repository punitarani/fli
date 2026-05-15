"""CLI parsing tests for the new May-2026 filter flags.

These tests don't hit the network — they mock the SearchFlights client
and just assert that the typer command translates the new CLI flags
(``--alliance``, ``--exclude-airlines``, ``--exclude-alliance``,
``--min-layover``, ``--max-layover``) into the matching kwargs on the
underlying FlightSearchFilters object.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from typer.testing import CliRunner

from fli.cli.main import app
from fli.models import Airline, Alliance


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _filters_from_last_call(mock_search_flights) -> Any:
    """Pluck the FlightSearchFilters object passed to SearchFlights.search."""
    assert mock_search_flights.search.call_count >= 1, "search() was not called"
    last_call = mock_search_flights.search.call_args_list[-1]
    # Positional or keyword — both supported.
    if last_call.args:
        return last_call.args[0]
    return last_call.kwargs["filters"]


class TestAllianceFlag:
    def test_single_alliance(self, runner, mock_search_flights, mock_console):
        result = runner.invoke(
            app,
            [
                "flights",
                "JFK",
                "LAX",
                datetime.now().strftime("%Y-%m-%d"),
                "--alliance",
                "ONEWORLD",
            ],
        )
        assert result.exit_code == 0
        f = _filters_from_last_call(mock_search_flights)
        assert f.alliances == [Alliance.ONEWORLD]

    def test_multiple_alliances_comma(self, runner, mock_search_flights, mock_console):
        result = runner.invoke(
            app,
            [
                "flights",
                "JFK",
                "LAX",
                datetime.now().strftime("%Y-%m-%d"),
                "--alliance",
                "ONEWORLD,SKYTEAM",
            ],
        )
        assert result.exit_code == 0
        f = _filters_from_last_call(mock_search_flights)
        assert set(f.alliances) == {Alliance.ONEWORLD, Alliance.SKYTEAM}

    def test_multiple_alliances_repeated(self, runner, mock_search_flights, mock_console):
        result = runner.invoke(
            app,
            [
                "flights",
                "JFK",
                "LAX",
                datetime.now().strftime("%Y-%m-%d"),
                "--alliance",
                "ONEWORLD",
                "--alliance",
                "STAR_ALLIANCE",
            ],
        )
        assert result.exit_code == 0
        f = _filters_from_last_call(mock_search_flights)
        assert set(f.alliances) == {Alliance.ONEWORLD, Alliance.STAR_ALLIANCE}

    def test_case_insensitive(self, runner, mock_search_flights, mock_console):
        result = runner.invoke(
            app,
            [
                "flights",
                "JFK",
                "LAX",
                datetime.now().strftime("%Y-%m-%d"),
                "--alliance",
                "oneworld",
            ],
        )
        assert result.exit_code == 0
        f = _filters_from_last_call(mock_search_flights)
        assert f.alliances == [Alliance.ONEWORLD]

    def test_invalid_alliance_rejected(self, runner, mock_search_flights, mock_console):
        result = runner.invoke(
            app,
            [
                "flights",
                "JFK",
                "LAX",
                datetime.now().strftime("%Y-%m-%d"),
                "--alliance",
                "BOGUS_ALLIANCE",
            ],
        )
        assert result.exit_code != 0


class TestExcludeAirlinesFlag:
    def test_single_exclude(self, runner, mock_search_flights, mock_console):
        result = runner.invoke(
            app,
            [
                "flights",
                "JFK",
                "LAX",
                datetime.now().strftime("%Y-%m-%d"),
                "--exclude-airlines",
                "DL",
            ],
        )
        assert result.exit_code == 0
        f = _filters_from_last_call(mock_search_flights)
        assert f.airlines_exclude == [Airline.DL]

    def test_multiple_exclude_comma(self, runner, mock_search_flights, mock_console):
        result = runner.invoke(
            app,
            [
                "flights",
                "JFK",
                "LAX",
                datetime.now().strftime("%Y-%m-%d"),
                "--exclude-airlines",
                "DL,B6",
            ],
        )
        assert result.exit_code == 0
        f = _filters_from_last_call(mock_search_flights)
        assert set(f.airlines_exclude) == {Airline.DL, Airline.B6}

    def test_exclude_short_flag(self, runner, mock_search_flights, mock_console):
        # -A is the short form for --exclude-airlines.
        result = runner.invoke(
            app,
            [
                "flights",
                "JFK",
                "LAX",
                datetime.now().strftime("%Y-%m-%d"),
                "-A",
                "DL",
            ],
        )
        assert result.exit_code == 0
        f = _filters_from_last_call(mock_search_flights)
        assert f.airlines_exclude == [Airline.DL]


class TestExcludeAllianceFlag:
    def test_exclude_alliance(self, runner, mock_search_flights, mock_console):
        result = runner.invoke(
            app,
            [
                "flights",
                "JFK",
                "LAX",
                datetime.now().strftime("%Y-%m-%d"),
                "--exclude-alliance",
                "STAR_ALLIANCE",
            ],
        )
        assert result.exit_code == 0
        f = _filters_from_last_call(mock_search_flights)
        assert f.alliances_exclude == [Alliance.STAR_ALLIANCE]


class TestLayoverDurationFlags:
    def test_min_layover_only(self, runner, mock_search_flights, mock_console):
        result = runner.invoke(
            app,
            [
                "flights",
                "BUF",
                "ATH",
                datetime.now().strftime("%Y-%m-%d"),
                "--min-layover",
                "120",
            ],
        )
        assert result.exit_code == 0
        f = _filters_from_last_call(mock_search_flights)
        assert f.layover_restrictions is not None
        assert f.layover_restrictions.min_duration == 120
        assert f.layover_restrictions.max_duration is None

    def test_max_layover_only(self, runner, mock_search_flights, mock_console):
        result = runner.invoke(
            app,
            [
                "flights",
                "BUF",
                "ATH",
                datetime.now().strftime("%Y-%m-%d"),
                "--max-layover",
                "300",
            ],
        )
        assert result.exit_code == 0
        f = _filters_from_last_call(mock_search_flights)
        assert f.layover_restrictions is not None
        assert f.layover_restrictions.min_duration is None
        assert f.layover_restrictions.max_duration == 300

    def test_both_min_and_max(self, runner, mock_search_flights, mock_console):
        result = runner.invoke(
            app,
            [
                "flights",
                "BUF",
                "ATH",
                datetime.now().strftime("%Y-%m-%d"),
                "--min-layover",
                "60",
                "--max-layover",
                "240",
            ],
        )
        assert result.exit_code == 0
        f = _filters_from_last_call(mock_search_flights)
        assert f.layover_restrictions.min_duration == 60
        assert f.layover_restrictions.max_duration == 240

    def test_layover_with_specific_airports(self, runner, mock_search_flights, mock_console):
        # Combining --layover (airports) with the new --min-layover/--max-layover.
        result = runner.invoke(
            app,
            [
                "flights",
                "BUF",
                "ATH",
                datetime.now().strftime("%Y-%m-%d"),
                "--layover",
                "ORD",
                "--min-layover",
                "90",
            ],
        )
        assert result.exit_code == 0
        f = _filters_from_last_call(mock_search_flights)
        assert f.layover_restrictions.min_duration == 90
        assert f.layover_restrictions.airports is not None


class TestCombinedFilters:
    def test_alliance_plus_exclude_plus_min_layover(
        self, runner, mock_search_flights, mock_console
    ):
        result = runner.invoke(
            app,
            [
                "flights",
                "JFK",
                "FRA",
                datetime.now().strftime("%Y-%m-%d"),
                "--alliance",
                "ONEWORLD",
                "--exclude-airlines",
                "BA",
                "--min-layover",
                "90",
            ],
        )
        assert result.exit_code == 0
        f = _filters_from_last_call(mock_search_flights)
        assert f.alliances == [Alliance.ONEWORLD]
        assert f.airlines_exclude == [Airline.BA]
        assert f.layover_restrictions.min_duration == 90


class TestLocaleFlags:
    """``--currency`` / ``--language`` / ``--country`` reach SearchFlights.search."""

    def _kwargs_from_last_call(self, mock_search_flights) -> dict:
        last = mock_search_flights.search.call_args_list[-1]
        return dict(last.kwargs)

    def test_currency_forwarded(self, runner, mock_search_flights, mock_console):
        result = runner.invoke(
            app,
            [
                "flights",
                "JFK",
                "LAX",
                datetime.now().strftime("%Y-%m-%d"),
                "--currency",
                "EUR",
            ],
        )
        assert result.exit_code == 0
        kwargs = self._kwargs_from_last_call(mock_search_flights)
        assert kwargs.get("currency") == "EUR"

    def test_language_and_country_forwarded(self, runner, mock_search_flights, mock_console):
        result = runner.invoke(
            app,
            [
                "flights",
                "JFK",
                "LAX",
                datetime.now().strftime("%Y-%m-%d"),
                "--language",
                "en-GB",
                "--country",
                "GB",
            ],
        )
        assert result.exit_code == 0
        kwargs = self._kwargs_from_last_call(mock_search_flights)
        assert kwargs.get("language") == "en-GB"
        assert kwargs.get("country") == "GB"

    def test_invalid_currency_rejected(self, runner, mock_search_flights, mock_console):
        """The ``validate_currency`` callback must reject malformed codes."""
        result = runner.invoke(
            app,
            [
                "flights",
                "JFK",
                "LAX",
                datetime.now().strftime("%Y-%m-%d"),
                "--currency",
                "US1",  # contains a digit — not a valid ISO 4217 code
            ],
        )
        assert result.exit_code != 0
