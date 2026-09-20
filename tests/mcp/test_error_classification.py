"""Table-driven tests for fli.mcp.errors.classify_error.

Requirement: this suite must fail if a new exception class is added to
fli.search.exceptions without giving it a classification here. That is
enforced by iterating SearchClientError.__subclasses__() at collection
time (see TestEverySearchClientErrorSubclassIsClassified) instead of
hand-listing the classes — a new subclass shows up in the parametrize
list automatically and fails until _EXPECTED is updated for it.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from fli.core.parsers import ParseError
from fli.mcp.errors import ErrorClassification, classify_error
from fli.search.exceptions import (
    SearchClientError,
    SearchConnectionError,
    SearchHTTPError,
    SearchParseError,
    SearchRejectedError,
    SearchTimeoutError,
    SearchUnsupportedError,
)


def _all_subclasses(cls: type) -> set[type]:
    """Recursively collect every currently-defined subclass of ``cls``."""
    seen: set[type] = set()
    stack = [cls]
    while stack:
        current = stack.pop()
        for sub in current.__subclasses__():
            if sub not in seen:
                seen.add(sub)
                stack.append(sub)
    return seen


# One representative-instance factory + expected (error_type, retryable) per
# exception class defined in fli.search.exceptions. SearchHTTPError is
# exercised separately below across several status codes since its
# `retryable` depends on the status code, not just the type.
_EXPECTED: dict[type, tuple[type[BaseException], tuple[str, bool]]] = {
    SearchClientError: (SearchClientError("boom"), ("search_error", False)),
    SearchTimeoutError: (SearchTimeoutError("timed out"), ("timeout_error", True)),
    SearchConnectionError: (SearchConnectionError("no route"), ("connection_error", True)),
    SearchHTTPError: (SearchHTTPError("bad response", status_code=500), ("http_error", True)),
    SearchRejectedError: (SearchRejectedError(13), ("rejected_error", False)),
    SearchUnsupportedError: (SearchUnsupportedError("multi-city"), ("unsupported_error", False)),
    SearchParseError: (SearchParseError("no ds:1 payload"), ("blocked_error", False)),
}


class TestEverySearchClientErrorSubclassIsClassified:
    """Guards against a new fli.search.exceptions class going unclassified."""

    @pytest.mark.parametrize(
        "exc_class",
        sorted(_all_subclasses(SearchClientError) | {SearchClientError}, key=lambda c: c.__name__),
    )
    def test_class_has_expected_mapping(self, exc_class):
        assert exc_class in _EXPECTED, (
            f"{exc_class.__name__} is a SearchClientError subclass with no entry in "
            "tests/mcp/test_error_classification.py::_EXPECTED — classify_error() in "
            "fli/mcp/errors.py needs an isinstance branch for it, and this table needs "
            "the expected (error_type, retryable) pair."
        )

    @pytest.mark.parametrize(
        "exc_class",
        sorted(_all_subclasses(SearchClientError) | {SearchClientError}, key=lambda c: c.__name__),
    )
    def test_class_classifies_as_expected(self, exc_class):
        instance, (expected_type, expected_retryable) = _EXPECTED[exc_class]
        result = classify_error(instance)
        assert result.error_type == expected_type
        assert result.retryable == expected_retryable


class TestSearchHTTPErrorRetryability:
    """retryable depends on the status code: 429 and 5xx are, everything else isn't."""

    @pytest.mark.parametrize(
        "status_code,expected_retryable",
        [
            (429, True),
            (500, True),
            (502, True),
            (503, True),
            (599, True),
            (400, False),
            (403, False),
            (404, False),
            (None, False),
        ],
    )
    def test_retryable_by_status(self, status_code, expected_retryable):
        exc = SearchHTTPError("Google Flights returned an error response", status_code=status_code)
        result = classify_error(exc)
        assert result.error_type == "http_error"
        assert result.retryable is expected_retryable

    def test_http_status_field_present_when_known(self):
        result = classify_error(SearchHTTPError("boom", status_code=503))
        assert result.http_status == 503
        assert result.as_fields()["http_status"] == 503

    def test_http_status_field_absent_when_unknown(self):
        result = classify_error(SearchHTTPError("boom", status_code=None))
        assert result.http_status is None
        assert "http_status" not in result.as_fields()


class TestNonSearchExceptions:
    """Pydantic ValidationError, ParseError, bare ValueError, and bare Exception."""

    def test_pydantic_validation_error(self):
        class _Model(BaseModel):
            passengers: int

        try:
            _Model(passengers="not-a-number")
        except ValidationError as exc:
            result = classify_error(exc)
        assert result == ErrorClassification("validation_error", retryable=False)

    def test_core_parse_error(self):
        result = classify_error(ParseError("unknown airport code 'ZZZ'"))
        assert result == ErrorClassification("validation_error", retryable=False)

    def test_bare_value_error_93_date_cap(self):
        # Mirrors the message SearchDates.search() raises when a date range
        # covers more than MAX_DATES_PER_SEARCH (93) dates — a plain
        # ValueError, not a ParseError or SearchClientError subclass.
        result = classify_error(
            ValueError("This date search covers 120 dates, above the 93-date limit.")
        )
        assert result == ErrorClassification("validation_error", retryable=False)

    def test_bare_exception_is_unexpected(self):
        result = classify_error(Exception("something nobody classified"))
        assert result == ErrorClassification("unexpected_error", retryable=False)

    def test_unrelated_builtin_exception_is_unexpected(self):
        result = classify_error(KeyError("missing"))
        assert result == ErrorClassification("unexpected_error", retryable=False)


class TestErrorClassificationAsFields:
    def test_no_http_status_key_when_not_http_error(self):
        fields = classify_error(SearchTimeoutError("slow")).as_fields()
        assert fields == {"error_type": "timeout_error", "retryable": True}
