"""Tests for the new May-2026 filter params on MCP `search_flights` / `search_dates`.

The MCP tool layer is a thin adapter — it parses user-facing strings into
the typed filter objects, then forwards to ``SearchFlights`` /
``SearchDates``. These tests mock those backend search methods and assert
that the constructed filters / kwargs carry the new fields. A regression
in the parser wiring (e.g. ``parse_alliances`` returning the wrong type,
or ``min_layover`` lost on the way to ``LayoverRestrictions``) gets
caught here without any network call.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from fli.mcp.server import (
    DateSearchParams,
    FlightSearchParams,
    _search_dates_from_params,
    _search_flights_from_params,
)
from fli.models import (
    Airline,
    Alliance,
    DateSearchFilters,
    FlightSearchFilters,
)


def _future(days: int) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


@pytest.fixture
def captured_search():
    """Patch ``SearchFlights.search`` and capture the filter + kwargs it receives."""
    captured: dict = {}

    def _fake(self, filters, **kwargs):
        captured["filters"] = filters
        captured["kwargs"] = kwargs
        return []  # MCP layer is happy with an empty result.

    with patch("fli.mcp.server.SearchFlights.search", side_effect=_fake, autospec=True):
        yield captured


@pytest.fixture
def captured_dates():
    captured: dict = {}

    def _fake(self, filters, **kwargs):
        captured["filters"] = filters
        captured["kwargs"] = kwargs
        return []

    with patch("fli.mcp.server.SearchDates.search", side_effect=_fake, autospec=True):
        yield captured


# ---------------------------------------------------------------------------
# search_flights — new filter params
# ---------------------------------------------------------------------------


class TestSearchFlightsNewFilters:
    def test_currency_language_country_flow_to_search_kwargs(self, captured_search):
        params = FlightSearchParams(
            origin="JFK",
            destination="LAX",
            departure_date=_future(30),
            currency="eur",
            language="en-GB",
            country="gb",
        )
        result = _search_flights_from_params(params)
        assert result["success"] is True
        kwargs = captured_search["kwargs"]
        # ``currency`` is normalised via parse_currency (uppercases ISO codes).
        assert kwargs["currency"] == "EUR"
        assert kwargs["language"] == "en-GB"
        assert kwargs["country"] == "gb"

    def test_alliance_include_translates_to_filter(self, captured_search):
        params = FlightSearchParams(
            origin="JFK",
            destination="FRA",
            departure_date=_future(30),
            alliance=["ONEWORLD"],
        )
        _search_flights_from_params(params)
        filters: FlightSearchFilters = captured_search["filters"]
        assert filters.alliances == [Alliance.ONEWORLD]
        assert filters.alliances_exclude is None

    def test_alliance_exclude_translates_to_filter(self, captured_search):
        params = FlightSearchParams(
            origin="JFK",
            destination="FRA",
            departure_date=_future(30),
            exclude_alliance=["STAR_ALLIANCE", "SKYTEAM"],
        )
        _search_flights_from_params(params)
        filters = captured_search["filters"]
        assert filters.alliances_exclude == [Alliance.STAR_ALLIANCE, Alliance.SKYTEAM]

    def test_airlines_exclude_translates_to_filter(self, captured_search):
        params = FlightSearchParams(
            origin="JFK",
            destination="LAX",
            departure_date=_future(30),
            exclude_airlines=["DL", "B6"],
        )
        _search_flights_from_params(params)
        filters = captured_search["filters"]
        assert filters.airlines_exclude == [Airline.DL, Airline.B6]

    def test_min_max_layover_build_restrictions(self, captured_search):
        params = FlightSearchParams(
            origin="BUF",
            destination="ATH",
            departure_date=_future(30),
            min_layover=120,
            max_layover=600,
        )
        _search_flights_from_params(params)
        filters = captured_search["filters"]
        assert filters.layover_restrictions is not None
        assert filters.layover_restrictions.min_duration == 120
        assert filters.layover_restrictions.max_duration == 600

    def test_invalid_alliance_string_returns_error(self):
        """``parse_alliances`` rejects unknown names without leaking an exception."""
        params = FlightSearchParams(
            origin="JFK",
            destination="LAX",
            departure_date=_future(30),
            alliance=["NOT_AN_ALLIANCE"],
        )
        result = _search_flights_from_params(params)
        assert result["success"] is False
        assert "alliance" in result["error"].lower() or "invalid" in result["error"].lower()

    def test_combined_new_filters_all_propagate(self, captured_search):
        """All new params together produce a fully-populated filter object."""
        params = FlightSearchParams(
            origin="JFK",
            destination="LAX",
            departure_date=_future(30),
            currency="USD",
            language="en",
            country="US",
            alliance=["ONEWORLD"],
            exclude_airlines=["DL"],
            min_layover=90,
            max_layover=480,
        )
        _search_flights_from_params(params)
        f = captured_search["filters"]
        k = captured_search["kwargs"]
        assert f.alliances == [Alliance.ONEWORLD]
        assert f.airlines_exclude == [Airline.DL]
        assert f.layover_restrictions.min_duration == 90
        assert f.layover_restrictions.max_duration == 480
        assert k["currency"] == "USD"
        assert k["language"] == "en"
        assert k["country"] == "US"


# ---------------------------------------------------------------------------
# search_dates — new filter params
# ---------------------------------------------------------------------------


class TestSearchDatesNewFilters:
    def test_currency_language_country_flow_to_search_kwargs(self, captured_dates):
        params = DateSearchParams(
            origin="JFK",
            destination="LAX",
            start_date=_future(30),
            end_date=_future(60),
            currency="gbp",
            language="en-GB",
            country="gb",
        )
        result = _search_dates_from_params(params)
        assert result["success"] is True
        kwargs = captured_dates["kwargs"]
        assert kwargs["currency"] == "GBP"
        assert kwargs["language"] == "en-GB"
        assert kwargs["country"] == "gb"

    def test_alliance_filters_translate(self, captured_dates):
        params = DateSearchParams(
            origin="JFK",
            destination="FRA",
            start_date=_future(30),
            end_date=_future(60),
            alliance=["SKYTEAM"],
            exclude_alliance=["ONEWORLD"],
        )
        _search_dates_from_params(params)
        filters: DateSearchFilters = captured_dates["filters"]
        assert filters.alliances == [Alliance.SKYTEAM]
        assert filters.alliances_exclude == [Alliance.ONEWORLD]

    def test_airlines_exclude_translates(self, captured_dates):
        params = DateSearchParams(
            origin="JFK",
            destination="LAX",
            start_date=_future(30),
            end_date=_future(60),
            exclude_airlines=["DL"],
        )
        _search_dates_from_params(params)
        filters = captured_dates["filters"]
        assert filters.airlines_exclude == [Airline.DL]

    def test_layover_restrictions_built(self, captured_dates):
        params = DateSearchParams(
            origin="JFK",
            destination="ATH",
            start_date=_future(30),
            end_date=_future(60),
            min_layover=120,
            max_layover=600,
        )
        _search_dates_from_params(params)
        filters = captured_dates["filters"]
        assert filters.layover_restrictions is not None
        assert filters.layover_restrictions.min_duration == 120
        assert filters.layover_restrictions.max_duration == 600
