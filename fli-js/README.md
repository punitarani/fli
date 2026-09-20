# fli (TypeScript)

A 1:1 TypeScript / JavaScript port of the [Python `fli` library](https://github.com/punitarani/fli).

Programmatic access to Google Flights data via direct API interaction (no
scraping). The API surface mirrors the Python package — same models, same
filter encoding, same wire-format decoders.

## Install

```bash
npm i fli-js   # or: pnpm add fli-js / yarn add fli-js / bun add fli-js
```

## Quick start

```ts
import {
  Airport,
  FlightSearchFilters,
  FlightSegment,
  MaxStops,
  PassengerInfo,
  SearchFlights,
  SeatType,
  SortBy,
} from "fli-js";

const filters = new FlightSearchFilters({
  passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
  flight_segments: [
    new FlightSegment({
      departure_airport: [[[Airport.JFK, 0]]],
      arrival_airport: [[[Airport.LAX, 0]]],
      travel_date: "2026-12-25",
    }),
  ],
  seat_type: SeatType.ECONOMY,
  stops: MaxStops.NON_STOP,
  sort_by: SortBy.CHEAPEST,
});

const results = await new SearchFlights().search(filters, { currency: "USD" });
console.log(results);
```

### Date-range search

```ts
import { Airport, DateSearchFilters, FlightSegment, SearchDates } from "fli-js";

const filters = new DateSearchFilters({
  passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
  flight_segments: [
    new FlightSegment({
      departure_airport: [[[Airport.JFK, 0]]],
      arrival_airport: [[[Airport.LAX, 0]]],
      travel_date: "2026-12-01",
    }),
  ],
  from_date: "2026-12-01",
  to_date: "2026-12-31",
});

const dates = await new SearchDates().search(filters);
```

### Booking links

Turn search results into clickable Google Flights links — no extra network
call, fully deterministic.

```ts
import { googleFlightsUrl, SearchFlights } from "fli-js";

const search = new SearchFlights();
const results = await search.search(filters, { currency: "USD" });

// Per-flight deep link: opens the specific itinerary's booking page
// (vendor fares + "Continue" CTA) via a `tfs` protobuf token.
const first = results?.[0];
if (first) {
  console.log(search.buildFlightBookingUrl(first, { currency: "USD" }));
  // https://www.google.com/travel/flights/booking?tfs=…&curr=USD
}

// Search-level deep link: route + dates pre-filled (handy for a date result
// or a quick "view on Google Flights" link).
console.log(googleFlightsUrl("JFK", "LHR", "2026-12-25", null, { currency: "USD" }));
// https://www.google.com/travel/flights?q=Flights%20from%20JFK%20to%20LHR%20on%202026-12-25&curr=USD
```

`buildFlightBookingUrl` accepts a single `FlightResult` (one-way) or an array
of them (round-trip / multi-city). It never throws — on malformed input it
falls back to the generic Google Flights URL.

## HTTP / proxy configuration

The TypeScript port uses native `fetch` (Bun's built-in) and replaces
`curl_cffi`'s TLS impersonation with:

- realistic Chrome `User-Agent` + `Sec-CH-*` headers,
- automatic rate-limiting at 10 req/s,
- 3-attempt exponential backoff on transient errors,
- proxy support via the `HTTPS_PROXY` / `HTTP_PROXY` env vars (or via the
  explicit `proxy` option on `new Client({...})`).

```ts
import { Client, SearchFlights } from "fli-js";

const search = new SearchFlights(
  new Client({ proxy: "http://user:pass@proxy.example.com:8080" }),
);
```

Set the per-request timeout with `FLI_TIMEOUT=30` (seconds) or via the
`timeoutMs` option on `new Client({...})`.

## Modules

- `fli-js/models` — `Airport`, `Airline`, `FlightSearchFilters`, `DateSearchFilters`,
  `FlightSegment`, `FlightResult`, `BookingOption`, all enums.
- `fli-js/core` — string-to-enum parsers, segment builders, airport search,
  currency token decoders, deep-link builder (`googleFlightsUrl`).
- `fli-js/search` — `SearchFlights` (incl. `buildFlightBookingUrl`),
  `SearchDates`, `Client`, error classes, protobuf token helpers
  (`buildBookingToken`, `buildTfsToken`, `extractBookingTokenFromTfu`).

## Development

```bash
bun install
bun run generate:enums   # regenerate airport.ts / airline.ts from data/*.csv
bun run typecheck
bun run lint             # biome + oxlint
bun run format           # biome format
bun test                 # unit + integration tests (no network)
bun run test:e2e         # live tests (FLI_E2E=1; talks to Google Flights)
bun run ci               # format-check + lint + typecheck + tests
```

## Parity with the Python library

The TypeScript port preserves byte-perfect wire compatibility with the
Python upstream:

- `FlightSearchFilters.format()` produces structurally identical
  nested-list payloads (see `tests/integration/filter_format_snapshots.test.ts`).
- `buildBookingToken(...)` and `buildTfsToken(...)` reproduce captured live
  booking-page tokens byte-for-byte (see `tests/search/proto.test.ts`); the
  resulting `buildFlightBookingUrl(...)` output matches the Python library
  character-for-character.
- The wire-format parser handles both the legacy single-chunk JSONP
  shape and the multi-chunk format used by `GetBookingResults`.

## License

MIT — same as the upstream Python project.
