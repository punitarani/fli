/**
 * Tests for the sparse-passenger-mix warning on empty results.
 *
 * Google's search-page transport inlines fewer (sometimes zero) rows for
 * parties with children or infants — the fares are priced client-side
 * through the gated RPC this transport cannot reach. An empty
 * `SearchFlights.search` / `SearchDates.search` result for such a party used
 * to be indistinguishable from a route with no service at all; these tests
 * pin the one warning each call logs to explain the difference, and confirm
 * it stays silent whenever it would not apply.
 *
 * A result can also come back empty because the *caller's own* client-side
 * filter (airline, price cap, max duration, departure window) removed every
 * row Google did inline — that is not evidence of the passenger-mix pricing
 * gap, so a second family of tests below pins that the warning (and the
 * `sparsePassengerMix` getter both classes expose) only fires when at least
 * one fetched page decoded to zero rows *before* filtering.
 *
 * Mirrors tests/search/test_sparse_passenger_warning.py.
 */

import { describe, expect, test } from "bun:test";
import { Airline } from "../../src/models/airline.ts";
import { Airport } from "../../src/models/airport.ts";
import {
  FlightSegment,
  type PassengerInfo,
  TripType,
} from "../../src/models/google-flights/base.ts";
import { DateSearchFilters } from "../../src/models/google-flights/dates.ts";
import { FlightSearchFilters } from "../../src/models/google-flights/flights.ts";
import { Client } from "../../src/search/client.ts";
import {
  SPARSE_PASSENGER_MIX_WARNING as DATES_SPARSE_WARNING,
  type DateOutcome,
  type DatePrice,
  SearchDates,
} from "../../src/search/dates.ts";
import {
  SPARSE_PASSENGER_MIX_WARNING as FLIGHTS_SPARSE_WARNING,
  SearchFlights,
} from "../../src/search/flights.ts";
import { setSearchLogger } from "../../src/search/logging.ts";

const ADULT_ONLY: PassengerInfo = {
  adults: 2,
  children: 0,
  infants_in_seat: 0,
  infants_on_lap: 0,
};
const WITH_CHILD: PassengerInfo = { adults: 1, children: 1, infants_in_seat: 0, infants_on_lap: 0 };

function futureDate(daysAhead = 45): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + daysAhead);
  return d.toISOString().slice(0, 10);
}

/** A minimal flight row `parseFlightRow` accepts. */
function flightRow(price = 199.99, airlineCode = "DL"): unknown {
  const leg: unknown[] = [
    airlineCode,
    null,
    null,
    "JFK",
    null,
    null,
    "LAX",
    null,
    [12, 30],
    null,
    [16, 45],
    375,
    null,
    null,
    null,
    null,
    null,
    "Boeing 737",
    null,
    false,
    [2026, 12, 25],
    [2026, 12, 25],
    [airlineCode, "100"],
  ];
  while (leg.length < 32) leg.push(null);
  const detail: unknown[] = Array.from({ length: 25 }, () => null);
  detail[0] = airlineCode;
  detail[1] = ["Carrier"];
  detail[2] = [leg];
  detail[9] = 375;
  const row: unknown[] = Array.from({ length: 11 }, () => null);
  row[0] = detail;
  row[1] = [[null, price], null];
  return row;
}

function asSearchPage(payload: unknown): string {
  return `<script>AF_initDataCallback({key: 'ds:1', hash: '1', data:${JSON.stringify(payload)}, sideChannel: {}});</script>`;
}

/** Wrap flight rows as a rendered search page (shared shape flights & dates both read). */
function searchPage(rows: unknown[]): string {
  const payload: unknown[] = Array.from({ length: 4 }, () => null);
  payload[0] = [null, null, null, null, "test-session-id"];
  payload[2] = [rows];
  return asSearchPage(payload);
}

function oneWayFlightFilters(
  passengerInfo: PassengerInfo,
  overrides: Partial<ConstructorParameters<typeof FlightSearchFilters>[0]> = {},
): FlightSearchFilters {
  return new FlightSearchFilters({
    passenger_info: passengerInfo,
    flight_segments: [
      new FlightSegment({
        departure_airport: [[[Airport.JFK, 0]]],
        arrival_airport: [[[Airport.LAX, 0]]],
        travel_date: futureDate(),
      }),
    ],
    ...overrides,
  });
}

