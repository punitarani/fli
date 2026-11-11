"""Live-API integration tests for the Explore search.

These hit Google's live ``GetExploreDestinations`` endpoint and confirm the
request recipe (same-origin headers + ``curr`` param) still works and that
responses parse into sensible results.

As live network tests they may be skipped or re-run on flake; do not include
in pre-commit CI.
"""

from datetime import datetime, timedelta

import pytest

from fli.models import ExplorePlace, ExploreSearchFilters
from fli.models.google_flights.explore import KG_MID_PREFIXES
from fli.search import SearchExplore
from fli.search.exceptions import SearchRejectedError

pytestmark = pytest.mark.live

LONDON = ExplorePlace(mid="/m/04jpl", type_code=4)
SOUTHERN_EUROPE = ExplorePlace(mid="/m/0250wj", type_code=6)


def _future(days: int) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


def _filters() -> ExploreSearchFilters:
    return ExploreSearchFilters(
        origin=LONDON,
        destination=SOUTHERN_EUROPE,
        departure_date=_future(45),
    )


def _search(client: SearchExplore, filters: ExploreSearchFilters, **kw):
    """Run one Explore search, xfailing only on Google's intermittent refusal.

    Google refuses a share of Explore requests with error 13 (about 40% in
    live checks on 2026-11-11, in clusters). SearchExplore already retries
    that and raises ``retryable=True`` once every attempt is refused; only
    that case is reported as xfail, so the daily canary still goes red when
    Explore breaks in any other way (a bad parse, wrong prices, error 3 from
    a request shape Google no longer accepts, or any other code).
    """
    try:
        return client.search(filters, **kw)
    except SearchRejectedError as exc:
        if exc.retryable:
            pytest.xfail(f"Google refused every Explore attempt with error {exc.code}")
        raise


@pytest.fixture
def client():
    return SearchExplore()


def test_explore_returns_many_priced_destinations(client):
    result = _search(client, _filters(), currency="USD")

    assert result.origin_name
    assert len(result.destinations) >= 20
    priced = [d for d in result.destinations if d.price is not None]
    assert len(priced) >= 1
    for d in result.destinations:
        assert d.mid.startswith(KG_MID_PREFIXES)
        assert d.name
    for d in priced:
        assert d.price > 0
        assert d.destination_airport
        assert d.departure_date


def test_currency_param_changes_prices(client):
    usd = _search(client, _filters(), currency="USD")
    gbp = _search(client, _filters(), currency="GBP")

    usd_prices = {d.mid: d.price for d in usd.destinations if d.price is not None}
    gbp_prices = {d.mid: d.price for d in gbp.destinations if d.price is not None}
    common = set(usd_prices) & set(gbp_prices)
    assert len(common) >= 5

    # GBP has been worth more than USD for decades — if that inverts, the
    # currency knob is broken long before this assertion is.
    cheaper_in_gbp = sum(1 for mid in common if gbp_prices[mid] < usd_prices[mid])
    assert cheaper_in_gbp > len(common) / 2

    currencies = {d.currency for d in usd.destinations if d.price is not None}
    assert currencies == {"USD"}
