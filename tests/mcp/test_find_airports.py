"""Tests for the MCP find_airports tool."""

from fli.mcp.server import _find_airports_impl


class TestFindAirports:
    def test_exact_code_returns_structured_result(self):
        result = _find_airports_impl("JFK")
        assert result["success"] is True
        assert result["query"] == "JFK"
        assert result["count"] >= 1
        top = result["airports"][0]
        assert top["code"] == "JFK"
        assert top["match_type"] == "iata_exact"
        assert "name" in top and isinstance(top["name"], str)

    def test_city_query_returns_multiple_airports(self):
        result = _find_airports_impl("new york")
        codes = {a["code"] for a in result["airports"]}
        assert {"JFK", "LGA", "EWR"} <= codes
        assert all(
            a["match_type"] == "city"
            for a in result["airports"]
            if a["code"] in {"JFK", "LGA", "EWR"}
        )

    def test_no_results_returns_empty_list_success(self):
        result = _find_airports_impl("xyznonexistent")
        assert result["success"] is True
        assert result["count"] == 0
        assert result["airports"] == []

    def test_limit_caps_results(self):
        result = _find_airports_impl("international", limit=3)
        assert len(result["airports"]) <= 3
        assert result["count"] == len(result["airports"])

    def test_invalid_limit_returns_empty_success(self):
        # _find_airports_impl forwards limit; search_airports handles <1 by returning [].
        result = _find_airports_impl("JFK", limit=0)
        assert result["success"] is True
        assert result["count"] == 0