function roundTripFlightFilters(
  passengerInfo: PassengerInfo,
  overrides: Partial<ConstructorParameters<typeof FlightSearchFilters>[0]> = {},
): FlightSearchFilters {
  return new FlightSearchFilters({
    trip_type: TripType.ROUND_TRIP,
    passenger_info: passengerInfo,
    flight_segments: [
      new FlightSegment({
        departure_airport: [[[Airport.JFK, 0]]],
        arrival_airport: [[[Airport.LAX, 0]]],
        travel_date: futureDate(45),
      }),
      new FlightSegment({
        departure_airport: [[[Airport.LAX, 0]]],
        arrival_airport: [[[Airport.JFK, 0]]],
        travel_date: futureDate(52),
      }),
    ],
    ...overrides,
  });
}

function oneWayDateFilters(
  days: number,
  passengerInfo: PassengerInfo,
  overrides: Partial<ConstructorParameters<typeof DateSearchFilters>[0]> = {},
): DateSearchFilters {
  const fromD = futureDate(30);
  return new DateSearchFilters({
    passenger_info: passengerInfo,
    flight_segments: [
      new FlightSegment({
        departure_airport: [[[Airport.JFK, 0]]],
        arrival_airport: [[[Airport.LAX, 0]]],
        travel_date: fromD,
      }),
    ],
    from_date: fromD,
    to_date: futureDate(30 + days - 1),
    ...overrides,
  });
}

/** A Client whose fetch serves `bodies` in call order (last one repeats). */
function clientServing(bodies: string[]): Client {
  let calls = 0;
  return new Client({
    retries: 1,
    fetchImpl: (async () => {
      const body = bodies[Math.min(calls, bodies.length - 1)] as string;
      calls++;
      return new Response(body, { status: 200 });
    }) as unknown as typeof fetch,
  });
}

/**
 * A Client whose response body can be swapped between calls, so the same
 * SearchFlights/SearchDates instance can be reused across two searches —
 * needed to test that `sparsePassengerMix` resets on the *same* instance
 * (TS `Client` takes its `fetchImpl` once at construction, unlike Python's
 * mutable `client.get`).
 */
function swappableClient(initialBody: string): { client: Client; setBody: (body: string) => void } {
  let body = initialBody;
  const client = new Client({
    retries: 1,
    backoffMs: 1,
    fetchImpl: (async () => new Response(body, { status: 200 })) as unknown as typeof fetch,
  });
  return { client, setBody: (b: string) => (body = b) };
}

