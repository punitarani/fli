"""Tests for the `fli airports` CLI command."""

import json

import pytest
from typer.testing import CliRunner

from fli.cli.main import app


@pytest.fixture
def runner():
    return CliRunner()


class TestAirportsCommand:
    def test_exact_code_table_output(self, runner):
        result = runner.invoke(app, ["airports", "JFK"])
        assert result.exit_code == 0
        assert "JFK" in result.stdout

    def test_json_output(self, runner):
        result = runner.invoke(app, ["airports", "JFK", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert isinstance(payload, list)
        assert payload[0]["code"] == "JFK"
        assert payload[0]["match_type"] == "iata_exact"

    def test_city_query_returns_all_airports(self, runner):
        result = runner.invoke(app, ["airports", "new york", "--json"])
        assert result.exit_code == 0
        codes = {row["code"] for row in json.loads(result.stdout)}
        assert {"JFK", "LGA", "EWR"} <= codes

    def test_no_results_exits_with_error(self, runner):
        result = runner.invoke(app, ["airports", "xyznonexistent"])
        assert result.exit_code == 1
        assert "No airports found" in result.stdout

    def test_limit_caps_results(self, runner):
        result = runner.invoke(app, ["airports", "international", "--limit", "2", "--json"])
        assert result.exit_code == 0
        assert len(json.loads(result.stdout)) <= 2
