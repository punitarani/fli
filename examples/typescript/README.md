# Fli TypeScript Examples

Runnable TypeScript examples for the [`fli-js`](https://www.npmjs.com/package/fli-js)
library. Each file is standalone and mirrors its Python counterpart in
[`../python`](../python).

> These examples talk to the live Google Flights API. They are rate-limited
> (10 req/s) and results vary with real availability and pricing.

## Setup

```bash
cd examples/typescript
bun install          # or: npm install / pnpm install
```

## Run

With [Bun](https://bun.sh) (recommended — runs `.ts` directly):

```bash
bun run basic_one_way_search.ts
# or via the package scripts:
bun run basic         # one-way
bun run round-trip    # round trip
bun run dates         # cheapest dates in a range
bun run multi-city    # 3-leg itinerary
bun run advanced      # alliances + exclusions + locale
bun run errors        # client tuning + typed error handling
```

With Node, run them through a TS loader such as [`tsx`](https://github.com/privatenumber/tsx):

```bash
npx tsx basic_one_way_search.ts
```

## Examples

| File | What it shows |
|------|---------------|
| `basic_one_way_search.ts` | Minimal one-way search and result printing |
| `round_trip_search.ts` | Round trip; itineraries returned as `[outbound, return]` |
| `date_range_search.ts` | Cheapest dates across a flexible window |
| `multi_city_search.ts` | Three-leg multi-city itinerary |
| `advanced_filters_search.ts` | Alliances, airline exclusions, layover bounds, currency/locale |
| `error_handling_with_retries.ts` | Custom `Client` config and typed `Search*Error` handling |

## Notes

- `FlightSegment` airports are triple-nested: `[[[Airport.JFK, 0]]]`.
- `PassengerInfo`, `TimeRestrictions`, and `LayoverRestrictions` are plain
  objects (not classes) — pass object literals.
- `currency` / `language` / `country` are passed to `search()`, not to the
  filter object.
- Round-trip and multi-city searches return an array of itineraries, each an
  array of `FlightResult` (one per leg). One-way returns a flat
  `FlightResult[]`.