describe("SearchFlights sparse-passenger-mix warning", () => {
  test("one-way empty result with a child warns exactly once", async () => {
    const client = clientServing([searchPage([])]);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    const search = new SearchFlights(client);
    let result: unknown;
    try {
      result = await search.search(oneWayFlightFilters(WITH_CHILD));
    } finally {
      setSearchLogger(null);
    }
    expect(result).toBeNull();
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toBe(FLIGHTS_SPARSE_WARNING);
    expect(search.sparsePassengerMix).toBe(true);
  });

  test("one-way empty result, adults only, does not warn", async () => {
    const client = clientServing([searchPage([])]);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    const search = new SearchFlights(client);
    let result: unknown;
    try {
      result = await search.search(oneWayFlightFilters(ADULT_ONLY));
    } finally {
      setSearchLogger(null);
    }
    expect(result).toBeNull();
    expect(warnings).toHaveLength(0);
    expect(search.sparsePassengerMix).toBe(false);
  });

  test("one-way non-empty result with a child does not warn", async () => {
    const client = clientServing([searchPage([flightRow()])]);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    let result: unknown;
    try {
      result = await new SearchFlights(client).search(oneWayFlightFilters(WITH_CHILD));
    } finally {
      setSearchLogger(null);
    }
    expect(result).not.toBeNull();
    expect(warnings).toHaveLength(0);
  });

  test("round trip: outbound itself empty, child warns exactly once", async () => {
    const client = clientServing([searchPage([])]);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    let result: unknown;
    try {
      result = await new SearchFlights(client).search(roundTripFlightFilters(WITH_CHILD));
    } finally {
      setSearchLogger(null);
    }
    expect(result).toBeNull();
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toBe(FLIGHTS_SPARSE_WARNING);
  });

  test("round trip: outbound has rows but every return-leg fetch is empty, child warns exactly once", async () => {
    // `_fetchFlights` runs twice here (outbound + one expansion candidate);
    // the warning must still fire only once for the whole `search()` call.
    const client = clientServing([searchPage([flightRow()]), searchPage([])]);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    let result: Array<unknown> | null;
    try {
      result = (await new SearchFlights(client).search(
        roundTripFlightFilters(WITH_CHILD),
      )) as Array<unknown> | null;
    } finally {
      setSearchLogger(null);
    }
    expect(result?.length ?? 0).toBe(0);
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toBe(FLIGHTS_SPARSE_WARNING);
  });

  test("round trip: rows on both legs with a child does not warn", async () => {
    const client = clientServing([searchPage([flightRow()]), searchPage([flightRow()])]);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    let result: Array<unknown> | null;
    try {
      result = (await new SearchFlights(client).search(
        roundTripFlightFilters(WITH_CHILD),
      )) as Array<unknown> | null;
    } finally {
      setSearchLogger(null);
    }
    expect((result?.length ?? 0) > 0).toBe(true);
    expect(warnings).toHaveLength(0);
  });
});

describe("SearchFlights sparse-passenger-mix misattribution", () => {
  // Every row here is on airline DL; filtering for AA removes it entirely —
  // Google *did* inline something, so the sparse-mix diagnosis does not
  // apply even though the final result is empty and the party has a child.

  test("one-way: rows filtered out by airline does not warn", async () => {
    const client = clientServing([searchPage([flightRow(199.99, "DL")])]);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    const search = new SearchFlights(client);
    let result: unknown;
    try {
      result = await search.search(oneWayFlightFilters(WITH_CHILD, { airlines: [Airline.AA] }));
    } finally {
      setSearchLogger(null);
    }
    expect(result).toBeNull();
    expect(warnings).toHaveLength(0);
    expect(search.sparsePassengerMix).toBe(false);
  });

  test("round trip: outbound rows filtered out does not warn", async () => {
    // Never even reaches the return-leg fetch — the outbound leg's
    // post-filter result is already empty.
    const client = clientServing([searchPage([flightRow(199.99, "DL")])]);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    const search = new SearchFlights(client);
    let result: unknown;
    try {
      result = await search.search(roundTripFlightFilters(WITH_CHILD, { airlines: [Airline.AA] }));
    } finally {
      setSearchLogger(null);
    }
    expect(result).toBeNull();
    expect(warnings).toHaveLength(0);
    expect(search.sparsePassengerMix).toBe(false);
  });

  test("round trip: outbound survives, return-leg row filtered out does not warn", async () => {
    // Outbound row matches the filter; the return-leg row does not. The
    // return-leg page still carried a row (Google inlined it) — the
    // caller's own filter removed it, not Google.
    const client = clientServing([
      searchPage([flightRow(199.99, "AA")]),
      searchPage([flightRow(199.99, "DL")]),
    ]);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    const search = new SearchFlights(client);
    let result: Array<unknown> | null;
    try {
      result = (await search.search(
        roundTripFlightFilters(WITH_CHILD, { airlines: [Airline.AA] }),
      )) as Array<unknown> | null;
    } finally {
      setSearchLogger(null);
    }
    expect(result?.length ?? 0).toBe(0);
    expect(warnings).toHaveLength(0);
    expect(search.sparsePassengerMix).toBe(false);
  });
});

