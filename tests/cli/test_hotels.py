"""Tests for the hotels CLI command."""

import json

import pytest
from typer.testing import CliRunner

from fli.cli.main import app


@pytest.fixture
def runner():
    """Return a CliRunner instance."""
    return CliRunner()


def test_basic_hotel_search(runner, mock_search_hotels, mock_console):
    """Test basic hotel search with required parameters."""
    result = runner.invoke(app, ["hotels", "Lima", "2026-06-10", "2026-06-18"])
    assert result.exit_code == 0
    mock_search_hotels.search.assert_called_once()


def test_hotels_with_adults(runner, mock_search_hotels, mock_console):
    """Test hotel search with adults option."""
    result = runner.invoke(
        app,
        ["hotels", "Lima", "2026-06-10", "2026-06-18", "--adults", "4"],
    )
    assert result.exit_code == 0
    mock_search_hotels.search.assert_called_once()


def test_hotels_with_children(runner, mock_search_hotels, mock_console):
    """Test hotel search with children option."""
    result = runner.invoke(
        app,
        ["hotels", "Lima", "2026-06-10", "2026-06-18", "--children", "2"],
    )
    assert result.exit_code == 0
    mock_search_hotels.search.assert_called_once()


def test_hotels_with_currency(runner, mock_search_hotels, mock_console):
    """Test hotel search with currency option."""
    result = runner.invoke(
        app,
        ["hotels", "Lima", "2026-06-10", "2026-06-18", "--currency", "EUR"],
    )
    assert result.exit_code == 0
    mock_search_hotels.search.assert_called_once()


def test_hotels_with_sort(runner, mock_search_hotels, mock_console):
    """Test hotel search with sort option."""
    result = runner.invoke(
        app,
        ["hotels", "Lima", "2026-06-10", "2026-06-18", "--sort", "price"],
    )
    assert result.exit_code == 0
    mock_search_hotels.search.assert_called_once()


def test_hotels_with_limit(runner, mock_search_hotels, mock_console):
    """Test hotel search with limit option."""
    result = runner.invoke(
        app,
        ["hotels", "Lima", "2026-06-10", "2026-06-18", "--limit", "5"],
    )
    assert result.exit_code == 0
    mock_search_hotels.search.assert_called_once()


def test_hotels_with_all_options(runner, mock_search_hotels, mock_console):
    """Test hotel search with all options combined."""
    result = runner.invoke(
        app,
        [
            "hotels",
            "Tokyo",
            "2026-08-01",
            "2026-08-07",
            "--adults",
            "2",
            "--children",
            "1",
            "--currency",
            "EUR",
            "--sort",
            "rating",
            "--limit",
            "10",
        ],
    )
    assert result.exit_code == 0
    mock_search_hotels.search.assert_called_once()


def test_hotels_no_results(runner, mock_search_hotels, mock_console):
    """Test hotel search with no results."""
    mock_search_hotels.search.return_value = None

    result = runner.invoke(app, ["hotels", "Lima", "2026-06-10", "2026-06-18"])
    assert result.exit_code == 1
    assert "No hotels found" in result.stdout


def test_hotels_json_output(runner, mock_search_hotels, mock_console):
    """Test hotel search with JSON output."""
    result = runner.invoke(
        app,
        ["hotels", "Lima", "2026-06-10", "2026-06-18", "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["data_source"] == "google_travel"
    assert payload["search_type"] == "hotels"
    assert payload["count"] == 3
    assert payload["hotels"][0]["name"] == "Hotel Lima Central"
    assert payload["hotels"][0]["price"] == 89.99
    assert payload["hotels"][0]["rating"] == 4.2
    assert payload["hotels"][0]["amenities"] == ["Free WiFi", "Pool", "Breakfast", "Gym", "Spa"]


def test_hotels_json_no_results(runner, mock_search_hotels, mock_console):
    """Test hotel JSON output when no results found."""
    mock_search_hotels.search.return_value = None

    result = runner.invoke(
        app,
        ["hotels", "Lima", "2026-06-10", "2026-06-18", "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["count"] == 0
    assert payload["hotels"] == []


def test_hotels_quoted_location(runner, mock_search_hotels, mock_console):
    """Test hotel search with multi-word location."""
    result = runner.invoke(
        app,
        ["hotels", "Buenos Aires", "2026-06-25", "2026-07-10"],
    )
    assert result.exit_code == 0
    mock_search_hotels.search.assert_called_once()


def test_hotels_short_options(runner, mock_search_hotels, mock_console):
    """Test hotel search with short option flags."""
    result = runner.invoke(
        app,
        [
            "hotels",
            "Lima",
            "2026-06-10",
            "2026-06-18",
            "-a",
            "3",
            "-k",
            "1",
            "-c",
            "GBP",
            "-s",
            "best",
            "-n",
            "5",
        ],
    )
    assert result.exit_code == 0
    mock_search_hotels.search.assert_called_once()
