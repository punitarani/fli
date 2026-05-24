# TypeScript Examples

Complete, runnable TypeScript examples live in
[`examples/typescript/`](https://github.com/punitarani/fli/tree/main/examples/typescript).
Each file mirrors its Python counterpart so you can compare the two APIs.

## Running

```bash
cd examples/typescript
bun install                 # or: npm install

bun run basic_one_way_search.ts
# ...or use the package scripts:
bun run basic        # one-way
bun run round-trip   # round trip
bun run dates        # cheapest dates in a range
bun run multi-city   # 3-leg itinerary
bun run advanced     # alliances + exclusions + locale
bun run errors       # client tuning + typed error handling
```

On Node, run through a TypeScript loader: `npx tsx basic_one_way_search.ts`.

## Files

| File | What it shows |
|------|---------------|
| `basic_one_way_search.ts` | Minimal one-way search and result printing |
| `round_trip_search.ts` | Round trip; itineraries returned as `[outbound, return]` |
| `date_range_search.ts` | Cheapest dates across a flexible window |
| `multi_city_search.ts` | Three-leg multi-city itinerary |
| `advanced_filters_search.ts` | Alliances, airline exclusions, layover bounds, currency/locale |
| `error_handling_with_retries.ts` | Custom `Client` config and typed `Search*Error` handling |

## Multi-city

```ts
import {
  Airport,
  type FlightResult,
  FlightSearchFilters,
  FlightSegment,
  SearchFlights,
  TripType,
} from "fli-js";

const inDays = (n: number) => new Date(Date.now() + n * 86_400_000).toISOString().slice(0, 10);

const leg = (from: Airport, to: Airport, date: string) =>
  new FlightSegment({
    departure_airport: [[[from, 0]]],
    arrival_airport: [[[to, 0]]],
    travel_date: date,
  });

const filters = new FlightSearchFilters({
  trip_type: TripType.MULTI_CITY,
  passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
  flight_segments: [
    leg(Airport.JFK, Airport.LHR, inDays(30)),
    leg(Airport.LHR, Airport.CDG, inDays(34)),
    leg(Airport.CDG, Airport.JFK, inDays(38)),
  ],
});

const itineraries = (await new SearchFlights().search(filters, { topN: 3 })) as
  | FlightResult[][]
  | null;

for (const legs of itineraries ?? []) {
  const total = legs.reduce((sum, l) => sum + (l.price ?? 0), 0);
  console.log(`Itinerary total: $${total}`);
}
```

## Error handling

```ts
import {
  SearchConnectionError,
  SearchHTTPError,
  SearchTimeoutError,
} from "fli-js";

try {
  await new SearchFlights().search(filters);
} catch (err) {
  if (err instanceof SearchTimeoutError) {
    // raise the client timeout and retry
  } else if (err instanceof SearchConnectionError) {
    // network/proxy problem
  } else if (err instanceof SearchHTTPError) {
    // non-2xx from Google
  } else {
    throw err;
  }
}
```

See the [Python examples](../python/examples.md) for the equivalent scripts.
