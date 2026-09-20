# Fli Python Examples

Runnable Python examples for the [`flights`](https://pypi.org/project/flights/)
library. Each file is standalone and mirrors its TypeScript counterpart in
[`../typescript`](../typescript) where one exists.

> These examples talk to the live Google Flights API. They are rate-limited
> (10 req/s) and results vary with real availability and pricing.

## Setup

```bash
# From the repo root, with uv (recommended — handles dependencies):
uv run python examples/python/basic_one_way_search.py

# Or install the package and run directly:
pip install flights
python examples/python/basic_one_way_search.py
```

`result_processing.py` additionally uses `pandas`, and
`error_handling_with_retries.py` uses `tenacity`:

```bash
pip install pandas tenacity
```

## Examples

### Core

| File | What it shows |
|------|---------------|
| `basic_one_way_search.py` | Minimal one-way search and result printing |
| `round_trip_search.py` | Round trip; results returned as `(outbound, return)` tuples |
| `date_range_search.py` | Cheapest dates across a flexible window |
| `multi_city_search.py` | Three-leg multi-city itinerary |
| `advanced_filters_search.py` | Alliances, airline exclusions, layover bounds, currency/locale |
| `error_handling_with_retries.py` | Retry logic with exponential backoff |

### Going further

| File | What it shows |
|------|---------------|
| `complex_flight_search.py` | Multiple passengers, airlines, layover restrictions, business class |
| `time_restrictions_search.py` | Departure/arrival time windows |
| `date_search_with_preferences.py` | Day-of-week / weekend-only date filtering |
| `complex_round_trip_validation.py` | Validation-heavy round trip with time + layover rules |
| `advanced_date_search_validation.py` | Validated date-range search with stay-length constraints |
| `price_tracking.py` | Monitoring prices across repeated searches |
| `result_processing.py` | Converting results to a pandas DataFrame for analysis |

## Notes

- `FlightSegment` airports are double-nested: `[[Airport.JFK, 0]]`.
- `currency` / `language` / `country` are passed to `search()`, not to the
  filter object.
- Round-trip and multi-city searches return a list of tuples of
  `FlightResult` (one per leg). One-way returns a flat `list[FlightResult]`.
