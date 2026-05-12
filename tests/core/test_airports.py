"""Tests for airport search functionality."""

from fli.core.airports import AirportMatch, search_airports
from fli.models import Airport


class TestSearchAirports:
    def test_exact_iata_code(self):
        results = search_airports("JFK")
        assert len(results) >= 1
        assert results[0].code is Airport.JFK
        assert results[0].match_type == "iata_exact"
        assert results[0].score == 100.0

    def test_iata_code_case_insensitive(self):
        results = search_airports("jfk")
        assert results[0].code is Airport.JFK

    def test_iata_code_with_surrounding_whitespace(self):
        results = search_airports("  JFK  ")
        assert results[0].code is Airport.JFK
        assert results[0].match_type == "iata_exact"

    def test_city_name_new_york(self):
        codes = {r.code for r in search_airports("new york")}
        assert {Airport.JFK, Airport.LGA, Airport.EWR} <= codes

    def test_city_name_tokyo(self):
        codes = {r.code for r in search_airports("tokyo")}
        assert {Airport.NRT, Airport.HND} <= codes

    def test_city_name_london_returns_all_five(self):
        codes = {r.code for r in search_airports("london")}
        assert {Airport.LHR, Airport.LGW, Airport.STN, Airport.LTN, Airport.LCY} <= codes

    def test_airport_name_substring(self):
        results = search_airports("heathrow")
        assert results[0].code is Airport.LHR
        assert results[0].match_type == "name"

    def test_san_francisco_dedupes_across_priorities(self):
        # "san francisco" matches both Priority 2 (city map) and Priority 4
        # (airport name substring). seen_codes must prevent duplicates.
        results = search_airports("san francisco")
        codes = [r.code for r in results]
        assert codes.count(Airport.SFO) == 1

    def test_partial_city_name(self):
        codes = {r.code for r in search_airports("new yo")}
        assert Airport.JFK in codes

    def test_iata_prefix_distinct_from_exact(self):
        # "JF" is not an exact IATA code, not a city alias, and not a substring
        # of any airport name -- so only Priority 5 (iata_prefix) fires.
        results = search_airports("JF")
        jfk_match = next(r for r in results if r.code is Airport.JFK)
        assert jfk_match.match_type == "iata_prefix"
        assert jfk_match.score == 60.0
        # All results for this query should be prefix matches.
        assert all(r.match_type == "iata_prefix" for r in results)

    def test_empty_query(self):
        assert search_airports("") == []
        assert search_airports("   ") == []

    def test_no_results(self):
        assert search_airports("xyznonexistent") == []

    def test_invalid_limit_returns_empty(self):
        assert search_airports("JFK", limit=0) == []
        assert search_airports("JFK", limit=-1) == []

    def test_limit_caps_results(self):
        assert len(search_airports("international", limit=3)) <= 3

    def test_default_limit_is_ten(self):
        # "international" appears in many airport names; default limit is 10.
        assert len(search_airports("international")) <= 10

    def test_priority_ordering(self):
        # Exact code (100) must rank above any city/name/prefix match for the same query family.
        results = search_airports("LAX")
        assert results[0].code is Airport.LAX
        assert results[0].match_type == "iata_exact"
        # Scores in the returned list must be monotonically non-increasing.
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_priority_3_skipped_when_exact_city_match(self):
        # When query is an exact city, only Priority 2 (score 90) should fire,
        # not Priority 3 (score 80). All city-matched results should be 90.
        results = search_airports("london")
        city_results = [r for r in results if r.match_type == "city"]
        assert city_results, "expected at least one city-typed match for 'london'"
        assert all(r.score == 90.0 for r in city_results)

    def test_name_score_decreases_with_position(self):
        # The 0.1-per-position weight means a match at position 0 outscores one later.
        results = search_airports("international")
        name_matches = [r for r in results if r.match_type == "name"]
        if len(name_matches) >= 2:
            scores = [r.score for r in name_matches]
            assert scores == sorted(scores, reverse=True)
            assert all(s <= 70.0 for s in scores)

    def test_city_abbreviation(self):
        codes = {r.code for r in search_airports("sf")}
        assert Airport.SFO in codes

    def test_nyc_abbreviation(self):
        codes = {r.code for r in search_airports("nyc")}
        assert Airport.JFK in codes


class TestAirportMatch:
    def test_frozen(self):
        m = AirportMatch(code=Airport.JFK, name="JFK Airport", match_type="iata_exact", score=100.0)
        try:
            m.score = 0.0
        except Exception:
            return
        raise AssertionError("AirportMatch should be frozen")

    def test_equality(self):
        a = AirportMatch(code=Airport.JFK, name="JFK", match_type="city", score=90.0)
        b = AirportMatch(code=Airport.JFK, name="JFK", match_type="city", score=90.0)
        assert a == b

    def test_rejects_invalid_match_type(self):
        try:
            AirportMatch(code=Airport.JFK, name="JFK", match_type="bogus", score=50.0)  # type: ignore[arg-type]
        except Exception:
            return
        raise AssertionError("AirportMatch should reject unknown match_type")

    def test_rejects_score_out_of_range(self):
        try:
            AirportMatch(code=Airport.JFK, name="JFK", match_type="iata_exact", score=101.0)
        except Exception:
            return
        raise AssertionError("AirportMatch should reject score > 100")
