"""Tests for the URL query-parameter helper used by SearchFlights / SearchDates."""

from fli.search._urls import with_locale_params
from fli.search.flights import _with_locale_params

BASE = "https://www.google.com/_/FlightsFrontendUi/data/x/y"


def test_no_params_returns_url_unchanged():
    assert _with_locale_params(BASE, None, None, None) == BASE


def test_currency_only_appends_curr():
    assert _with_locale_params(BASE, "EUR", None, None) == f"{BASE}?curr=EUR"


def test_currency_is_uppercased():
    assert _with_locale_params(BASE, "eur", None, None) == f"{BASE}?curr=EUR"


def test_language_only():
    assert _with_locale_params(BASE, None, "en-GB", None) == f"{BASE}?hl=en-GB"


def test_country_is_uppercased():
    assert _with_locale_params(BASE, None, None, "gb") == f"{BASE}?gl=GB"


def test_all_three_params_in_order():
    out = _with_locale_params(BASE, "JPY", "ja", "JP")
    assert out == f"{BASE}?curr=JPY&hl=ja&gl=JP"


def test_appends_to_existing_query_string():
    out = _with_locale_params(f"{BASE}?foo=bar", "EUR", None, None)
    assert out == f"{BASE}?foo=bar&curr=EUR"


# ---------------------------------------------------------------------------
# Percent-encoding — these guard against query-param injection and non-ASCII
# inputs breaking the URL. The helper uses ``urllib.parse.quote(safe='')``
# so every special character must be escaped.
# ---------------------------------------------------------------------------


def test_public_import_path_works():
    """The encoder is reachable via the new ``fli.search._urls`` module."""
    assert with_locale_params(BASE, "EUR", None, None) == f"{BASE}?curr=EUR"


def test_non_ascii_language_is_percent_encoded():
    """A CJK locale code round-trips as percent-escaped UTF-8 bytes."""
    out = with_locale_params(BASE, None, "日本", None)
    # 日本 → E6 97 A5 E6 9C AC
    assert out == f"{BASE}?hl=%E6%97%A5%E6%9C%AC"


def test_latin1_special_chars_encoded():
    """Accented input is escaped, not passed through."""
    out = with_locale_params(BASE, None, "fr-CA é", None)
    assert "%20" in out  # space
    assert "%C3%A9" in out  # é


def test_query_param_injection_blocked():
    """An ``&`` in the input value cannot create a new parameter."""
    out = with_locale_params(BASE, None, "en&gl=XX", None)
    # The ``&`` must be encoded so Google sees one hl param, not two.
    assert "&gl=XX" not in out
    assert "%26gl%3DXX" in out


def test_equals_sign_in_value_encoded():
    """``=`` in the value must be percent-encoded, not interpreted."""
    out = with_locale_params(BASE, None, "x=y", None)
    assert "?hl=x%3Dy" in out
