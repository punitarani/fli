# fli (TypeScript)

A 1:1 TypeScript / JavaScript port of the [Python `fli` library](https://github.com/punitarani/fli).

Programmatic access to Google Flights data via direct API interaction (no
scraping). The API surface mirrors the Python package — same models, same
filter encoding, same wire-format decoders — and, since Google gated its
RPC endpoints, the same [search-page transport](#search-transport).

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

## Search transport

Searches are served by Google's public search page rather than the
`FlightsFrontendService` RPC. Since 2026-08 `GetShoppingResults` and
`GetCalendarGraph` require an `x-goog-batchexecute-bgr` header that only the
page's own JavaScript can produce, so a plain HTTP client gets HTTP 200 with no
payload. `fli-js` issues `GET https://www.google.com/travel/flights?tfs=<protobuf>`
instead and reads the results out of the page's inline `AF_initDataCallback`
blob keyed `ds:1`.

What that means in practice:

- **Three filters are not supported.** `emissions`, `bags` and
  `exclude_basic_economy` have no `tfs` field and cannot be reconstructed from
  the decoded rows, so they are dropped with a warning. Stops, cabin,
  passengers, alliances and layover bounds ride in the request; airline
  include/exclude, price cap, max duration and departure windows are applied to
  the results after fetching, and `sort_by` orders them afterwards
  (`TOP_FLIGHTS` / `BEST` keep Google's own ranking).
- **Multi-city throws `SearchUnsupportedError`.** Google loads those results
  client-side through the gated RPC, so the page carries no rows to read.
  Search each leg separately.
- **`getBookingOptions` is unavailable.** It calls `GetBookingResults`, which
  is gated the same way, and currently throws `SearchRejectedError`. The
  per-flight `tfs` booking deep links (`buildFlightBookingUrl`) are built
  offline and still work.
- **Fewer rows per search.** Expect roughly 20–45 itineraries, fewer than the
  old RPC returned — and a client-side filter cannot back-fill the list the way
  Google's server-side one did.
- **Date searches cost one page fetch per date.** The page has no calendar
  grid, so a range is priced date by date; one `SearchDates.search` covers at
  most 93 dates (`MAX_DATES_PER_SEARCH`) and a wider range throws `RangeError`.
  A sweep that never manages to load a single page — the shape a blocked or
  consent-gated client produces — stops once five dates have come back
  payload-less rather than paying the retry budget on all of them, and throws.
  Up to ten dates are in flight at once, so around fourteen are attempted
  before the rest are abandoned (measured: 42 page fetches, whether the range
  is 30, 61 or 93 days). Only pages served without results count towards that:
  a timeout or a dropped connection says nothing about the dates not yet tried,
  so those never abandon a sweep. A sweep cut short that still found prices
  returns them with one warning saying so.
- **A page occasionally arrives without results.** Roughly one request in sixty
  returns HTTP 200 with no `ds:1` blob; the client retries that case up to twice
  (0.5s then 1.5s) before throwing `SearchParseError`. A healthy search never
  pays for it.
- **`FLI_SOCS_COOKIE`.** EU/EEA IPs are redirected to Google's consent
  interstitial, which serves no `ds:1` blob. The client sends a pre-accepted
  `SOCS` consent cookie by default; set `FLI_SOCS_COOKIE` to change the value,
  or to an empty string to send none.

The client reports dropped filters and partial sweeps through `console.warn`.
Redirect or silence that with `setSearchLogger`:

```ts
import { setSearchLogger } from "fli-js";

setSearchLogger({ warn: (m) => myLogger.warn(m), debug: () => {} });
setSearchLogger(null); // back to console.warn
```

## HTTP / proxy configuration

The TypeScript port uses native `fetch` (Bun's and Node's built-in) and
replaces `curl_cffi`'s TLS impersonation with:

- realistic Chrome `User-Agent` + `Sec-CH-*` headers — the `User-Agent` is
  load-bearing, not cosmetic: without one the search page serves a shell with
  no flight rows in it,
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
  (`buildBookingToken`, `buildTfsToken`, `extractBookingTokenFromTfu`), and
  the search-page transport (`buildTfs`, `pageUrl`, `extractPayload`,
  `fetchPayload`).

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
- `buildTfs(...)` produces the same search-page token as the Python
  `fli.search._tfs.build_tfs` across trip shapes, cabins, stop limits,
  passenger mixes, alliances and layover bounds. The expected values in
  `tests/search/tfs.test.ts` are generated by running the Python encoder —
  regenerate them from the repository root with
  `uv run --python 3.13 python fli-js/scripts/dump_tfs_goldens.py`.
- `extractPayload(...)` is pinned against the same captured search page the
  Python suite uses (`tests/search/fixtures/search_page_jfk_lhr_nonstop_ds1.html`).
- The wire-format parser handles both the legacy single-chunk JSONP
  shape and the multi-chunk format used by `GetBookingResults`.

## License

MIT — same as the upstream Python project.