describe("SearchFlights.sparsePassengerMix lifecycle", () => {
  test("resets to false after a non-sparse search on the same instance", async () => {
    const { client, setBody } = swappableClient(searchPage([]));
    const search = new SearchFlights(client);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    try {
      await search.search(oneWayFlightFilters(WITH_CHILD));
    } finally {
      setSearchLogger(null);
    }
    expect(search.sparsePassengerMix).toBe(true);

    setBody(searchPage([flightRow()]));
    const result = await search.search(oneWayFlightFilters(WITH_CHILD));
    expect(result).not.toBeNull();
    expect(search.sparsePassengerMix).toBe(false);
  });

  test("resets to false before a search that throws", async () => {
    const { client, setBody } = swappableClient(searchPage([]));
    const search = new SearchFlights(client);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    try {
      await search.search(oneWayFlightFilters(WITH_CHILD));
    } finally {
      setSearchLogger(null);
    }
    expect(search.sparsePassengerMix).toBe(true);

    setBody("<html><body>consent wall</body></html>");
    setSearchLogger({ warn: () => {}, debug: () => {} });
    try {
      await expect(search.search(oneWayFlightFilters(WITH_CHILD))).rejects.toThrow();
    } finally {
      setSearchLogger(null);
    }
    expect(search.sparsePassengerMix).toBe(false);
  });
});

function priced(price: number): DateOutcome {
  return {
    price: { date: [new Date(2030, 0, 1)], price, currency: "USD" },
    failure: null,
    error: null,
    attempted: true,
    rowsBeforeFilters: 1,
  };
}

function loadedEmptyRawZero(): DateOutcome {
  return { price: null, failure: null, error: null, attempted: true, rowsBeforeFilters: 0 };
}

function loadedEmptyFilteredOut(rowsBeforeFilters = 2): DateOutcome {
  return { price: null, failure: null, error: null, attempted: true, rowsBeforeFilters };
}

function failedOutcome(failure = "SearchConnectionError: transient"): DateOutcome {
  return {
    price: null,
    failure,
    error: new Error(failure),
    attempted: true,
    rowsBeforeFilters: null,
  };
}

describe("SearchDates._warnIfSparsePassengerMix (unit)", () => {
  test("no result, no failures, zero raw rows, child warns exactly once", () => {
    const outcomes = [loadedEmptyRawZero(), loadedEmptyRawZero(), loadedEmptyRawZero()];
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    let warned: boolean;
    try {
      warned = SearchDates._warnIfSparsePassengerMix(outcomes, null, WITH_CHILD);
    } finally {
      setSearchLogger(null);
    }
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toBe(DATES_SPARSE_WARNING);
    expect(warned).toBe(true);
  });

  test("no result, no failures, adults only does not warn", () => {
    const outcomes = [loadedEmptyRawZero(), loadedEmptyRawZero(), loadedEmptyRawZero()];
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    let warned: boolean;
    try {
      warned = SearchDates._warnIfSparsePassengerMix(outcomes, null, ADULT_ONLY);
    } finally {
      setSearchLogger(null);
    }
    expect(warnings).toHaveLength(0);
    expect(warned).toBe(false);
  });

  test("no result but a failed date present, child does not warn", () => {
    // A failed date means `_collect` already explains the gap — the two
    // warnings must never stack.
    const outcomes = [
      loadedEmptyRawZero(),
      loadedEmptyRawZero(),
      loadedEmptyRawZero(),
      failedOutcome(),
    ];
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    let warned: boolean;
    try {
      warned = SearchDates._warnIfSparsePassengerMix(outcomes, null, WITH_CHILD);
    } finally {
      setSearchLogger(null);
    }
    expect(warnings).toHaveLength(0);
    expect(warned).toBe(false);
  });

  test("a result present, child does not warn", () => {
    const p = priced(150);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    let warned: boolean;
    try {
      warned = SearchDates._warnIfSparsePassengerMix([p], [p.price as DatePrice], WITH_CHILD);
    } finally {
      setSearchLogger(null);
    }
    expect(warnings).toHaveLength(0);
    expect(warned).toBe(false);
  });

  test("no result, rows filtered out every date, does not warn", () => {
    // Every date's page carried rows; the caller's own filter emptied all.
    const outcomes = [
      loadedEmptyFilteredOut(2),
      loadedEmptyFilteredOut(3),
      loadedEmptyFilteredOut(1),
    ];
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    let warned: boolean;
    try {
      warned = SearchDates._warnIfSparsePassengerMix(outcomes, null, WITH_CHILD);
    } finally {
      setSearchLogger(null);
    }
    expect(warnings).toHaveLength(0);
    expect(warned).toBe(false);
  });

  test("no result, mixed zero and filtered rows, still warns", () => {
    // At least one date's page was genuinely empty — still the pricing gap.
    const outcomes = [loadedEmptyFilteredOut(2), loadedEmptyRawZero()];
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    let warned: boolean;
    try {
      warned = SearchDates._warnIfSparsePassengerMix(outcomes, null, WITH_CHILD);
    } finally {
      setSearchLogger(null);
    }
    expect(warnings).toHaveLength(1);
    expect(warned).toBe(true);
  });

  test("1 failed + 3 empty + child: exactly one warning total, and it is the sweep's own", () => {
    // Exercises `_collect` and `_warnIfSparsePassengerMix` together, in the
    // same order `SearchDates.search` calls them, so the "cannot stack"
    // contract between the two is pinned directly.
    const outcomes = [
      loadedEmptyRawZero(),
      loadedEmptyRawZero(),
      loadedEmptyRawZero(),
      failedOutcome(),
    ];
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    let result: DatePrice[] | null;
    try {
      result = SearchDates._collect(outcomes, 4, 0);
      SearchDates._warnIfSparsePassengerMix(outcomes, result, WITH_CHILD);
    } finally {
      setSearchLogger(null);
    }
    expect(result).toBeNull();
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).not.toBe(DATES_SPARSE_WARNING);
    expect(warnings[0]).toContain("loaded");
  });
});

