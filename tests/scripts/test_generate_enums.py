"""Tests for ``scripts/generate_enums.py``.

Loads the script as a module (it lives outside the ``fli`` package and has
no ``__init__.py``, so it can't be imported normally) to unit-test the
disambiguation and uniqueness-assertion helpers in isolation, without
needing to regenerate the real ``fli/models/airport.py`` / ``airline.py``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_enums.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_enums", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generate_enums = _load_module()


class TestDisambiguateNames:
    """``_disambiguate_names`` must only touch members of a duplicate group."""

    def test_unique_names_untouched(self):
        entries = [("AAA", "Anaa Airport"), ("JFK", "John F. Kennedy Airport")]
        assert generate_enums._disambiguate_names(entries) == entries

    def test_all_members_of_duplicate_group_suffixed(self):
        # NAH and OKA share "Naha Airport" in data/airports.csv today — use
        # the same pattern (three-way duplicate) to prove every member of
        # the group is suffixed, not just the second-and-later ones.
        entries = [
            ("NAH", "Naha Airport"),
            ("OKA", "Naha Airport"),
            ("ZZZ", "Naha Airport"),
        ]
        result = generate_enums._disambiguate_names(entries)
        assert result == [
            ("NAH", "Naha Airport (NAH)"),
            ("OKA", "Naha Airport (OKA)"),
            ("ZZZ", "Naha Airport (ZZZ)"),
        ]

    def test_mixed_unique_and_duplicate(self):
        entries = [
            ("AAA", "Unique Airport"),
            ("NCL", "Newcastle Airport"),
            ("NTL", "Newcastle Airport"),
        ]
        result = generate_enums._disambiguate_names(entries)
        assert result == [
            ("AAA", "Unique Airport"),
            ("NCL", "Newcastle Airport (NCL)"),
            ("NTL", "Newcastle Airport (NTL)"),
        ]

    def test_empty_entries(self):
        assert generate_enums._disambiguate_names([]) == []


class TestAssertUnique:
    """The generator must refuse to emit an enum with colliding members."""

    def test_passes_for_unique_codes_and_names(self):
        entries = [("AAA", "Anaa Airport"), ("JFK", "John F. Kennedy Airport")]
        generate_enums._assert_unique(entries, enum_name="Airport")  # no raise

    def test_raises_on_duplicate_names_after_disambiguation(self):
        # Simulates a CSV that lists the same (code, name) pair twice —
        # ``_disambiguate_names`` appends the same code both times, so the
        # resulting names still collide and must be rejected.
        entries = [("ABC", "Foo Airport (ABC)"), ("ABC", "Foo Airport (ABC)")]
        with pytest.raises(ValueError, match="ABC"):
            generate_enums._assert_unique(entries, enum_name="Airport")

    def test_raises_on_duplicate_sanitized_codes(self):
        # "A.B" and "A B" both sanitize (non-alnum -> "_") to "A_B".
        entries = [("A.B", "Airport One"), ("A B", "Airport Two")]
        with pytest.raises(ValueError, match="A_B"):
            generate_enums._assert_unique(entries, enum_name="Airport")

    def test_allows_digit_prefixed_airline_codes(self):
        # Airline codes may start with a digit; the sanitizer prefixes an
        # underscore for those, which must not itself be flagged as a
        # collision between e.g. "3F" and "_3F".
        entries = [("3F", "Airline One"), ("4F", "Airline Two")]
        generate_enums._assert_unique(entries, enum_name="Airline")  # no raise
