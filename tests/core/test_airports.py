"""Tests for airport search functionality."""

from fli.core.airports import search_airports


class TestSearchAirports:
    """Tests for the search_airports function."""

    def test_exact_iata_code(self):
        """Exact IATA code returns the airport."""
        results = search_airports("JFK")
        assert len(results) >= 1
        assert results[0].code == "JFK"
        assert results[0].match_type == "code"

    def test_iata_code_case_insensitive(self):
        """IATA code search is case-insensitive."""
        results = search_airports("jfk")
        assert len(results) >= 1
        assert results[0].code == "JFK"

    def test_city_name_new_york(self):
        """City name 'new york' returns NYC airports."""
        results = search_airports("new york")
        codes = [r.code for r in results]
        assert "JFK" in codes
        assert "LGA" in codes
        assert "EWR" in codes

    def test_city_name_tokyo(self):
        """City name 'tokyo' returns Tokyo airports."""
        results = search_airports("tokyo")
        codes = [r.code for r in results]
        assert "NRT" in codes
        assert "HND" in codes

    def test_city_name_london(self):
        """City name 'london' returns London airports."""
        results = search_airports("london")
        codes = [r.code for r in results]
        assert "LHR" in codes
        assert "LGW" in codes

    def test_airport_name_substring(self):
        """Searching by airport name substring works."""
        results = search_airports("heathrow")
        assert len(results) >= 1
        assert results[0].code == "LHR"

    def test_airport_name_san_francisco(self):
        """Searching 'san francisco' matches via both city map and name."""
        results = search_airports("san francisco")
        codes = [r.code for r in results]
        assert "SFO" in codes

    def test_partial_city_name(self):
        """Partial city name matches."""
        results = search_airports("new yo")
        codes = [r.code for r in results]
        assert "JFK" in codes

    def test_iata_prefix(self):
        """Partial IATA code prefix matches."""
        results = search_airports("SF")
        codes = [r.code for r in results]
        assert "SFO" in codes

    def test_empty_query(self):
        """Empty query returns empty list."""
        assert search_airports("") == []
        assert search_airports("   ") == []

    def test_no_results(self):
        """Query with no matches returns empty list."""
        results = search_airports("xyznonexistent")
        assert results == []

    def test_limit(self):
        """Limit parameter caps results."""
        results = search_airports("international", limit=3)
        assert len(results) <= 3

    def test_code_match_highest_priority(self):
        """Exact code match scores higher than name match."""
        results = search_airports("LAX")
        assert results[0].code == "LAX"
        assert results[0].match_type == "code"

    def test_city_abbreviation(self):
        """City abbreviations work."""
        results = search_airports("sf")
        codes = [r.code for r in results]
        assert "SFO" in codes

    def test_nyc_abbreviation(self):
        """NYC abbreviation works."""
        results = search_airports("nyc")
        codes = [r.code for r in results]
        assert "JFK" in codes
