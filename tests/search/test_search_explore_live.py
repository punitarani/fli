"""Live-API integration tests for the Explore search.

These hit Google's live ``GetExploreDestinations`` endpoint and confirm the
request recipe (same-origin headers + ``curr`` param) still works and that
responses parse into sensible results.

As live network tests they may be skipped or re-run on flake; do not include
in pre-commit CI.
"""

from datetime import datetime, timedelta

import pytest
from tenacity import retry, stop_after_attempt, wait_exponential

from fli.models import ExplorePlace, ExploreSearchFilters
from fli.search import SearchExplore
from fli.search.exceptions import SearchRejectedError

# GetExploreDestinations is a FlightsFrontendService RPC behind the same
# signed-header gate as #223: measured 2026-11-11, Google refused 8 of 20
# identical requests with error 13, in bursts long enough to beat this
# file's three-attempt retry about once in five runs. Only that rejection is
# expected — ``raises=`` keeps any other failure (a parse regression, wrong
# currency) a real failure, and an unlucky-free run still passes as XPASS.
pytestmark = [
    pytest.mark.live,
    pytest.mark.xfail(
        raises=SearchRejectedError,
        strict=False,
        reason="GetExploreDestinations intermittently answers error 13 (#223)",
    ),
]

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


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
def _search_with_retry(client: SearchExplore, filters: ExploreSearchFilters, **kw):
    result = client.search(filters, **kw)
    if result is None or not result.destinations:
        raise ValueError("Empty explore result, retrying...")
    return result


@pytest.fixture
def client():
    return SearchExplore()


def test_explore_returns_many_priced_destinations(client):
    result = _search_with_retry(client, _filters(), currency="USD")

    assert result.origin_name
    assert len(result.destinations) >= 20
    priced = [d for d in result.destinations if d.price is not None]
    assert len(priced) >= 1
    for d in result.destinations:
        assert d.mid.startswith(("/m/", "/g/"))
        assert d.name
    for d in priced:
        assert d.price > 0
        assert d.destination_airport
        assert d.departure_date


def test_currency_param_changes_prices(client):
    usd = _search_with_retry(client, _filters(), currency="USD")
    gbp = _search_with_retry(client, _filters(), currency="GBP")

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
