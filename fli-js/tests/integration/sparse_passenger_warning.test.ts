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
 * Mirrors tests/search/test_sparse_passenger_warning.py.
 */

import { describe, expect, test } from "bun:test";
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
function flightRow(price = 199.99): unknown {
  const leg: unknown[] = [
    "AA",
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
    ["AA", "100"],
  ];
  while (leg.length < 32) leg.push(null);
  const detail: unknown[] = Array.from({ length: 25 }, () => null);
  detail[0] = "AA";
  detail[1] = ["American Airlines"];
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

function oneWayFlightFilters(passengerInfo: PassengerInfo): FlightSearchFilters {
  return new FlightSearchFilters({
    passenger_info: passengerInfo,
    flight_segments: [
      new FlightSegment({
        departure_airport: [[[Airport.JFK, 0]]],
        arrival_airport: [[[Airport.LAX, 0]]],
        travel_date: futureDate(),
      }),
    ],
  });
}

function roundTripFlightFilters(passengerInfo: PassengerInfo): FlightSearchFilters {
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
  });
}

function oneWayDateFilters(days: number, passengerInfo: PassengerInfo): DateSearchFilters {
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

describe("SearchFlights sparse-passenger-mix warning", () => {
  test("one-way empty result with a child warns exactly once", async () => {
    const client = clientServing([searchPage([])]);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    let result: unknown;
    try {
      result = await new SearchFlights(client).search(oneWayFlightFilters(WITH_CHILD));
    } finally {
      setSearchLogger(null);
    }
    expect(result).toBeNull();
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toBe(FLIGHTS_SPARSE_WARNING);
  });

  test("one-way empty result, adults only, does not warn", async () => {
    const client = clientServing([searchPage([])]);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    let result: unknown;
    try {
      result = await new SearchFlights(client).search(oneWayFlightFilters(ADULT_ONLY));
    } finally {
      setSearchLogger(null);
    }
    expect(result).toBeNull();
    expect(warnings).toHaveLength(0);
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

function priced(price: number): DateOutcome {
  return {
    price: { date: [new Date(2030, 0, 1)], price, currency: "USD" },
    failure: null,
    error: null,
    attempted: true,
  };
}

function loadedEmpty(): DateOutcome {
  return { price: null, failure: null, error: null, attempted: true };
}

function failedOutcome(failure = "SearchConnectionError: transient"): DateOutcome {
  return { price: null, failure, error: new Error(failure), attempted: true };
}

describe("SearchDates._warnIfSparsePassengerMix (unit)", () => {
  test("no result, no failures, child warns exactly once", () => {
    const outcomes = [loadedEmpty(), loadedEmpty(), loadedEmpty()];
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    try {
      SearchDates._warnIfSparsePassengerMix(outcomes, null, WITH_CHILD);
    } finally {
      setSearchLogger(null);
    }
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toBe(DATES_SPARSE_WARNING);
  });

  test("no result, no failures, adults only does not warn", () => {
    const outcomes = [loadedEmpty(), loadedEmpty(), loadedEmpty()];
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    try {
      SearchDates._warnIfSparsePassengerMix(outcomes, null, ADULT_ONLY);
    } finally {
      setSearchLogger(null);
    }
    expect(warnings).toHaveLength(0);
  });

  test("no result but a failed date present, child does not warn", () => {
    // A failed date means `_collect` already explains the gap — the two
    // warnings must never stack.
    const outcomes = [loadedEmpty(), loadedEmpty(), loadedEmpty(), failedOutcome()];
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    try {
      SearchDates._warnIfSparsePassengerMix(outcomes, null, WITH_CHILD);
    } finally {
      setSearchLogger(null);
    }
    expect(warnings).toHaveLength(0);
  });

  test("a result present, child does not warn", () => {
    const p = priced(150);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    try {
      SearchDates._warnIfSparsePassengerMix([p], [p.price as DatePrice], WITH_CHILD);
    } finally {
      setSearchLogger(null);
    }
    expect(warnings).toHaveLength(0);
  });

  test("1 failed + 3 empty + child: exactly one warning total, and it is the sweep's own", () => {
    // Exercises `_collect` and `_warnIfSparsePassengerMix` together, in the
    // same order `SearchDates.search` calls them, so the "cannot stack"
    // contract between the two is pinned directly.
    const outcomes = [loadedEmpty(), loadedEmpty(), loadedEmpty(), failedOutcome()];
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
    let result: DatePrice[] | null;
    try {
      result = await new SearchDates(client).search(oneWayDateFilters(3, WITH_CHILD));
    } finally {
      setSearchLogger(null);
    }
    expect(result).toBeNull();
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toBe(DATES_SPARSE_WARNING);
  });

  test("empty sweep, adults only, does not warn", async () => {
    const client = clientServing([searchPage([])]);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    let result: DatePrice[] | null;
    try {
      result = await new SearchDates(client).search(oneWayDateFilters(3, ADULT_ONLY));
    } finally {
      setSearchLogger(null);
    }
    expect(result).toBeNull();
    expect(warnings).toHaveLength(0);
  });

  test("sweep with results, child, does not warn", async () => {
    const client = clientServing([searchPage([flightRow()])]);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    let result: DatePrice[] | null;
    try {
      result = await new SearchDates(client).search(oneWayDateFilters(3, WITH_CHILD));
    } finally {
      setSearchLogger(null);
    }
    expect(result).not.toBeNull();
    expect(warnings).toHaveLength(0);
  });
});