describe("SearchDates sparse-passenger-mix warning (integration, stubbed)", () => {
  test("empty sweep with a child warns exactly once", async () => {
    const client = clientServing([searchPage([])]);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    const search = new SearchDates(client);
    let result: DatePrice[] | null;
    try {
      result = await search.search(oneWayDateFilters(3, WITH_CHILD));
    } finally {
      setSearchLogger(null);
    }
    expect(result).toBeNull();
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toBe(DATES_SPARSE_WARNING);
    expect(search.sparsePassengerMix).toBe(true);
  });

  test("empty sweep, adults only, does not warn", async () => {
    const client = clientServing([searchPage([])]);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    const search = new SearchDates(client);
    let result: DatePrice[] | null;
    try {
      result = await search.search(oneWayDateFilters(3, ADULT_ONLY));
    } finally {
      setSearchLogger(null);
    }
    expect(result).toBeNull();
    expect(warnings).toHaveLength(0);
    expect(search.sparsePassengerMix).toBe(false);
  });

  test("sweep with results, child, does not warn", async () => {
    const client = clientServing([searchPage([flightRow()])]);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    const search = new SearchDates(client);
    let result: DatePrice[] | null;
    try {
      result = await search.search(oneWayDateFilters(3, WITH_CHILD));
    } finally {
      setSearchLogger(null);
    }
    expect(result).not.toBeNull();
    expect(warnings).toHaveLength(0);
    expect(search.sparsePassengerMix).toBe(false);
  });

  test("sweep: rows filtered out by airline every date does not warn", async () => {
    const client = clientServing([searchPage([flightRow(199.99, "DL")])]);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    const search = new SearchDates(client);
    let result: DatePrice[] | null;
    try {
      result = await search.search(oneWayDateFilters(3, WITH_CHILD, { airlines: [Airline.AA] }));
    } finally {
      setSearchLogger(null);
    }
    expect(result).toBeNull();
    expect(warnings).toHaveLength(0);
    expect(search.sparsePassengerMix).toBe(false);
  });

  test("sparsePassengerMix resets to false after a non-sparse sweep on the same instance", async () => {
    const { client, setBody } = swappableClient(searchPage([]));
    const search = new SearchDates(client);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    try {
      await search.search(oneWayDateFilters(3, WITH_CHILD));
    } finally {
      setSearchLogger(null);
    }
    expect(search.sparsePassengerMix).toBe(true);

    setBody(searchPage([flightRow()]));
    const result = await search.search(oneWayDateFilters(3, WITH_CHILD));
    expect(result).not.toBeNull();
    expect(search.sparsePassengerMix).toBe(false);
  });
});
