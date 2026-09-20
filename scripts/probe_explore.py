"""Live probe matrix for the GetExploreDestinations (Explore) endpoint.

Dev tool — hits the live Google API. Run variants with::

    uv run python scripts/probe_explore.py                 # full matrix, tier 1
    uv run python scripts/probe_explore.py --only minimal  # one variant
    uv run python scripts/probe_explore.py --tier 2        # escalate headers
    uv run python scripts/probe_explore.py --save-fixture  # write baseline .bin

The matrix resolves the open reverse-engineering questions recorded in the
Explore plan (see fli/models/google_flights/explore.py):

    R1  do fli's minimal headers work, or is browser ceremony required?
    R2  does the ``curr=`` URL param control the currency?
    R3  are ``["JFK", 0]`` airport-code origins accepted?
    R4  what mid/type does "Anywhere" need?
    R5  what do trip-length-window values mean; does round-trip work?
    R6  region enum seeds — does each curated mid return results?

Escalation tiers (``--tier``): 1 = fli's bare request shape; 2 = + the
``x-same-domain``/``origin``/``referer`` headers; 3 = + the
``soc-*``/``rt=c``/``_reqid`` query params; 4 = + currency via the
``x-goog-ext-259736195-jspb`` header.

FINDINGS (probed live 2026-08-11):
    R1  tier 1 fails with an opaque wrb.fr error ``[13]``. Tier 2 works —
        and ANY ONE of the three headers is sufficient on its own (it is a
        same-origin check). No cookies, no ``at`` XSRF token, no
        ``f.sid``/``bl``/``soc-*``/``rt=c`` needed. SearchExplore sends
        ``x-same-domain: 1`` + ``origin``.
    R2  ``curr=`` works (Malta 132 USD / 114 EUR, plausible FX ratio).
    R3  ``["JFK", 0]`` airport origins work.
    R4  Anywhere = ``["/m/02j71", 6]``; type 4 fails with error 13. A null
        destination slot also works (defaults to a nearby region).
    R5  ``departure_date`` is REQUIRED (error 13 without it). Window is
        ``[4, 23, min_nights, max_nights]``: forcing ``[4,23,14,14]``
        re-prices every destination; dest[28] never moves -> it is the
        outbound ARRIVAL date, not a return date.
    R6  every curated ExploreRegion mid returns results. Responses stream
        across up to 24 wrb.fr chunks — parse ALL chunks, not the first two.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

from fli.models import (
    Airport,
    Alliance,
    BagsFilter,
    ExplorePlace,
    ExploreRegion,
    ExploreSearchFilters,
    MaxStops,
    PriceLimit,
    TripType,
)
from fli.search._urls import with_locale_params
from fli.search._wire import iter_wrb_chunks
from fli.search.client import get_client

BASE_URL = (
    "https://www.google.com/_/FlightsFrontendUi/data/"
    "travel.frontend.flights.FlightsFrontendService/GetExploreDestinations"
)
FIXTURE_PATH = (
    Path(__file__).parent.parent / "tests/search/fixtures/explore_lon_southern_europe.bin"
)

LONDON = ExplorePlace(mid="/m/04jpl", type_code=4)
SOUTHERN_EUROPE = ExplorePlace(mid="/m/0250wj", type_code=6)


def future(days: int = 30) -> str:
    """Return a YYYY-MM-DD date ``days`` from now."""
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


def encode_payload(payload: list) -> str:
    """Encode a raw formatted payload the same way ExploreSearchFilters.encode does."""
    inner = json.dumps(payload, separators=(",", ":"))
    return urllib.parse.quote(json.dumps([None, inner], separators=(",", ":")))


def safe_get(tree, *path, default=None):
    """Walk a positional path into nested lists, returning ``default`` on any miss."""
    for key in path:
        try:
            tree = tree[key]
        except (IndexError, KeyError, TypeError):
            return default
    return tree


def extract(chunks: list) -> tuple[list, dict]:
    """Shape-based extraction of destination and price records from chunks."""
    dests: list = []
    prices: dict = {}
    for chunk in chunks:
        dest_records = safe_get(chunk, 3, 0)
        if isinstance(dest_records, list) and any(
            isinstance(safe_get(r, 0), str)
            and safe_get(r, 0, default="").startswith(("/m/", "/g/"))
            and isinstance(safe_get(r, 2), str)
            for r in dest_records
            if isinstance(r, list)
        ):
            dests.extend(r for r in dest_records if isinstance(r, list))
        price_records = safe_get(chunk, 4, 0)
        if isinstance(price_records, list):
            for r in price_records:
                mid = safe_get(r, 0)
                if isinstance(mid, str) and mid.startswith(("/m/", "/g/")):
                    prices[mid] = r
    return dests, prices


def run_variant(
    name: str,
    payload: list,
    *,
    tier: int,
    currency: str | None = "USD",
    language: str | None = "en",
    country: str | None = "US",
    save_fixture: bool = False,
) -> None:
    """POST one probe payload at the given escalation tier and print the outcome."""
    url = with_locale_params(BASE_URL, currency, language, country)
    headers: dict[str, str] = {}
    if tier >= 2:
        headers.update(
            {
                "x-same-domain": "1",
                "origin": "https://www.google.com",
                "referer": "https://www.google.com/travel/explore",
            }
        )
    if tier >= 3:
        reqid = random.randint(10000, 999999)
        url += f"&soc-app=162&soc-platform=1&soc-device=1&rt=c&_reqid={reqid}"
    if tier >= 4:
        headers["x-goog-ext-259736195-jspb"] = json.dumps(
            ["en", "US", currency or "USD", 1, None, [0], None, None, 1, []],
            separators=(",", ":"),
        )

    client = get_client()
    print(f"\n=== {name} (tier {tier}, curr={currency}) ===")
    try:
        response = client.post(
            url=url,
            data=f"f.req={encode_payload(payload)}",
            impersonate="chrome",
            allow_redirects=True,
            **({"headers": headers} if headers else {}),
        )
    except Exception as e:  # noqa: BLE001 — probe tool, report and continue
        print(f"  REQUEST FAILED: {type(e).__name__}: {e}")
        return

    body = response.text
    chunks = list(iter_wrb_chunks(body))
    dests, prices = extract(chunks)
    priced = [d for d in dests if safe_get(d, 0) in prices]
    print(f"  status={response.status_code} bytes={len(body)} chunks={len(chunks)}")
    print(f"  destinations={len(dests)} priced={len(priced)}")
    for d in priced[:3]:
        mid = safe_get(d, 0)
        p = prices[mid]
        print(
            f"    {safe_get(d, 2)!r:20} {safe_get(d, 4)!r:16}"
            f" price={safe_get(p, 1, 0, 1)}"
            f" airline={safe_get(p, 6, 0)}"
            f" stops={safe_get(p, 6, 2)}"
            f" dur={safe_get(p, 6, 3)}min"
            f" apt={safe_get(p, 6, 5)}"
            f" dep={safe_get(d, 11)} ret={safe_get(d, 28)}"
        )
    unpriced = [d for d in dests if safe_get(d, 0) not in prices]
    if unpriced:
        print(f"    (+{len(unpriced)} unpriced, e.g. {safe_get(unpriced[0], 2)!r})")
    if save_fixture:
        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_PATH.write_bytes(body.encode("utf-8") if isinstance(body, str) else body)
        print(f"  fixture saved -> {FIXTURE_PATH}")


def build_variants() -> dict[str, dict]:
    """Return the probe matrix: name -> {payload, kwargs}."""
    har_full = ExploreSearchFilters(
        origin=LONDON,
        destination=SOUTHERN_EUROPE,
        departure_date=future(30),
        price_limit=PriceLimit(max_price=900),
        bags=BagsFilter(carry_on=True),
        trip_length_window=[4, 23, 0, 23],
        stops=MaxStops.NON_STOP,
        alliances=[Alliance.ONEWORLD],
        max_duration=600,
    )
    minimal = ExploreSearchFilters(
        origin=LONDON, destination=SOUTHERN_EUROPE, departure_date=future(30)
    )
    airport_origin = ExploreSearchFilters(
        origin=Airport.JFK, destination=ExploreRegion.EUROPE, departure_date=future(30)
    )
    anywhere = ExploreSearchFilters(
        origin=LONDON, destination=ExploreRegion.ANYWHERE, departure_date=future(30)
    )
    round_trip = ExploreSearchFilters(
        origin=LONDON,
        destination=SOUTHERN_EUROPE,
        trip_type=TripType.ROUND_TRIP,
        departure_date=future(30),
        trip_length_window=[4, 23, 0, 23],
    )
    round_trip_fortnight = ExploreSearchFilters(
        origin=LONDON,
        destination=SOUTHERN_EUROPE,
        trip_type=TripType.ROUND_TRIP,
        departure_date=future(30),
        trip_length_window=[4, 23, 14, 14],
    )

    gb_locale = {"currency": "GBP", "language": "en-GB", "country": "GB"}
    variants: dict[str, dict] = {
        "har_full": {"payload": har_full.format(), "kwargs": gb_locale},
        "minimal": {"payload": minimal.format(), "kwargs": {"save_fixture": True}},
        "curr_usd": {"payload": minimal.format(), "kwargs": {"currency": "USD"}},
        "curr_eur": {"payload": minimal.format(), "kwargs": {"currency": "EUR"}},
        "airport_origin": {"payload": airport_origin.format(), "kwargs": {}},
        "anywhere_t6": {"payload": anywhere.format(), "kwargs": {}},
        "round_trip": {"payload": round_trip.format(), "kwargs": {}},
        "round_trip_fortnight": {"payload": round_trip_fortnight.format(), "kwargs": {}},
    }

    # Payload mutations that the model can't (or refuses to) express.
    no_date = minimal.format()
    no_date[3][13][0][6] = None  # confirmed: error 13 without a date
    variants["no_date"] = {"payload": no_date, "kwargs": {}}

    anywhere_t4 = anywhere.format()
    anywhere_t4[3][13][0][1] = [[["/m/02j71", 4]]]  # confirmed: error 13
    variants["anywhere_t4"] = {"payload": anywhere_t4, "kwargs": {}}

    dest_null = anywhere.format()
    dest_null[3][13][0][1] = None
    variants["dest_null"] = {"payload": dest_null, "kwargs": {}}

    # Curated region enum verification (R6).
    for region in ExploreRegion:
        if region in (ExploreRegion.ANYWHERE, ExploreRegion.SOUTHERN_EUROPE):
            continue
        f = ExploreSearchFilters(origin=LONDON, destination=region, departure_date=future(30))
        variants[f"region_{region.name.lower()}"] = {"payload": f.format(), "kwargs": {}}

    return variants


def main() -> int:
    """Run the selected probe variants."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", type=int, default=1, choices=[1, 2, 3, 4])
    parser.add_argument("--only", type=str, help="comma-separated variant names")
    parser.add_argument(
        "--save-fixture", action="store_true", help="save the 'minimal' variant body"
    )
    args = parser.parse_args()

    variants = build_variants()
    selected = args.only.split(",") if args.only else list(variants)
    unknown = [name for name in selected if name not in variants]
    if unknown:
        print(f"Unknown variants: {unknown}. Available: {list(variants)}")
        return 1

    for name in selected:
        spec = variants[name]
        kwargs = dict(spec["kwargs"])
        if not args.save_fixture:
            kwargs.pop("save_fixture", None)
        run_variant(name, spec["payload"], tier=args.tier, **kwargs)

    return 0


if __name__ == "__main__":
    sys.exit(main())
