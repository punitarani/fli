"""Offline tests for the Explore search wire parsing and payload join.

The hand-built bodies replicate the ``GetExploreDestinations`` framing:
``)]}'`` prefix + byte-counted length-prefixed ``wrb.fr`` chunks (see
``fli/search/_wire.py``). Length headers count UTF-8 BYTES — the Kraków
destination below pins that behaviour for non-ASCII names.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from fli.search import explore as explore_module
from fli.search._decoders import (
    is_explore_destinations_chunk,
    is_explore_prices_chunk,
    parse_explore_destinations_chunk,
    parse_explore_prices_chunk,
)
from fli.search.exceptions import SearchParseError, SearchRejectedError
from fli.search.explore import EXPLORE_ATTEMPTS, SearchExplore

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# Wire-body builders
# ---------------------------------------------------------------------------


class _FakeResponse:
    __slots__ = ("text", "status_code")

    def __init__(self, text: str):
        self.text = text
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    """Serves ``texts`` in order, repeating the last one once they run out."""

    def __init__(self, *texts: str):
        self._texts = list(texts)
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"url": url, **kwargs})
        index = min(len(self.calls), len(self._texts)) - 1
        return _FakeResponse(self._texts[index])


def _frame(inner: Any) -> str:
    """One length-prefixed wrb.fr frame carrying ``inner`` as its payload."""
    outer = json.dumps([["wrb.fr", None, json.dumps(inner, separators=(",", ":"))]])
    # The length header counts the payload bytes plus the newline on each
    # side of it (the reader consumes `length - 1` after the header's \n).
    return f"{len(outer.encode('utf-8')) + 2}\n{outer}\n"


def _body(*inners: Any) -> str:
    return ")]}'\n\n" + "".join(_frame(inner) for inner in inners)


def _dest_record(
    mid: str,
    name: str,
    country: str | None = None,
    departure: str | None = "2026-09-10",
    arrival: str | None = "2026-09-10",
) -> list:
    record: list = [None] * 29
    record[0] = mid
    record[1] = [10.5, 20.25]
    record[2] = name
    record[3] = "https://thumb.example/t.jpg"
    record[4] = country
    record[7] = "https://hero.example/h.jpg"
    record[11] = departure
    record[28] = arrival
    return record


def _dest_chunk(records: list, region: str = "Europe", origin: str = "London") -> list:
    return [
        [None, [1, 2, 3], 0, "search_token", "session_token"],
        None,
        [region, [[47.0, 29.6], [27.4, -31.4]]],
        [records],
        None,
        [[[None, 50], [None, 1500]]],
        [[origin, [51.5, -0.12], "/m/04jpl", "/m/04jpl", "ChIJplaceid"]],
        "continuation_token",
        None,
    ]


def _price_record(
    mid: str,
    price: float | None,
    airline: str = "FR",
    stops: int = 0,
    duration: int = 100,
    airport: str = "XXX",
) -> list:
    record: list = [None] * 15
    record[0] = mid
    record[1] = [[None, price], "token-not-a-real-protobuf"]
    record[6] = [airline, f"{airline} Air", stops, duration, None, airport, "/m/04jpl", None, 0]
    record[9] = price is not None
    return record


def _price_chunk(records: list) -> list:
    return [[None, None, 1, "search_token"], None, None, None, [records], None, None, None, None]


# ---------------------------------------------------------------------------
# Chunk classification
# ---------------------------------------------------------------------------


def test_chunk_classification():
    dest = _dest_chunk([_dest_record("/m/0491y", "Kraków", "Poland")])
    price = _price_chunk([_price_record("/m/0491y", 18)])
    assert is_explore_destinations_chunk(dest)
    assert not is_explore_prices_chunk(dest)
    assert is_explore_prices_chunk(price)
    assert not is_explore_destinations_chunk(price)
    for junk in (None, [], [None] * 9, ["wrb.fr"], 42):
        assert not is_explore_destinations_chunk(junk)
        assert not is_explore_prices_chunk(junk)


def test_malformed_destination_records_skipped():
    good = _dest_record("/m/0491y", "Kraków", "Poland")
    no_name = _dest_record("/m/xxxx", "ignored")
    no_name[2] = None
    not_a_mid = _dest_record("KRK", "Kraków")
    chunk = _dest_chunk([good, no_name, not_a_mid, "not-a-list", None])
    meta, destinations = parse_explore_destinations_chunk(chunk)
    assert [d.mid for d in destinations] == ["/m/0491y"]
    assert meta["region_name"] == "Europe"
    assert meta["origin_name"] == "London"
    assert meta["price_slider_min"] == 50
    assert meta["price_slider_max"] == 1500


def test_negative_price_record_omitted():
    """merge_explore_payloads skips model validation, so the decoder must."""
    chunk = _price_chunk([_price_record("/m/0491y", -5)])
    assert parse_explore_prices_chunk(chunk, default_currency="USD") == {}


def test_price_record_without_fare_omitted():
    chunk = _price_chunk([_price_record("/m/0491y", 18), _price_record("/m/04v3q", None)])
    prices = parse_explore_prices_chunk(chunk, default_currency="USD")
    assert set(prices) == {"/m/0491y"}
    assert prices["/m/0491y"]["price"] == 18
    assert prices["/m/0491y"]["currency"] == "USD"  # fake token -> fallback
    assert prices["/m/0491y"]["destination_airport"] == "XXX"


# ---------------------------------------------------------------------------
# End-to-end parse through SearchExplore (stubbed client)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    """Record Explore's error-13 backoff instead of sleeping through it."""
    sleeps: list[float] = []
    monkeypatch.setattr(explore_module.time, "sleep", sleeps.append)
    return sleeps


