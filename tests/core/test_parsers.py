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


@pytest.mark.parametrize(
    "code, expected",
    [
        ("STAR_ALLIANCE", Airline.STAR_ALLIANCE),
        ("ONEWORLD", Airline.ONEWORLD),
        ("SKYTEAM", Airline.SKYTEAM),
    ],
)
def test_parse_airlines_alliance(code, expected):
    assert parse_airlines([code]) == [expected]


def test_parse_airlines_alliance_mixed_with_airlines():
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

    @pytest.mark.parametrize("codes", [[","], [" "], [""], ["", " ", ","]])
    def test_raises_when_no_valid_codes(self, codes):
        with pytest.raises(ParseError, match="No valid airline codes"):
            parse_airlines(codes)

    def test_none_input_still_returns_none(self):
        assert parse_airlines(None) is None

    def test_empty_list_still_returns_none(self):
        assert parse_airlines([]) is None


@pytest.mark.parametrize(
    "value, expected",
    [
        ("TOP_FLIGHTS", SortBy.TOP_FLIGHTS),
        ("BEST", SortBy.BEST),
        ("CHEAPEST", SortBy.CHEAPEST),
        ("EMISSIONS", SortBy.EMISSIONS),
    ],
)
def test_parse_sort_by(value, expected):
    assert parse_sort_by(value) == expected


def test_parse_sort_by_invalid():
    with pytest.raises(ParseError, match="Invalid sort_by value"):
        parse_sort_by("NONE")
