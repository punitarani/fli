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


class TestParseAirlinesSplitting:
    """Tests for parse_airlines accepting comma- and whitespace-separated codes per item.

    Motivated by the documented `--airlines BA,KL` (single token) and
    `--airlines "BA KL"` (quoted) CLI forms, plus the same tolerance now extended
    to MCP callers passing combined strings.
    """

    def test_comma_separated_in_one_item(self):
        result = parse_airlines(["BA,KL"])
        assert result == [Airline.BA, Airline.KL]

    def test_space_separated_in_one_item(self):
        result = parse_airlines(["BA KL"])
        assert result == [Airline.BA, Airline.KL]

    def test_tab_separator(self):
        result = parse_airlines(["BA\tKL"])
        assert result == [Airline.BA, Airline.KL]

    def test_collapses_consecutive_separators(self):
        result = parse_airlines(["BA,,KL", "AA  UA"])
        assert result == [Airline.BA, Airline.KL, Airline.AA, Airline.UA]

    def test_strips_leading_and_trailing_separators(self):
        result = parse_airlines([",BA,", " KL "])
        assert result == [Airline.BA, Airline.KL]

    def test_mixed_forms(self):
        result = parse_airlines(["BA,KL", "LH"])
        assert result == [Airline.BA, Airline.KL, Airline.LH]

    def test_repeated_items_still_work(self):
        # Backwards compat: `--airlines BA --airlines KL` arrives as ["BA", "KL"].
        result = parse_airlines(["BA", "KL"])
        assert result == [Airline.BA, Airline.KL]

    def test_lowercase_in_split_is_uppercased(self):
        result = parse_airlines(["ba,kl"])
        assert result == [Airline.BA, Airline.KL]

    def test_numeric_prefix_in_split(self):
        result = parse_airlines(["BA,3F"])
        assert result == [Airline.BA, Airline._3F]

    def test_invalid_code_in_split_propagates(self):
        with pytest.raises(ParseError, match="Invalid airline code: 'XXX'"):
            parse_airlines(["BA,XXX"])

    def test_raises_when_only_commas(self):
        with pytest.raises(ParseError, match="No valid airline codes"):
            parse_airlines([","])

    def test_raises_when_only_whitespace(self):
        with pytest.raises(ParseError, match="No valid airline codes"):
            parse_airlines([" "])

    def test_raises_when_only_empty_string(self):
        with pytest.raises(ParseError, match="No valid airline codes"):
            parse_airlines([""])

    def test_raises_when_only_separators_across_items(self):
        with pytest.raises(ParseError, match="No valid airline codes"):
            parse_airlines(["", " ", ","])

    def test_none_input_still_returns_none(self):
        assert parse_airlines(None) is None

    def test_empty_list_still_returns_none(self):
        assert parse_airlines([]) is None


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
