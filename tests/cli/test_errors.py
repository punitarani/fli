"""Tests for the CLI error reporting helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from fli.cli.errors import _write_log, json_error_payload, report_cli_error
from fli.cli.main import app
from fli.search.exceptions import (
    SearchClientError,
    SearchConnectionError,
    SearchHTTPError,
    SearchTimeoutError,
)


@pytest.fixture
def runner() -> CliRunner:
    """Return a CliRunner instance."""
    return CliRunner()


@pytest.fixture(autouse=True)
def _isolated_tmp_log_dir(monkeypatch, tmp_path):
    """Redirect _LOG_DIR so log files land under tmp_path instead of ~/.fli/logs/."""
    monkeypatch.setattr("fli.cli.errors._LOG_DIR", tmp_path / "fli-logs")


def test_write_log_creates_file_with_traceback(tmp_path):
    """`_write_log` should write a file containing the traceback details."""
    try:
        raise SearchTimeoutError("backend slow")
    except SearchTimeoutError as exc:
        log_path = _write_log(exc, command="flights")

    assert log_path.exists()
    contents = log_path.read_text()
    assert "command: flights" in contents
    assert "SearchTimeoutError" in contents
    assert "backend slow" in contents
    assert "traceback:" in contents


def test_json_error_payload_maps_error_types():
    """Each SearchClientError subclass should map to a distinct error_type string."""
    cases = [
        (SearchTimeoutError("timed out"), "timeout"),
        (SearchConnectionError("dns"), "connection_error"),
        (SearchHTTPError("403", status_code=403), "http_error"),
        (SearchClientError("generic"), "search_error"),
        (RuntimeError("boom"), "unexpected_error"),
    ]
    for exc, expected_type in cases:
        message, error_type, log_path = json_error_payload(exc)
        assert error_type == expected_type
        assert isinstance(log_path, Path)
        assert log_path.exists()
        assert message  # non-empty


def test_report_cli_error_returns_typer_exit_and_writes_log(tmp_path, capsys):
    """`report_cli_error` should write a log and return a typer.Exit."""
    import typer

    exc = SearchTimeoutError("hung")
    result = report_cli_error(exc, command="multi")
    assert isinstance(result, typer.Exit)
    assert result.exit_code == 1

    # A log file should now exist under our redirected tmp dir.
    log_files = list((tmp_path / "fli-logs").glob("fli-error-*.log"))
    assert len(log_files) == 1


def test_multi_command_handles_timeout_cleanly(runner, monkeypatch, tmp_path):
    """A curl timeout inside `multi` should produce a clean message + log file."""
    from curl_cffi.requests import exceptions as curl_exc

    def fake_post(self, url, **kwargs):
        raise curl_exc.Timeout("curl: (28) timed out", 28, None)

    monkeypatch.setattr("curl_cffi.requests.Session.post", fake_post)

    result = runner.invoke(
        app,
        [
            "multi",
            "-l",
            "SEA,NRT,2026-12-26",
            "-l",
            "NRT,HKG,2026-12-30",
            "-l",
            "HKG,SEA,2027-01-05",
        ],
    )

    assert result.exit_code == 1
    # Friendly message — no raw curl traceback in the output.
    assert "Error" in result.output
    assert "Timed out talking to Google Flights" in result.output
    assert "Full traceback written to" in result.output
    assert "Traceback (most recent call last)" not in result.output

    log_files = list((tmp_path / "fli-logs").glob("fli-error-*.log"))
    assert len(log_files) >= 1


def test_flights_command_json_error_includes_log_path(runner, monkeypatch, tmp_path):
    """JSON-mode errors should include the log path and a typed error_type."""
    import json

    from curl_cffi.requests import exceptions as curl_exc

    def fake_post(self, url, **kwargs):
        raise curl_exc.ConnectionError("dns lookup failed", 6, None)

    monkeypatch.setattr("curl_cffi.requests.Session.post", fake_post)

    result = runner.invoke(
        app,
        ["flights", "JFK", "LHR", "2026-10-25", "--format", "json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False
    assert payload["error"]["type"] == "connection_error"
    assert "log_path" in payload["error"]
    assert Path(payload["error"]["log_path"]).exists()
