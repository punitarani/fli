from fli.core import extract_currency_from_price_token, format_price, format_price_axis_label

SHOPPING_TOKEN = (
    "CjRIQktCNmV1UjNqNjhBR043X0FCRy0tLS0tLS0tLS12dGpkN0FBQUFBR25JcWZNS2pGTTBBEgZV"
    "QTIyMDkaCgjcWxACGgNVU0Q4HHDcWw=="
)


def test_extract_currency_from_price_token():
    """Google Flights price tokens should expose the returned ISO currency code."""
    assert extract_currency_from_price_token(SHOPPING_TOKEN) == "USD"


def test_extract_currency_from_price_token_invalid():
    """Invalid tokens should fail closed instead of raising."""
    assert extract_currency_from_price_token("not-a-valid-token") is None


def test_format_price_uses_currency_code():
    """Price formatting should use ISO currency codes for symbols."""
    assert format_price(118, "HKD") == "HK$118.00"


def test_format_price_without_currency():
    """Missing currency should still render a plain numeric value."""
    assert format_price(118, None) == "118.00"


def test_format_price_with_none_amount_and_currency():
    """A None price renders as ``"<CCY> —"`` (issue #165 premium-RT case)."""
    assert format_price(None, "USD") == "USD —"


def test_format_price_with_none_amount_no_currency():
    """A None price with no currency code falls back to a bare em dash."""
    assert format_price(None, None) == "—"


def test_format_price_with_none_amount_empty_currency():
    """Empty-string currency is treated as missing (falsy), not uppercased."""
    assert format_price(None, "") == "—"


def test_format_price_axis_label_uses_single_currency_code():
    """Charts should show the single returned currency code when consistent."""
    assert format_price_axis_label(["EUR", "EUR"]) == "Price (EUR)"


def test_format_price_axis_label_omits_mixed_currency_code():
    """Charts should avoid claiming a single currency for mixed result sets."""
    assert format_price_axis_label(["EUR", "USD"]) == "Price"
