from fli.core import (
    extract_currency_from_price_token,
    extract_price_from_price_token,
    format_price,
    format_price_axis_label,
)

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


def test_extract_price_from_price_token():
    """Tokens should expose the protobuf-encoded display price."""
    # The shopping token encodes 11740 minor units (cents) with currency USD,
    # which renders as 117.40 in display units.
    assert extract_price_from_price_token(SHOPPING_TOKEN) == 117.40


def test_extract_price_from_price_token_invalid():
    """Invalid tokens should fail closed instead of raising."""
    assert extract_price_from_price_token("not-a-valid-token") is None


def test_extract_price_from_price_token_empty():
    """Empty/None tokens should return None instead of raising."""
    assert extract_price_from_price_token(None) is None
    assert extract_price_from_price_token("") is None


def _build_price_token(amount: int, currency: str) -> str:
    """Encode a minimal Google Flights-shaped price token for tests."""
    import base64

    def varint(n: int) -> bytes:
        out = bytearray()
        while True:
            byte = n & 0x7F
            n >>= 7
            if n:
                out.append(byte | 0x80)
            else:
                out.append(byte)
                break
        return bytes(out)

    def length_delim(payload: bytes) -> bytes:
        return varint(len(payload)) + payload

    inner = (
        bytes([(1 << 3) | 0])
        + varint(amount)
        + bytes([(3 << 3) | 2])
        + length_delim(currency.encode("ascii"))
    )
    outer = bytes([(3 << 3) | 2]) + length_delim(inner)
    return base64.urlsafe_b64encode(outer).rstrip(b"=").decode("ascii")


def test_extract_price_from_price_token_zero_decimal_currency():
    """Zero-decimal currencies (KRW, JPY) should not be divided by 100."""
    krw_token = _build_price_token(150000, "KRW")
    assert extract_price_from_price_token(krw_token) == 150000.0
    assert extract_currency_from_price_token(krw_token) == "KRW"

    jpy_token = _build_price_token(15000, "JPY")
    assert extract_price_from_price_token(jpy_token) == 15000.0
    assert extract_currency_from_price_token(jpy_token) == "JPY"


def test_format_price_uses_currency_code():
    """Price formatting should use ISO currency codes for symbols."""
    assert format_price(118, "HKD") == "HK$118.00"


def test_format_price_without_currency():
    """Missing currency should still render a plain numeric value."""
    assert format_price(118, None) == "118.00"


def test_format_price_axis_label_uses_single_currency_code():
    """Charts should show the single returned currency code when consistent."""
    assert format_price_axis_label(["EUR", "EUR"]) == "Price (EUR)"


def test_format_price_axis_label_omits_mixed_currency_code():
    """Charts should avoid claiming a single currency for mixed result sets."""
    assert format_price_axis_label(["EUR", "USD"]) == "Price"
