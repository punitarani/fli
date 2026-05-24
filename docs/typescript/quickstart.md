# TypeScript Quick Start

`fli` is a 1:1 TypeScript / JavaScript port of the Python library, published
to npm as [`fli-js`](https://www.npmjs.com/package/fli-js). It mirrors the Python
package — same models, same filter encoding, same wire-format decoders — and
talks directly to Google Flights (no scraping).

## Installation

```bash
bun add fli-js       # or: npm install fli-js / pnpm add fli-js
```

The package ships ESM type definitions. It runs on Bun and on Node via a
TypeScript loader such as [`tsx`](https://github.com/privatenumber/tsx).

## One-way search

```ts
import {
  Airport,
  FlightSearchFilters,
  FlightSegment,
  MaxStops,
  SearchFlights,
  SeatType,
  SortBy,
} from "fli-js";

// travel_date must be in the future, so compute it dynamically.
const inDays = (n: number) => new Date(Date.now() + n * 86_400_000).toISOString().slice(0, 10);

const filters = new FlightSearchFilters({
  passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
  flight_segments: [
    new FlightSegment({
      departure_airport: [[[Airport.JFK, 0]]],
      arrival_airport: [[[Airport.LAX, 0]]],
      travel_date: inDays(30),
    }),
  ],
  seat_type: SeatType.ECONOMY,
  stops: MaxStops.NON_STOP,
  sort_by: SortBy.CHEAPEST,
});

const results = await new SearchFlights().search(filters, { currency: "USD" });
for (const flight of results ?? []) {
  console.log(`$${flight.price ?? "N/A"} — ${flight.duration} min — ${flight.stops} stop(s)`);
}
```

!!! note "Airport nesting"
    `departure_airport` / `arrival_airport` are **triple-nested**:
    `[[[Airport.JFK, 0]]]`. The inner pair is `[airport, 0]`; the extra
    levels mirror the Google Flights wire format.

!!! note "Plain objects, not classes"
    `PassengerInfo`, `TimeRestrictions`, and `LayoverRestrictions` are
    object types (Zod schemas), not classes — pass object literals.
    `FlightSearchFilters`, `DateSearchFilters`, and `FlightSegment` are
    classes constructed with `new`.

## Round-trip search

Round-trip and multi-city searches return an array of itineraries, where each
itinerary is an array of `FlightResult` — one per leg, in order.

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

const filters = new FlightSearchFilters({
  trip_type: TripType.ROUND_TRIP,
  passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
  flight_segments: [
    new FlightSegment({
      departure_airport: [[[Airport.JFK, 0]]],
      arrival_airport: [[[Airport.LAX, 0]]],
      travel_date: inDays(30),
    }),
    new FlightSegment({
      departure_airport: [[[Airport.LAX, 0]]],
      arrival_airport: [[[Airport.JFK, 0]]],
      travel_date: inDays(37),
    }),
  ],
});

const itineraries = (await new SearchFlights().search(filters, { topN: 5 })) as
  | FlightResult[][]
  | null;

for (const [outbound, ret] of itineraries ?? []) {
  console.log(`Total $${outbound.price ?? "N/A"} (return ${ret.legs[0].flight_number})`);
}
```

## Cheapest dates

```ts
import { Airport, DateSearchFilters, FlightSegment, SearchDates } from "fli-js";

const inDays = (n: number) => new Date(Date.now() + n * 86_400_000).toISOString().slice(0, 10);

const filters = new DateSearchFilters({
  passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
  flight_segments: [
    new FlightSegment({
      departure_airport: [[[Airport.JFK, 0]]],
      arrival_airport: [[[Airport.LAX, 0]]],
      travel_date: inDays(30),
    }),
  ],
  from_date: inDays(30),
  to_date: inDays(60),
});

const dates = await new SearchDates().search(filters);
for (const { date, price } of dates ?? []) {
  console.log(`${date[0].toISOString().slice(0, 10)} — $${price}`);
}
```

`DatePrice.date` is a tuple of `Date` objects: `[outbound]` for one-way,
`[outbound, return]` for round trips. Ranges larger than 61 days are split
into multiple calls automatically.

## Filters, alliances, and locale

```ts
import {
  Airline,
  Airport,
  Alliance,
  FlightSearchFilters,
  FlightSegment,
  MaxStops,
  SearchFlights,
  SeatType,
} from "fli-js";

const inDays = (n: number) => new Date(Date.now() + n * 86_400_000).toISOString().slice(0, 10);

const filters = new FlightSearchFilters({
  passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
  flight_segments: [
    new FlightSegment({
      departure_airport: [[[Airport.JFK, 0]]],
      arrival_airport: [[[Airport.NRT, 0]]],
      travel_date: inDays(30),
    }),
  ],
  seat_type: SeatType.BUSINESS,
  stops: MaxStops.ONE_STOP_OR_FEWER,
  alliances: [Alliance.ONEWORLD],
  airlines_exclude: [Airline.AA],
  layover_restrictions: { airports: null, min_duration: 60, max_duration: 240 },
  max_duration: 1200, // minutes
});

// curr / hl / gl map to the search() options, not the filter object.
const flights = await new SearchFlights().search(filters, {
  currency: "EUR",
  language: "en-GB",
  country: "GB",
});
```

## Configuring the HTTP client

The `Client` rate-limits to 10 req/s and retries transient failures with
exponential backoff. Tune it or point it at a proxy:

```ts
import { Client, SearchFlights } from "fli-js";

const client = new Client({
  timeoutMs: 30_000,
  retries: 5,
  proxy: "http://user:pass@proxy.example.com:8080", // or HTTPS_PROXY / HTTP_PROXY env
});

const search = new SearchFlights(client);
```

Typed errors — `SearchTimeoutError`, `SearchConnectionError`,
`SearchHTTPError`, all extending `SearchClientError` — let you branch on
failure mode.

## Next steps

* Browse the [TypeScript examples](examples.md)
* Compare with the [Python Quick Start](../python/quickstart.md)
* The full TypeScript source lives in
  [`fli-js/`](https://github.com/punitarani/fli/tree/main/fli-js)
