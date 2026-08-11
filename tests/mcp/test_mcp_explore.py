"""Unit tests for the search_explore MCP tool (SearchExplore is mocked)."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from fli.mcp.server import (
    ExploreSearchParams,
    _parse_explore_destination,
    _parse_explore_origin,
    _search_explore_from_params,
)
from fli.models import (
    Airport,
    ExploreDestination,
    ExplorePlace,
    ExploreRegion,
    ExploreResult,
)

DEPARTURE_DATE = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")


def _make_result() -> ExploreResult:
    return ExploreResult(
        region_name="Europe",
        origin_name="New York",
        price_slider_min=50,
        price_slider_max=1500,
        destinations=[
            ExploreDestination(
                mid="/m/0491y",
                name="Kraków",
                country="Poland",
                price=118,
                currency="USD",
                airline="FR",
                airline_name="Ryanair",
                stops=0,
                duration_minutes=140,
                destination_airport="KRK",
                departure_date=DEPARTURE_DATE,
                arrival_date=DEPARTURE_DATE,
            ),
            ExploreDestination(mid="/m/056_y", name="Unpriced Town"),
            ExploreDestination(
                mid="/m/04v3q",
                name="Malta",
                country="Malta",
                price=45,
                currency="USD",
                airline="W9",
                destination_airport="MLA",
                departure_date=DEPARTURE_DATE,
            ),
        ],
    )


@pytest.fixture
def mock_search(monkeypatch):
    """Patch SearchExplore in the server module; returns the mock class."""
    mock_cls = MagicMock()
    mock_cls.return_value.search.return_value = _make_result()
    monkeypatch.setattr("fli.mcp.server.SearchExplore", mock_cls)
    return mock_cls


class TestDestinationParsing:
    def test_region_names(self):
        assert _parse_explore_destination("ANYWHERE") is ExploreRegion.ANYWHERE
        assert _parse_explore_destination("europe") is ExploreRegion.EUROPE
        assert _parse_explore_destination("Southern Europe") is ExploreRegion.SOUTHERN_EUROPE
        assert _parse_explore_destination("north-america") is ExploreRegion.NORTH_AMERICA

    def test_raw_mid(self):
        place = _parse_explore_destination("/m/05qtj")
        assert isinstance(place, ExplorePlace)
        assert place.mid == "/m/05qtj"

    def test_airport_code(self):
        assert _parse_explore_destination("LHR") is Airport.LHR

    def test_garbage_reports_options(self, mock_search):
        params = ExploreSearchParams(
            origin="JFK", destination="NOT_A_PLACE", departure_date=DEPARTURE_DATE
        )
        result = _search_explore_from_params(params)
        assert result["success"] is False
        assert "ANYWHERE" in result["error"]
        assert result["destinations"] == []

    def test_origin_mid_is_city_typed(self):
        origin = _parse_explore_origin("/m/04jpl")
        assert isinstance(origin, ExplorePlace)
        assert origin.type_code == 4

    def test_origin_airport(self):
        assert _parse_explore_origin("jfk") is Airport.JFK


class TestExecuteExploreSearch:
    def test_success_shape_and_price_sort(self, mock_search):
        params = ExploreSearchParams(origin="JFK", departure_date=DEPARTURE_DATE)
        result = _search_explore_from_params(params)

        assert result["success"] is True
        assert result["count"] == 3
        assert result["priced_count"] == 2
        assert result["region_name"] == "Europe"
        assert result["origin_name"] == "New York"
        # Cheapest first, unpriced destinations last.
        assert [d["name"] for d in result["destinations"]] == [
            "Malta",
            "Kraków",
            "Unpriced Town",
        ]
        malta = result["destinations"][0]
        assert malta["price"] == 45
        assert malta["destination_airport"] == "MLA"
        assert "flights_url" in malta
        assert "JFK" in malta["flights_url"]
        # Unpriced entries have no airport/date, so no deep link.
        assert "flights_url" not in result["destinations"][2]

    def test_unsorted_keeps_response_order(self, mock_search):
        params = ExploreSearchParams(
            origin="JFK", departure_date=DEPARTURE_DATE, sort_by_price=False
        )
        result = _search_explore_from_params(params)
        assert [d["name"] for d in result["destinations"]] == [
            "Kraków",
            "Unpriced Town",
            "Malta",
        ]

    def test_limit_applies_after_sort(self, mock_search):
        params = ExploreSearchParams(origin="JFK", departure_date=DEPARTURE_DATE, limit=1)
        result = _search_explore_from_params(params)
        assert result["count"] == 1
        assert result["destinations"][0]["name"] == "Malta"

    def test_round_trip_builds_window(self, mock_search):
        params = ExploreSearchParams(
            origin="JFK",
            departure_date=DEPARTURE_DATE,
            round_trip=True,
            trip_min_nights=7,
            trip_max_nights=14,
        )
        result = _search_explore_from_params(params)
        assert result["success"] is True
        assert result["trip_type"] == "ROUND_TRIP"
        filters = mock_search.return_value.search.call_args.args[0]
        assert filters.trip_length_window == [4, 23, 7, 14]

    def test_trip_window_min_exceeding_max_is_rejected(self, mock_search):
        """An inverted nights window must fail locally, not reach Google."""
        params = ExploreSearchParams(
            origin="JFK",
            departure_date=DEPARTURE_DATE,
            trip_min_nights=14,
            trip_max_nights=7,
        )
        result = _search_explore_from_params(params)
        assert result["success"] is False
        assert "trip_min_nights" in result["error"]
        mock_search.return_value.search.assert_not_called()

    def test_window_without_round_trip_is_allowed(self, mock_search):
        """Google accepts a trip-length window on one-way searches (HAR-observed)."""
        params = ExploreSearchParams(
            origin="JFK",
            departure_date=DEPARTURE_DATE,
            trip_min_nights=0,
            trip_max_nights=7,
        )
        result = _search_explore_from_params(params)
        assert result["success"] is True
        filters = mock_search.return_value.search.call_args.args[0]
        assert filters.trip_length_window == [4, 23, 0, 7]

    def test_none_result_is_reported_as_error(self, mock_search):
        """An unparseable response is a failed request, not an empty result set."""
        mock_search.return_value.search.return_value = None
        params = ExploreSearchParams(origin="JFK", departure_date=DEPARTURE_DATE)
        result = _search_explore_from_params(params)
        assert result["success"] is False
        assert "no parseable response" in result["error"]
        assert result["destinations"] == []

    def test_search_exception_reported(self, mock_search):
        mock_search.return_value.search.side_effect = RuntimeError("boom")
        params = ExploreSearchParams(origin="JFK", departure_date=DEPARTURE_DATE)
        result = _search_explore_from_params(params)
        assert result["success"] is False
        assert "boom" in result["error"]
        assert result["destinations"] == []

    def test_bad_origin_is_parse_error(self, mock_search):
        params = ExploreSearchParams(origin="NOT_AN_AIRPORT", departure_date=DEPARTURE_DATE)
        result = _search_explore_from_params(params)
        assert result["success"] is False
        assert result["destinations"] == []
