"""Regression tests for the hotel HTML parser.

Guards against the specific bugs that broke upstream `fast_hotels`:
- `$1` prices from promotional-copy regex matches.
- "Photos"/FAQ/carousel cards surfacing as hotels.
- Implausibly low prices slipping through.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from fli.search.hotels import _parse_hotels_html, _parse_price

FIXTURES = Path(__file__).parent.parent / "fixtures"
FIXTURE = FIXTURES / "google_hotels_salvador.html.gz"
FIXTURE_ALT_LAYOUT = FIXTURES / "google_hotels_la_alt_layout.html.gz"


def _load(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"Fixture missing: {path}")
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return fh.read()


def _load_fixture() -> str:
    return _load(FIXTURE)


def test_parse_price_handles_commas_and_decimals():
    assert _parse_price("$1,234") == 1234.0
    assert _parse_price("$1,234.50") == 1234.5
    assert _parse_price("$231") == 231.0
    assert _parse_price("From $99/night") == 99.0
    assert _parse_price("no price here") is None


def test_parser_returns_plausible_hotels_only():
    hotels = _parse_hotels_html(_load_fixture())
    assert hotels, "parser should return at least some hotels"
    for h in hotels:
        assert h["name"], "every hotel must have a non-empty name"
        assert h["price"] >= 10.0, (
            f"implausible price {h['price']} on {h['name']!r} — parser regressed"
        )
        assert h["name"].lower() not in {"photos", "faq", "overview"}


def test_parser_drops_garbage_cards():
    hotels = _parse_hotels_html(_load_fixture())
    names = {h["name"].lower() for h in hotels}
    # These are container labels that used to leak through the upstream parser.
    for junk in ("photos", "faq", "deals", "overview", "about"):
        assert junk not in names


def test_parser_does_not_confuse_great_deal_strikethroughs():
    """Reproduce the Captain Morgan Hostel case.

    'GREAT DEAL $16 ... 33% less' — the old regex captured '$1633' or '$1' off
    the card text.
    """
    hotels = _parse_hotels_html(_load_fixture())
    hostel = next((h for h in hotels if "captain morgan" in h["name"].lower()), None)
    if hostel is None:
        pytest.skip("hostel not in fixture — skipping targeted regression check")
    assert 5 <= hostel["price"] <= 100, (
        f"Captain Morgan Hostel price {hostel['price']} is implausible"
    )


def test_parser_handles_alt_layout():
    """Google serves a second card layout (h2.Cx32Ud + span.W9vOvb.nDkDDb).

    Hit intermittently, especially for queries with children > 0. An earlier
    version of the parser returned 0 hotels for these responses because it
    only matched the primary layout's selectors.
    """
    hotels = _parse_hotels_html(_load(FIXTURE_ALT_LAYOUT))
    assert len(hotels) >= 5, f"alt layout should yield hotels, got {len(hotels)}"
    for h in hotels:
        assert h["price"] >= 10.0
        assert h["name"]
