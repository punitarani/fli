"""Tests for the currency parser helper."""

import pytest

from fli.core import parse_currency
from fli.core.parsers import ParseError


class TestParseCurrency:
    """Tests for parse_currency."""

    def test_none(self):
        assert parse_currency(None) is None

    def test_empty(self):
        assert parse_currency("") is None

    def test_known_uppercase(self):
        assert parse_currency("USD") == "USD"

    def test_known_lowercase(self):
        assert parse_currency("eur") == "EUR"

    def test_strip_whitespace(self):
        assert parse_currency("  gbp  ") == "GBP"

    def test_unknown_three_letter_passes_through(self):
        # Currencies not yet in the enum still passthrough — Google may
        # support newer codes than the enum lists.
        assert parse_currency("xpf") == "XPF"

    def test_invalid_too_short(self):
        with pytest.raises(ParseError, match="Expected a 3-letter ISO 4217 code"):
            parse_currency("EU")

    def test_invalid_too_long(self):
        with pytest.raises(ParseError, match="Expected a 3-letter ISO 4217 code"):
            parse_currency("EUROS")

    def test_invalid_digits(self):
        with pytest.raises(ParseError, match="Expected a 3-letter ISO 4217 code"):
            parse_currency("US1")
