"""Capture live GetShoppingResults / GetExploreDestinations responses for snapshot tests.

Usage::

    uv run python scripts/capture_fixtures.py [--out-dir tests/search/fixtures]

The script hits Google's live API with each scenario defined in ``SCENARIOS``
below and writes the raw response body to a binary fixture. Snapshot tests
in ``tests/search/test_snapshot_fixtures.py`` replay these bodies through
the same parser used by ``SearchFlights.search`` — so updating the
fixtures (re-running this script after Google changes anything) keeps the
offline tests in sync with reality.

When you add a new scenario, also add a corresponding fixture in
``test_snapshot_fixtures.py``.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from fli.models import (
    Airline,
    Airport,
    Alliance,
    ExplorePlace,
    ExploreSearchFilters,
    FlightSearchFilters,
    FlightSegment,
    LayoverRestrictions,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
    TripType,
)
from fli.search import SearchExplore, SearchFlights
from fli.search._urls import with_locale_params
from fli.search.client import get_client


def _future(days: int) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


def _seg(dep: Airport, arr: Airport, days: int = 45) -> list[FlightSegment]:
    return [
        FlightSegment(
            departure_airport=[[dep, 0]],
            arrival_airport=[[arr, 0]],
            travel_date=_future(days),
        )
    ]


# Each scenario: name → (filters factory, currency).
SCENARIOS: dict[str, tuple[Callable[[], FlightSearchFilters], str]] = {
    "flight_search_jfk_lax_oneway_usd": (
        lambda: FlightSearchFilters(
            passenger_info=PassengerInfo(adults=1),
            flight_segments=_seg(Airport.JFK, Airport.LAX),
            stops=MaxStops.NON_STOP,
        ),
        "USD",
    ),
    "flight_search_jfk_fra_oneworld": (
        lambda: FlightSearchFilters(
            passenger_info=PassengerInfo(adults=1),
            flight_segments=_seg(Airport.JFK, Airport.FRA),
            alliances=[Alliance.ONEWORLD],
        ),
        "USD",
    ),
    "flight_search_buf_ath_min_layover_120": (
        lambda: FlightSearchFilters(
            passenger_info=PassengerInfo(adults=1),
            flight_segments=_seg(Airport.BUF, Airport.ATH),
            layover_restrictions=LayoverRestrictions(min_duration=120),
        ),
        "USD",
    ),
    "flight_search_jfk_lax_exclude_dl": (
        lambda: FlightSearchFilters(
            passenger_info=PassengerInfo(adults=1),
            flight_segments=_seg(Airport.JFK, Airport.LAX),
            airlines_exclude=[Airline.DL],
        ),
        "USD",
    ),
    "flight_search_jfk_lax_eur": (
        lambda: FlightSearchFilters(
            passenger_info=PassengerInfo(adults=1),
            flight_segments=_seg(Airport.JFK, Airport.LAX),
            stops=MaxStops.NON_STOP,
        ),
        "EUR",
    ),
    # Issue #165 regression: premium-cabin RT with family pax. Google
    # returns rows with an empty price head; the parser must surface
    # them with ``price=None`` rather than dropping the whole batch.
    "flight_search_lax_lhr_rt_biz_2a1c": (
        lambda: FlightSearchFilters(
            trip_type=TripType.ROUND_TRIP,
            passenger_info=PassengerInfo(adults=2, children=1),
            flight_segments=[
                FlightSegment(
                    departure_airport=[[Airport.LAX, 0]],
                    arrival_airport=[[Airport.LHR, 0]],
                    travel_date=_future(45),
                ),
                FlightSegment(
                    departure_airport=[[Airport.LHR, 0]],
                    arrival_airport=[[Airport.LAX, 0]],
                    travel_date=_future(59),
                ),
            ],
            stops=MaxStops.ANY,
            seat_type=SeatType.BUSINESS,
            sort_by=SortBy.BEST,
            show_all_results=True,
        ),
        "USD",
    ),
}

# Explore scenarios hit GetExploreDestinations, which additionally requires
# SearchExplore's same-origin headers (see fli/search/explore.py).
EXPLORE_SCENARIOS: dict[str, tuple[Callable[[], ExploreSearchFilters], str]] = {
    "explore_lon_southern_europe": (
        lambda: ExploreSearchFilters(
            origin=ExplorePlace(mid="/m/04jpl", type_code=4),  # London
            destination=ExplorePlace(mid="/m/0250wj", type_code=6),  # Southern Europe
            departure_date=_future(30),
        ),
        "USD",
    ),
}


def main() -> int:
    """CLI entry point — capture fixtures listed in ``SCENARIOS``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        default="tests/search/fixtures",
        help="Directory to write fixture .bin files into",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        help="Only capture this scenario (can be repeated). Default: all.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    client = get_client()

    # name -> (filters factory, currency, endpoint URL, extra headers).
    registry: dict[str, tuple[Callable[[], object], str, str, dict | None]] = {
        name: (factory, currency, SearchFlights.BASE_URL, None)
        for name, (factory, currency) in SCENARIOS.items()
    }
    registry.update(
        {
            name: (factory, currency, SearchExplore.BASE_URL, SearchExplore.DEFAULT_HEADERS)
            for name, (factory, currency) in EXPLORE_SCENARIOS.items()
        }
    )

    selected = args.scenario or list(registry)
    for name in selected:
        if name not in registry:
            print(f"!! Unknown scenario: {name}")
            continue
        factory, currency, base_url, headers = registry[name]
        filters = factory()
        encoded = filters.encode()
        url = with_locale_params(base_url, currency, None, None)
        r = client.post(
            url=url,
            data=f"f.req={encoded}",
            impersonate="chrome",
            allow_redirects=True,
            **({"headers": headers} if headers else {}),
        )
        path = out_dir / f"{name}.bin"
        path.write_bytes(r.content)
        print(f"  {name}: {len(r.content)} bytes -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
