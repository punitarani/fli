"""Tests for core parser utilities."""

import pytest

from fli.core.parsers import ParseError, parse_airlines, parse_emissions, parse_sort_by
from fli.models import Airline, EmissionsFilter, SortBy


class TestParseEmissions:
    """Tests for parse_emissions."""

    def test_all(self):
        assert parse_emissions("ALL") == EmissionsFilter.ALL

    def test_less(self):
        assert parse_emissions("LESS") == EmissionsFilter.LESS

    def test_case_insensitive(self):
        assert parse_emissions("all") == EmissionsFilter.ALL
        assert parse_emissions("Less") == EmissionsFilter.LESS

    def test_invalid(self):
        with pytest.raises(ParseError, match="Invalid EmissionsFilter"):
            parse_emissions("NONE")

    def test_invalid_random(self):
        with pytest.raises(ParseError, match="Invalid EmissionsFilter"):
            parse_emissions("HIGH")


class TestParseAirlinesWithAlliances:
    """Tests for parse_airlines with alliance codes."""

    def test_alliance_star_alliance(self):
        result = parse_airlines(["STAR_ALLIANCE"])
        assert result == [Airline.STAR_ALLIANCE]

    def test_alliance_oneworld(self):
        result = parse_airlines(["ONEWORLD"])
        assert result == [Airline.ONEWORLD]

    def test_alliance_skyteam(self):
        result = parse_airlines(["SKYTEAM"])
        assert result == [Airline.SKYTEAM]

    def test_alliance_mixed_with_airlines(self):
        result = parse_airlines(["STAR_ALLIANCE", "AA"])
        assert Airline.STAR_ALLIANCE in result
        assert Airline.AA in result


class TestParseSortBy:
    """Tests for parse_sort_by with updated enum values."""

    def test_top_flights(self):
        assert parse_sort_by("TOP_FLIGHTS") == SortBy.TOP_FLIGHTS
        assert SortBy.TOP_FLIGHTS.value == 0

    def test_best(self):
        assert parse_sort_by("BEST") == SortBy.BEST
        assert SortBy.BEST.value == 1

    def test_cheapest(self):
        assert parse_sort_by("CHEAPEST") == SortBy.CHEAPEST
        assert SortBy.CHEAPEST.value == 2

    def test_emissions(self):
        assert parse_sort_by("EMISSIONS") == SortBy.EMISSIONS
        assert SortBy.EMISSIONS.value == 6

    def test_invalid(self):
        with pytest.raises(ParseError, match="Invalid sort_by value"):
            parse_sort_by("NONE")
