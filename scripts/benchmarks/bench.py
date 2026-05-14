"""Run the full ``fli`` parsing & concurrency benchmark suite.

Usage:

    uv run python scripts/benchmarks/bench.py [--iterations N] [--latency-ms M]

The suite times four scenarios end-to-end against a deterministic mocked
HTTP layer:

1. ``parse_flight_row`` — pure CPU work on captured fixtures.
2. ``SearchFlights.search`` (one-way) — single HTTP call + row parse.
3. ``SearchFlights.search`` (round-trip, ``top_n=5``) — exercises the
   multi-leg expansion path.
4. ``SearchDates.search`` (180-day range, splits into 3 chunks).

Every scenario records wall-clock mean / p50 / p95, CPU time, and the
peak in-flight request count seen by the mocked client (so we can verify
parallel paths actually overlap HTTP).
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fli.models import (  # noqa: E402
    Airport,
    DateSearchFilters,
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
    TripType,
)
from fli.search import SearchDates, SearchFlights  # noqa: E402
from fli.search._decoders import parse_flight_row  # noqa: E402
from scripts.benchmarks._harness import (  # noqa: E402
    BenchResult,
    print_table,
    speedup,
    time_callable,
)
from scripts.benchmarks._mocks import FakeClient, load_fixture  # noqa: E402

# ---------------------------------------------------------------------------
# Scenario helpers
# ---------------------------------------------------------------------------


def _extract_rows(fixture: str) -> list:
    outer = json.loads(fixture.lstrip(")]}'"))
    inner_str = outer[0][2]
    if not inner_str:
        return []
    inner = json.loads(inner_str)
    return [item for i in (2, 3) if isinstance(inner[i], list) for item in inner[i][0]]


def _synthetic_date_fixture(days: int = 61) -> str:
    """Build a minimal ``GetCalendarGraph`` body shaped like the live API.

    The date-search parser reads ``data[-1]`` as a list of
    ``[date_str, _, [[None, price], currency_token]]`` entries.
    """
    base = datetime(2026, 7, 1)
    entries = [
        [
            (base + timedelta(days=i)).strftime("%Y-%m-%d"),
            None,
            [[None, 150 + i], "USD0.000"],
        ]
        for i in range(days)
    ]
    # inner JSON: dates_data is read as data[-1] — match that shape.
    inner = json.dumps([None, None, entries])
    return ")]}'\n" + json.dumps([["wrb.fr", None, inner]])


def _one_way_filters(date: str | None = None) -> FlightSearchFilters:
    date = date or (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    return FlightSearchFilters(
        trip_type=TripType.ONE_WAY,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LAX, 0]],
                travel_date=date,
            )
        ],
    )


def _round_trip_filters() -> FlightSearchFilters:
    outbound = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    return_d = (datetime.now() + timedelta(days=37)).strftime("%Y-%m-%d")
    return FlightSearchFilters(
        trip_type=TripType.ROUND_TRIP,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LAX, 0]],
                travel_date=outbound,
            ),
            FlightSegment(
                departure_airport=[[Airport.LAX, 0]],
                arrival_airport=[[Airport.JFK, 0]],
                travel_date=return_d,
            ),
        ],
    )


def _date_filters(days: int) -> DateSearchFilters:
    start = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    end = (datetime.now() + timedelta(days=7 + days - 1)).strftime("%Y-%m-%d")
    return DateSearchFilters(
        trip_type=TripType.ONE_WAY,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport.JFK, 0]],
                arrival_airport=[[Airport.LAX, 0]],
                travel_date=start,
            )
        ],
        from_date=start,
        to_date=end,
    )


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def bench_parse_row(rows: list, iterations: int) -> BenchResult:
    """Pure CPU benchmark — parse all rows from a captured response."""

    def run():
        return [parse_flight_row(r) for r in rows]

    return time_callable(run, iterations=iterations, name="parse_flight_row (loop)")


def bench_one_way(fixture: str, iterations: int, latency_ms: float) -> BenchResult:
    """Single HTTP + parse path — provides a "no expansion" baseline."""
    fake = FakeClient(fixture, latency_ms=latency_ms)

    def run():
        search = SearchFlights()
        search.client = fake  # inject stub
        return search.search(_one_way_filters())

    res = time_callable(run, iterations=iterations, name="search one-way")
    res.payload = {"calls": fake.calls, "concurrent_max": fake.concurrent_high_water}
    return res


def bench_round_trip(fixture: str, iterations: int, latency_ms: float) -> BenchResult:
    """Multi-leg expansion — the headline scenario for parallelism."""
    fake = FakeClient(fixture, latency_ms=latency_ms)

    def run():
        search = SearchFlights()
        search.client = fake
        return search.search(_round_trip_filters(), top_n=5)

    res = time_callable(run, iterations=iterations, name="search round-trip top_n=5")
    res.payload = {"calls": fake.calls, "concurrent_max": fake.concurrent_high_water}
    return res


def bench_date_range(fixture: str, iterations: int, latency_ms: float, days: int) -> BenchResult:
    """Date-range search across multiple chunks."""
    fake = FakeClient(fixture, latency_ms=latency_ms)

    def run():
        search = SearchDates()
        search.client = fake
        return search.search(deepcopy(_date_filters(days)))

    res = time_callable(run, iterations=iterations, name=f"search dates {days}d (chunks)")
    res.payload = {"calls": fake.calls, "concurrent_max": fake.concurrent_high_water}
    return res


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument(
        "--latency-ms",
        type=float,
        default=120.0,
        help="Simulated per-request HTTP latency (ms).",
    )
    parser.add_argument(
        "--date-range-days",
        type=int,
        default=180,
        help="Date-range span — affects chunk count (61-day max per chunk).",
    )
    args = parser.parse_args()

    flight_fixture = load_fixture("flight_search_jfk_lax_oneway_usd.bin")
    date_fixture = _synthetic_date_fixture(days=61)
    rows = _extract_rows(flight_fixture)

    print(f"Loaded {len(rows)} flight rows from fixture.")
    print(
        f"Latency per simulated request: {args.latency_ms:.0f}ms; "
        f"iterations: {args.iterations}; date range: {args.date_range_days}d.\n"
    )

    parse_res = bench_parse_row(rows, iterations=max(args.iterations * 20, 50))
    one_way = bench_one_way(flight_fixture, args.iterations, args.latency_ms)
    round_trip = bench_round_trip(flight_fixture, args.iterations, args.latency_ms)
    date_range = bench_date_range(
        date_fixture, args.iterations, args.latency_ms, days=args.date_range_days
    )

    print_table(
        "Benchmark results (wall-clock ms; lower is better)",
        [parse_res, one_way, round_trip, date_range],
    )

    print("\nObserved concurrency:")
    for r in (one_way, round_trip, date_range):
        meta = r.payload or {}
        print(
            f"  {r.name:30s}  calls/run={meta.get('calls', 0) / max(r.iterations, 1):5.1f}  "
            f"peak in-flight={meta.get('concurrent_max', 1)}"
        )

    # Print quick interpretive line
    parsing_throughput = len(rows) * 1000.0 / max(parse_res.wall_mean, 1e-6)
    print(
        f"\nParser throughput: {parsing_throughput:,.0f} rows/sec "
        f"({len(rows)} rows / {parse_res.wall_mean:.2f}ms)"
    )

    expected_seq_round_trip = args.latency_ms * (1 + 5)  # initial + 5 expansions
    print(
        f"Expected sequential round-trip latency: ~{expected_seq_round_trip:.0f}ms; "
        f"measured: {round_trip.wall_mean:.0f}ms; "
        f"saved: {expected_seq_round_trip - round_trip.wall_mean:.0f}ms"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# Helpers exposed for use from a comparison driver.
__all__ = [
    "bench_date_range",
    "bench_one_way",
    "bench_parse_row",
    "bench_round_trip",
    "speedup",
    "_extract_rows",
    "_one_way_filters",
    "_round_trip_filters",
    "_date_filters",
]
