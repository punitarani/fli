"""An ordinary empty search result must exit clean, not report a crash.

`typer.Exit(1)` — raised in the empty-result branch of `flights`, `dates`, and
`multi` once the search legitimately returns nothing — is `click.exceptions.Exit`,
a `RuntimeError` subclass. Each command's broad `except Exception` handler used to
catch that control-flow exception too, so a perfectly normal "no flights matched"
outcome also printed a bogus "Unexpected error: Exit: 1" line and wrote a
traceback log file under `~/.fli/logs/`.

These tests pin down two things per command: the empty-result path exits clean
with exactly its own message (no extra "Unexpected error" text, no log file),
and a genuine unexpected exception is still caught and reported exactly as
before (message + log file) — the fix must not blind the broad handler.

Kept in a new file rather than appended to test_flights.py /test_dates.py /
test_multi.py: another branch in flight also touches those files, and this
avoids conflicting with it.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fli.cli.main import app


@pytest.fixture
def runner() -> CliRunner:
    """Return a CliRunner instance."""
    return CliRunner()


@pytest.fixture(autouse=True)
def _isolated_tmp_log_dir(monkeypatch, tmp_path):
    """Redirect _LOG_DIR so log files land under tmp_path instead of ~/.fli/logs/.

    The target subdirectory does not exist until `_write_log` creates it, so
    "no log file was written" can be asserted as "the directory was never
    created" — a bug that silently creates-and-writes would fail that check,
    while a test that merely looked for zero *known* filenames would not.
    """
    monkeypatch.setattr("fli.cli.errors._LOG_DIR", tmp_path / "fli-logs")


def _log_dir(tmp_path: Path) -> Path:
    return tmp_path / "fli-logs"


def _future_date(days_ahead: int) -> str:
    """Return a future date string in YYYY-MM-DD format, relative to today."""
    return (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# flights
# ---------------------------------------------------------------------------


def test_flights_empty_result_exits_clean(runner, mock_search_flights, mock_console, tmp_path):
    """An ordinary empty flight search exits 1 with only the empty-result message."""
    mock_search_flights.search.return_value = []

    result = runner.invoke(app, ["flights", "JFK", "LHR", _future_date(40)])

    assert result.exit_code == 1
    assert result.output.count("No flights found.") == 1
    assert "Unexpected error" not in result.output
    assert "Exit: 1" not in result.output
    assert "Full traceback" not in result.output
    assert not _log_dir(tmp_path).exists()


def test_flights_json_empty_result_unchanged(runner, mock_search_flights, mock_console):
    """`--format json` still exits 0 with an empty flights[] payload, untouched by the fix."""
    mock_search_flights.search.return_value = []

    result = runner.invoke(app, ["flights", "JFK", "LHR", _future_date(40), "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["count"] == 0
    assert payload["flights"] == []


def test_flights_unexpected_exception_still_reported(
    runner, mock_search_flights, mock_console, tmp_path
):
    """A genuine crash still goes through the broad handler: message + log file."""
    mock_search_flights.search.side_effect = RuntimeError("boom")

    result = runner.invoke(app, ["flights", "JFK", "LHR", _future_date(40)])

    assert result.exit_code == 1
    assert "Unexpected error: RuntimeError: boom" in result.output
    assert "Full traceback written to" in result.output
    log_dir = _log_dir(tmp_path)
    assert log_dir.exists()
    assert list(log_dir.iterdir())


# ---------------------------------------------------------------------------
# dates
# ---------------------------------------------------------------------------


def test_dates_empty_result_exits_clean(runner, mock_search_dates, mock_console, tmp_path):
    """An ordinary empty dates search exits 1 with only the empty-result message."""
    mock_search_dates.search.return_value = []

    result = runner.invoke(app, ["dates", "JFK", "LHR"])

    assert result.exit_code == 1
    assert result.output.count("No flights found for these dates.") == 1
    assert "Unexpected error" not in result.output
    assert "Exit: 1" not in result.output
    assert "Full traceback" not in result.output
    assert not _log_dir(tmp_path).exists()


def test_dates_empty_result_for_selected_days_exits_clean(
    runner, mock_search_dates, mock_console, tmp_path
):
    """The "selected days" empty-result variant is equally clean."""
    mock_search_dates.search.return_value = []

    result = runner.invoke(app, ["dates", "JFK", "LHR", "--monday"])

    assert result.exit_code == 1
    assert result.output.count("No flights found for the selected days.") == 1
    assert "Unexpected error" not in result.output
    assert "Exit: 1" not in result.output
    assert "Full traceback" not in result.output
    assert not _log_dir(tmp_path).exists()


def test_dates_json_empty_result_unchanged(runner, mock_search_dates, mock_console):
    """`--format json` still exits 0 with an empty dates[] payload, untouched by the fix."""
    mock_search_dates.search.return_value = []

    result = runner.invoke(app, ["dates", "JFK", "LHR", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["count"] == 0
    assert payload["dates"] == []


def test_dates_unexpected_exception_still_reported(
    runner, mock_search_dates, mock_console, tmp_path
):
    """A genuine crash still goes through the broad handler: message + log file."""
    mock_search_dates.search.side_effect = RuntimeError("boom")

    result = runner.invoke(app, ["dates", "JFK", "LHR"])

    assert result.exit_code == 1
    assert "Unexpected error: RuntimeError: boom" in result.output
    assert "Full traceback written to" in result.output
    log_dir = _log_dir(tmp_path)
    assert log_dir.exists()
    assert list(log_dir.iterdir())


# ---------------------------------------------------------------------------
# multi
# ---------------------------------------------------------------------------


def test_multi_empty_result_exits_clean(runner, mock_search_flights, mock_console, tmp_path):
    """An ordinary empty multi-city search exits 1 with only the empty-result message."""
    mock_search_flights.search.return_value = []

    result = runner.invoke(
        app,
        ["multi", "--leg", f"SEA,HKG,{_future_date(40)}", "--leg", f"HKG,SEA,{_future_date(47)}"],
    )

    assert result.exit_code == 1
    assert result.output.count("No flights found.") == 1
    assert "Unexpected error" not in result.output
    assert "Exit: 1" not in result.output
    assert "Full traceback" not in result.output
    assert not _log_dir(tmp_path).exists()


def test_multi_too_few_legs_exits_clean(runner, mock_search_flights, mock_console, tmp_path):
    """The "requires at least 2 legs" guard is control flow too, not a crash."""
    result = runner.invoke(app, ["multi", "--leg", f"SEA,HKG,{_future_date(40)}"])

    assert result.exit_code == 1
    assert result.output.count("Error: multi-city search requires at least 2 legs") == 1
    assert "Unexpected error" not in result.output
    assert "Exit: 1" not in result.output
    assert "Full traceback" not in result.output
    assert not _log_dir(tmp_path).exists()
    mock_search_flights.search.assert_not_called()


def test_multi_unexpected_exception_still_reported(
    runner, mock_search_flights, mock_console, tmp_path
):
    """A genuine crash still goes through the broad handler: message + log file."""
    mock_search_flights.search.side_effect = RuntimeError("boom")

    result = runner.invoke(
        app,
        ["multi", "--leg", f"SEA,HKG,{_future_date(40)}", "--leg", f"HKG,SEA,{_future_date(47)}"],
    )

    assert result.exit_code == 1
    assert "Unexpected error: RuntimeError: boom" in result.output
    assert "Full traceback written to" in result.output
    log_dir = _log_dir(tmp_path)
    assert log_dir.exists()
    assert list(log_dir.iterdir())
