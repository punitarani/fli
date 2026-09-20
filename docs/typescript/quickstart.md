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
`[outbound, return]` for round trips.

!!! warning "One page fetch per date"
    Google's search page carries no calendar grid, so every date in the
    range costs its own full page fetch (~2 MB). A single
    `SearchDates.search` prices at most **93 dates**
    (`MAX_DATES_PER_SEARCH`); a wider range throws `RangeError`. See
    [Search transport](#search-transport).

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
`SearchHTTPError`, `SearchParseError`, `SearchRejectedError` and
`SearchUnsupportedError`, all extending `SearchClientError` — let you
branch on failure mode.

## Search transport

Searches are served by Google's public search page rather than the
`FlightsFrontendService` RPC. Since 2026-08 `GetShoppingResults` and
`GetCalendarGraph` require an `x-goog-batchexecute-bgr` header that only
the page's own JavaScript can produce, so a plain HTTP client gets HTTP
200 with no payload. `fli-js` issues
`GET https://www.google.com/travel/flights?tfs=<protobuf>` instead and
reads the results out of the page's inline `AF_initDataCallback` blob
keyed `ds:1`. This matches the Python library, which moved the same way.

What that means in practice:

* **Three filters are not supported.** `emissions`, `bags` and
  `exclude_basic_economy` have no `tfs` field and cannot be reconstructed
  from the decoded rows, so they are dropped with a warning. Stops,
  cabin, passengers, alliances and layover bounds ride in the request;
  airline include/exclude, price cap, max duration and departure windows
  are applied to the results after fetching, and `sort_by` orders them
  afterwards (`TOP_FLIGHTS` / `BEST` keep Google's own ranking).
* **Multi-city throws `SearchUnsupportedError`.** Google loads those
  results client-side through the gated RPC, so the page carries no rows
  to read. Search each leg separately.
* **`getBookingOptions` is unavailable.** It calls `GetBookingResults`,
  which is gated the same way, and currently throws
  `SearchRejectedError`. `buildFlightBookingUrl` is built offline from
  the itinerary and still works.
* **Fewer rows per search.** Expect roughly 20–45 itineraries, fewer than
  the old RPC returned — and a client-side filter cannot back-fill the
  list the way Google's server-side one did.
* **Children and infants thin the results — sometimes to nothing.** Google
  prices those parties client-side, so the page inlines fewer itineraries
  for them, and in premium cabins often none (measured 2026-09: JFK→LHR
  economy 23 rows for one adult, 16 with an infant; SFO→NRT business 9
  rows for one or two adults, 0 with a child). Extra adults cost nothing.
  An empty result for such a search does not mean the route has no
  flights; `search()` logs a warning, and an adults-only search shows the
  schedule.
* **Date searches cost one page fetch per date**, capped at 93 dates. A
  sweep that never loads a single page stops once five dates have come
  back payload-less and throws, rather than paying the retry budget on
  all of them. Ten dates are in flight at once, so around fourteen are
  attempted first — about 42 page fetches, whether the range is 30, 61 or
  93 days. One that was cut short but found prices returns them with a
  warning. That breaker disarms for good the moment any page loads, even
  an empty one, so it cannot catch a sweep that is mostly timeouts around
  one lucky date — `search` throws that case too, whenever nothing priced
  and at least half the attempted dates never loaded. A minority of
  failures alongside real results, or alongside a confirmed-empty range,
  still returns normally but logs one warning naming the counts.
* **A page occasionally arrives without results.** Roughly one request in
  sixty returns HTTP 200 with no `ds:1` blob; the client retries that case
  up to twice (0.5s then 1.5s) before throwing `SearchParseError`.
* **`FLI_SOCS_COOKIE`.** EU/EEA IPs are redirected to Google's consent
  interstitial, which serves no `ds:1` blob. The client sends a
  pre-accepted `SOCS` consent cookie by default; set `FLI_SOCS_COOKIE` to
  change the value, or to an empty string to send none.

Warnings (dropped filters, a sweep cut short) go to `console.warn`.
Redirect or silence them with `setSearchLogger`:

```ts
import { setSearchLogger } from "fli-js";

setSearchLogger({ warn: (m) => myLogger.warn(m), debug: () => {} });
setSearchLogger(null); // back to console.warn
```

## Next steps

* Browse the [TypeScript examples](examples.md)
* Compare with the [Python Quick Start](../python/quickstart.md)
* The full TypeScript source lives in
  [`fli-js/`](https://github.com/punitarani/fli/tree/main/fli-js)
