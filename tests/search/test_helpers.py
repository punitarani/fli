"""Unit tests for fli.search._helpers — the defensive accessors used by all decoders."""

from __future__ import annotations

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


class TestAsBool:
    def test_true_returns_true(self):
        assert as_bool(True) is True

    def test_false_returns_false(self):
        # False is a valid bool — must NOT return None.
        result = as_bool(False)
        assert result is False
        assert result is not None

    def test_int_one_returns_none(self):
        assert as_bool(1) is None

    def test_int_zero_returns_none(self):
        assert as_bool(0) is None

    def test_string_true_returns_none(self):
        assert as_bool("true") is None

    def test_none_returns_none(self):
        assert as_bool(None) is None


class TestAsStr:
    def test_non_empty_string_returned(self):
        assert as_str("hello") == "hello"

    def test_empty_string_returns_none(self):
        assert as_str("") is None

    def test_int_returns_none(self):
        assert as_str(42) is None

    def test_none_returns_none(self):
        assert as_str(None) is None

    def test_whitespace_only_string_returned(self):
        # Only the empty string is rejected; whitespace-only is kept.
        assert as_str("  ") == "  "

    def test_bool_returns_none(self):
        assert as_str(True) is None


class TestAsInt:
    def test_positive_int_returned(self):
        assert as_int(5) == 5

    def test_zero_returned(self):
        assert as_int(0) == 0

    def test_negative_int_returned(self):
        assert as_int(-3) == -3

    def test_bool_true_returns_none(self):
        # bool is a subclass of int in Python — must be explicitly rejected.
        assert as_int(True) is None

    def test_bool_false_returns_none(self):
        assert as_int(False) is None

    def test_float_returns_none(self):
        assert as_int(3.0) is None

    def test_string_returns_none(self):
        assert as_int("5") is None

    def test_none_returns_none(self):
        assert as_int(None) is None


class TestAsNonNegativeInt:
    def test_zero_returned(self):
        assert as_non_negative_int(0) == 0

    def test_positive_returned(self):
        assert as_non_negative_int(42) == 42

    def test_negative_returns_none(self):
        assert as_non_negative_int(-1) is None

    def test_bool_returns_none(self):
        # Inherits as_int rejection of bools.
        assert as_non_negative_int(True) is None

    def test_none_returns_none(self):
        assert as_non_negative_int(None) is None
