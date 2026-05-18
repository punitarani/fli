"""Unit tests for fli.search._helpers — the defensive accessors used by all decoders."""

from __future__ import annotations

import pytest

from fli.search._helpers import as_bool, as_int, as_non_negative_int, as_str, safe_get


class TestSafeGet:
    def test_returns_element_at_valid_index(self):
        assert safe_get([1, 2, 3], 1) == 2

    def test_returns_none_for_out_of_bounds(self):
        assert safe_get([1], 5) is None

    def test_returns_none_for_negative_index(self):
        assert safe_get([1, 2], -1) is None

    def test_returns_none_for_non_list_string(self):
        assert safe_get("abc", 0) is None

    def test_returns_none_for_non_list_dict(self):
        assert safe_get({"a": 1}, 0) is None

    def test_returns_none_for_none_seq(self):
        assert safe_get(None, 0) is None

    def test_returns_none_for_empty_list(self):
        assert safe_get([], 0) is None

    def test_returns_falsy_zero_at_index(self):
        # 0 at a valid index is NOT None — callers rely on this distinction.
        assert safe_get([False, 0, None], 1) == 0

    def test_returns_false_at_index(self):
        assert safe_get([False, 0, None], 0) is False

    def test_returns_none_element_at_index(self):
        # None stored at a valid index should be returned as-is.
        assert safe_get([1, None, 3], 1) is None


@pytest.mark.parametrize(
    "val, expected",
    [
        (True, True),
        # False is a valid bool — must NOT return None.
        (False, False),
        (1, None),
        (0, None),
        ("true", None),
        (None, None),
    ],
)
def test_as_bool(val, expected):
    assert as_bool(val) is expected


@pytest.mark.parametrize(
    "val, expected",
    [
        ("hello", "hello"),
        # Only the empty string is rejected; whitespace-only is kept.
        ("  ", "  "),
        ("", None),
        (42, None),
        (True, None),
        (None, None),
    ],
)
def test_as_str(val, expected):
    assert as_str(val) == expected


@pytest.mark.parametrize(
    "val, expected",
    [
        (5, 5),
        (0, 0),
        (-3, -3),
        # bool is a subclass of int in Python — must be explicitly rejected.
        (True, None),
        (False, None),
        (3.0, None),
        ("5", None),
        (None, None),
    ],
)
def test_as_int(val, expected):
    assert as_int(val) == expected


@pytest.mark.parametrize(
    "val, expected",
    [
        (0, 0),
        (42, 42),
        (-1, None),
        # Inherits as_int rejection of bools.
        (True, None),
        (None, None),
    ],
)
def test_as_non_negative_int(val, expected):
    assert as_non_negative_int(val) == expected