def _search_with_body(*bodies: str, destination: Any = None) -> tuple[Any, _FakeClient]:
    from datetime import datetime, timedelta

    from fli.models import Airport, ExploreSearchFilters

    search = SearchExplore()
    fake = _FakeClient(*bodies)
    search.client = fake
    extra = {"destination": destination} if destination is not None else {}
    filters = ExploreSearchFilters(
        origin=Airport.LHR,
        departure_date=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
        **extra,
    )
    return search.search(filters, currency="USD"), fake


DESTS = [
    _dest_record("/m/0491y", "Kraków", "Poland"),
    _dest_record("/m/04v3q", "Malta", "Malta"),
    _dest_record("/m/056_y", "Unpriced Town", "Nowhere"),
]
PRICES = [
    _price_record("/m/0491y", 18, airline="FR", airport="KRK"),
    _price_record("/m/04v3q", 132, airline="VY", stops=1, duration=430, airport="MLA"),
]


@pytest.mark.parametrize("order", ["dest_first", "price_first"])
def test_two_payload_join_in_either_order(order):
    chunks = [_dest_chunk(DESTS), _price_chunk(PRICES)]
    if order == "price_first":
        chunks.reverse()
    result, fake = _search_with_body(_body(*chunks))

    assert result is not None
    assert result.region_name == "Europe"
    assert result.origin_name == "London"
    assert [d.name for d in result.destinations] == ["Kraków", "Malta", "Unpriced Town"]

    krakow = result.destinations[0]
    assert krakow.price == 18
    assert krakow.airline == "FR"
    assert krakow.destination_airport == "KRK"
    assert krakow.country == "Poland"
    assert krakow.latitude == 10.5

    unpriced = result.destinations[2]
    assert unpriced.price is None
    assert unpriced.price_unknown
    assert unpriced.airline is None

    # The endpoint's same-origin requirement must always be satisfied.
    headers = fake.calls[0]["headers"]
    assert headers["x-same-domain"] == "1"
    assert headers["origin"] == "https://www.google.com"


def test_records_accumulate_across_many_chunks():
    """Large regions stream records across many chunks (24 observed live)."""
    body = _body(
        _dest_chunk(DESTS[:1]),
        _price_chunk(PRICES[:1]),
        _dest_chunk(DESTS[1:], region="Europe"),
        _price_chunk(PRICES[1:]),
    )
    result, _ = _search_with_body(body)
    assert [d.name for d in result.destinations] == ["Kraków", "Malta", "Unpriced Town"]
    assert [d.price for d in result.destinations] == [18, 132, None]


@pytest.mark.parametrize("body", [")]}'\n\nnot json at all", _body([None] * 9)])
def test_unparseable_body_raises(body):
    with pytest.raises(SearchParseError, match="no parseable destination"):
        _search_with_body(body)


def _error_body(code: int) -> str:
    return ")]}'\n\n" + json.dumps([["wrb.fr", None, None, None, None, [code]]])


def test_error_13_on_every_attempt_raises_retryable(_no_retry_sleep):
    """Explore's error 13 is intermittent: retried, then reported as retryable."""
    with pytest.raises(SearchRejectedError) as exc:
        _search_with_body(_error_body(13))
    assert exc.value.code == 13
    assert exc.value.retryable is True
    assert "intermittently" in str(exc.value)
    assert "bgr" not in str(exc.value)
    assert len(_no_retry_sleep) == EXPLORE_ATTEMPTS - 1


def test_error_13_then_success_returns_results(_no_retry_sleep):
    good = _body(_dest_chunk(DESTS), _price_chunk(PRICES))
    result, fake = _search_with_body(_error_body(13), _error_body(13), good)
    assert len(fake.calls) == 3
    assert [d.price for d in result.destinations] == [18, 132, None]
    assert _no_retry_sleep == [1.0, 2.0]


def test_error_3_is_not_retried(_no_retry_sleep):
    """INVALID_ARGUMENT is Google refusing the request itself, not a transient gate."""
    with pytest.raises(SearchRejectedError) as exc:
        _search_with_body(_error_body(3))
    assert exc.value.code == 3
    assert exc.value.retryable is False
    assert "INVALID_ARGUMENT" in str(exc.value)
    assert "bgr" not in str(exc.value)
    assert _no_retry_sleep == []


def test_empty_body_for_raw_mid_destination_mentions_cities():
    from fli.models import ExplorePlace

    with pytest.raises(SearchParseError, match="may also be a city"):
        _search_with_body(_body([None] * 9), destination=ExplorePlace(mid="/m/04jpl"))


# ---------------------------------------------------------------------------
# Captured-fixture replay (durable assertions only — see snapshot drift policy)
# ---------------------------------------------------------------------------


def test_fixture_replay_lon_southern_europe():
    fixture = FIXTURES_DIR / "explore_lon_southern_europe.bin"
    if not fixture.exists():
        pytest.skip("explore fixture not captured")

    result, _ = _search_with_body(fixture.read_text(encoding="utf-8"))
    assert result is not None
    assert result.region_name
    assert result.origin_name
    assert len(result.destinations) >= 20
    priced = [d for d in result.destinations if d.price is not None]
    unpriced = [d for d in result.destinations if d.price is None]
    assert len(priced) >= 1
    assert len(unpriced) >= 1
    for d in result.destinations:
        assert d.mid.startswith(("/m/", "/g/"))
        assert d.name
    for d in priced:
        assert d.price > 0
        assert d.currency
