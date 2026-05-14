"""Tests for the URL query-parameter helper used by SearchFlights / SearchDates."""

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
