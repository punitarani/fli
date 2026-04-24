"""Tests for multi-airport support in MCP server helpers."""

import pytest

from fli.core.parsers import ParseError
from fli.mcp.server import _resolve_airports
from fli.models import Airport


class TestResolveAirports:
    """Tests for the comma-separated airport resolver."""

    def test_single_code(self):
        assert _resolve_airports("JFK") == [Airport.JFK]

    def test_multiple_codes(self):
        assert _resolve_airports("JFK,LGA") == [Airport.JFK, Airport.LGA]

    def test_multiple_codes_with_whitespace(self):
        assert _resolve_airports(" JFK , LGA ") == [Airport.JFK, Airport.LGA]

    def test_lowercase_codes(self):
        assert _resolve_airports("jfk,lga") == [Airport.JFK, Airport.LGA]

    def test_mixed_case_codes(self):
        assert _resolve_airports("jFk,Lga") == [Airport.JFK, Airport.LGA]

    def test_empty_string_raises(self):
        with pytest.raises(ParseError):
            _resolve_airports("")

    def test_only_commas_raises(self):
        with pytest.raises(ParseError):
            _resolve_airports(",,,")

    def test_only_whitespace_raises(self):
        with pytest.raises(ParseError):
            _resolve_airports("   ")

    def test_invalid_code_raises(self):
        with pytest.raises(ParseError):
            _resolve_airports("INVALID")

    def test_valid_followed_by_invalid_raises(self):
        with pytest.raises(ParseError):
            _resolve_airports("JFK,INVALID")

    def test_preserves_order(self):
        assert _resolve_airports("CDG,LHR,JFK") == [Airport.CDG, Airport.LHR, Airport.JFK]

    def test_three_airports(self):
        assert _resolve_airports("JFK,LGA,EWR") == [Airport.JFK, Airport.LGA, Airport.EWR]
