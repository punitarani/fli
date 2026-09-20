/**
 * End-to-end test of SearchDates with a stubbed HTTP client.
 *
 * The date sweep used to POST one `GetCalendarGraph` request per 61-day
 * chunk and read a whole price grid back. That RPC is gated, and the
 * public search page carries no calendar grid, so every date now costs
 * its own page fetch. These stubs were rewritten around that rather than
 * deleted, and the tests that mattered — chunking, empty responses,
 * price/date parsing — have equivalents below.
 */

import { describe, expect, test } from "bun:test";
import { Airline } from "../../src/models/airline.ts";
import { Airport } from "../../src/models/airport.ts";
import { FlightSegment, TripType } from "../../src/models/google-flights/base.ts";
import { DateSearchFilters } from "../../src/models/google-flights/dates.ts";
import { Client } from "../../src/search/client.ts";
import {
  type DateOutcome,
  MAX_DATES_PER_SEARCH,
  SearchDates,
  SWEEP_FAILURE_THRESHOLD,
} from "../../src/search/dates.ts";
import { SearchClientError, SearchParseError } from "../../src/search/exceptions.ts";
import { setSearchLogger } from "../../src/search/logging.ts";
import { _setPageRetrySleep } from "../../src/search/tfs.ts";

function futureDate(daysAhead = 30): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + daysAhead);
  return d.toISOString().slice(0, 10);
}

/** A flight row `parseFlightRow` accepts, at the given price. */
function flightRow(price: number, airline = "AA"): unknown {
  const leg: unknown[] = [
    airline,
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
    [airline, "100"],
  ];
  while (leg.length < 32) leg.push(null);
  const detail: unknown[] = Array.from({ length: 25 }, () => null);
  detail[0] = airline;
  detail[1] = ["American Airlines"];
  detail[2] = [leg];
  detail[9] = 375;
  const row: unknown[] = Array.from({ length: 11 }, () => null);
  row[0] = detail;
  row[1] = [[null, price], null];
  return row;
}

/** Wrap flight rows as a rendered search page. */
function searchPage(rows: unknown[]): string {
  const payload: unknown[] = [null, null, [rows], null];
  return `<script>AF_initDataCallback({key: 'ds:1', hash: '1', data:${JSON.stringify(payload)}, sideChannel: {}});</script>`;
}

const BLANK_PAGE = "<html><body>consent wall</body></html>";

/** A `DateOutcome` carrying a price, for driving `_collect` directly. */
function priced(price: number): DateOutcome {
  return {
    price: { date: [new Date(2030, 0, 1)], price, currency: "USD" },
    failure: null,
    error: null,
    attempted: true,
  };
}

function oneWayFilters(fromAhead: number, toAhead: number): DateSearchFilters {
  const fromD = futureDate(fromAhead);
  return new DateSearchFilters({
    passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
    flight_segments: [
      new FlightSegment({
        departure_airport: [[[Airport.JFK, 0]]],
        arrival_airport: [[[Airport.LAX, 0]]],
        travel_date: fromD,
      }),
    ],
    from_date: fromD,
    to_date: futureDate(toAhead),
  });
}

function clientReturning(
  handler: (url: string, call: number) => string | { body: string; status: number },
): { client: Client; urls: string[] } {
  const urls: string[] = [];
  const client = new Client({
    retries: 1,
    backoffMs: 1,
    // The real 10 req/sec ceiling would make a 93-date sweep take ten
    // seconds of wall clock for no extra coverage.
    callsPerSecond: 10_000,
    fetchImpl: (async (input: string | URL | Request) => {
      urls.push(String(input));
      const out = handler(String(input), urls.length);
      if (typeof out === "string") return new Response(out, { status: 200 });
      return new Response(out.body, { status: out.status });
    }) as unknown as typeof fetch,
  });
  return { client, urls };
}

describe("SearchDates.search (stubbed)", () => {
  test("prices every date in the range with its own page fetch", async () => {
    const { client, urls } = clientReturning((_u, call) => searchPage([flightRow(100 + call)]));
    const results = await new SearchDates(client).search(oneWayFilters(10, 14), {
      currency: "USD",
    });
    // 10..14 inclusive is five dates, five pages.
    expect(urls).toHaveLength(5);
    expect(urls.every((u) => u.startsWith("https://www.google.com/travel/flights?"))).toBe(true);
    expect(results).toHaveLength(5);
    expect(results?.[0]?.date).toHaveLength(1);
    expect(results?.[0]?.currency).toBe("USD");
  });

  test("each date is priced at the cheapest flight on its page", async () => {
    const { client } = clientReturning(() =>
      searchPage([flightRow(400), flightRow(120), flightRow(250)]),
    );
    const results = await new SearchDates(client).search(oneWayFilters(10, 11));
    expect(results?.map((r) => r.price)).toEqual([120, 120]);
  });

  test("client-side filters apply before the minimum is taken", async () => {
    // The cheapest row is on an excluded carrier; taking the minimum
    // before filtering would quote a fare the caller asked not to see.
    const { client } = clientReturning(() =>
      searchPage([flightRow(400, "AA"), flightRow(120, "DL")]),
    );
    const filters = oneWayFilters(10, 10);
    filters.airlines_exclude = [Airline.DL];
    const results = await new SearchDates(client).search(filters);
    expect(results?.map((r) => r.price)).toEqual([400]);
  });

  test("a round trip prices the outbound and its return date", async () => {
    const fromD = futureDate(10);
    const filters = new DateSearchFilters({
      trip_type: TripType.ROUND_TRIP,
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: fromD,
        }),
        new FlightSegment({
          departure_airport: [[[Airport.LAX, 0]]],
          arrival_airport: [[[Airport.JFK, 0]]],
          travel_date: futureDate(17),
        }),
      ],
      from_date: fromD,
      to_date: futureDate(11),
      duration: 7,
    });
    const { client, urls } = clientReturning(() => searchPage([flightRow(300)]));
    const results = await new SearchDates(client).search(filters);
    expect(urls).toHaveLength(2);
    expect(results).toHaveLength(2);
    const pair = results?.[0]?.date as [Date, Date];
    expect(pair).toHaveLength(2);
    const gapDays = Math.round((pair[1].getTime() - pair[0].getTime()) / 86_400_000);
    expect(gapDays).toBe(7);
  });

  test("a date whose page has no flights is a legitimate empty answer", async () => {
    const { client } = clientReturning((_u, call) =>
      call === 1 ? searchPage([]) : searchPage([flightRow(200)]),
    );
    const results = await new SearchDates(client).search(oneWayFilters(10, 11));
    expect(results).toHaveLength(1);
    expect(results?.[0]?.price).toBe(200);
  });

  test("every date having no flights returns null, not an error", async () => {
    const { client } = clientReturning(() => searchPage([]));
    expect(await new SearchDates(client).search(oneWayFilters(10, 12))).toBeNull();
  });

  test("one malformed row does not sink the sweep", async () => {
    const { client } = clientReturning(() =>
      searchPage(["not a row", flightRow(175), { nope: true }]),
    );
    const results = await new SearchDates(client).search(oneWayFilters(10, 11));
    expect(results?.map((r) => r.price)).toEqual([175, 175]);
  });

  test("a reshaped payload yields no flights rather than throwing", async () => {
    const page = `<script>AF_initDataCallback({key: 'ds:1', hash: '1', data:{"not":"an array"}, sideChannel: {}});</script>`;
    const { client } = clientReturning(() => page);
    expect(await new SearchDates(client).search(oneWayFilters(10, 11))).toBeNull();
  });

  test("dates already in the past are skipped without a request", async () => {
    const { client, urls } = clientReturning(() => searchPage([flightRow(100)]));
    // `FlightSegment` refuses a past travel date, so the segment stays on
    // today and only the sweep's range reaches backwards.
    const filters = new DateSearchFilters({
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: futureDate(0),
        }),
      ],
      from_date: futureDate(-3),
      to_date: futureDate(2),
    });
    const results = await new SearchDates(client).search(filters);
    // Six dates in the range; the two before "today somewhere on Earth"
    // are not bookable and cost no request at all.
    expect(urls).toHaveLength(4);
    expect(results).toHaveLength(4);
  });
});

describe("SearchDates range cap", () => {
  test(`a range above ${MAX_DATES_PER_SEARCH} dates is refused before any fetch`, async () => {
    const { client, urls } = clientReturning(() => searchPage([flightRow(100)]));
    const filters = oneWayFilters(1, 1 + MAX_DATES_PER_SEARCH);
    await expect(new SearchDates(client).search(filters)).rejects.toThrow(
      new RegExp(`${MAX_DATES_PER_SEARCH}-date limit`),
    );
    expect(urls).toHaveLength(0);
  });

  test(`exactly ${MAX_DATES_PER_SEARCH} dates is allowed`, async () => {
    const { client, urls } = clientReturning(() => searchPage([flightRow(100)]));
    // `from` .. `from + 92` inclusive is 93 dates.
    const filters = oneWayFilters(1, MAX_DATES_PER_SEARCH);
    const results = await new SearchDates(client).search(filters);
    expect(urls).toHaveLength(MAX_DATES_PER_SEARCH);
    expect(results).toHaveLength(MAX_DATES_PER_SEARCH);
  });
});

describe("SearchDates failure reporting", () => {
  const silence = () => setSearchLogger({ warn: () => {}, debug: () => {} });

  test("every date failing raises instead of reporting an empty range", async () => {
    _setPageRetrySleep(async () => {});
    silence();
    try {
      const { client } = clientReturning(() => BLANK_PAGE);
      // Three dates, all blocked — under the breaker threshold, so every
      // one is actually attempted.
      await expect(new SearchDates(client).search(oneWayFilters(10, 12))).rejects.toThrow(
        SearchParseError,
      );
    } finally {
      _setPageRetrySleep(null);
      setSearchLogger(null);
    }
  });

  test("a blocked sweep names the FLI_SOCS_COOKIE knob", async () => {
    _setPageRetrySleep(async () => {});
    silence();
    try {
      const { client } = clientReturning(() => BLANK_PAGE);
      await expect(new SearchDates(client).search(oneWayFilters(10, 12))).rejects.toThrow(
        /FLI_SOCS_COOKIE/,
      );
    } finally {
      _setPageRetrySleep(null);
      setSearchLogger(null);
    }
  });

  test("the circuit breaker stops a sweep that has never loaded a page", async () => {
    _setPageRetrySleep(async () => {});
    silence();
    try {
      const { client, urls } = clientReturning(() => BLANK_PAGE);
      const filters = oneWayFilters(10, 70); // 61 dates
      await expect(new SearchDates(client).search(filters)).rejects.toThrow(SearchParseError);
      // Each attempted date costs up to PAGE_FETCH_ATTEMPTS fetches, and
      // the breaker trips once SWEEP_FAILURE_THRESHOLD dates have come
      // back payload-less — far short of 61 dates' worth of requests.
      expect(urls.length).toBeLessThan(61 * 3);
      expect(urls.length).toBeGreaterThanOrEqual(SWEEP_FAILURE_THRESHOLD * 3);
    } finally {
      _setPageRetrySleep(null);
      setSearchLogger(null);
    }
  });

  test("the tripped breaker says how many dates it abandoned", async () => {
    _setPageRetrySleep(async () => {});
    silence();
    try {
      const { client } = clientReturning(() => BLANK_PAGE);
      await expect(new SearchDates(client).search(oneWayFilters(10, 70))).rejects.toThrow(
        /skipped/,
      );
    } finally {
      _setPageRetrySleep(null);
      setSearchLogger(null);
    }
  });

  test("a network error does not arm the breaker", async () => {
    silence();
    try {
      let calls = 0;
      const client = new Client({
        retries: 1,
        backoffMs: 1,
        fetchImpl: (async () => {
          calls++;
          throw new TypeError("fetch failed");
        }) as unknown as typeof fetch,
      });
      // A transient network fault says nothing about the dates not yet
      // tried, so all 10 are attempted rather than abandoned after 5.
      await expect(new SearchDates(client).search(oneWayFilters(10, 19))).rejects.toThrow(
        SearchClientError,
      );
      expect(calls).toBe(10);
    } finally {
      setSearchLogger(null);
    }
  });

  test("one success disarms the breaker for the rest of the sweep", async () => {
    _setPageRetrySleep(async () => {});
    silence();
    try {
      // The first date loads; everything after it is blocked. The sweep
      // must still attempt every remaining date.
      const seen = new Set<string>();
      const client = new Client({
        retries: 1,
        backoffMs: 1,
        callsPerSecond: 10_000,
        fetchImpl: (async (input: string | URL | Request) => {
          const url = String(input);
          const first = seen.size === 0;
          seen.add(url);
          return new Response(first ? searchPage([flightRow(150)]) : BLANK_PAGE, { status: 200 });
        }) as unknown as typeof fetch,
      });
      const results = await new SearchDates(client).search(oneWayFilters(10, 30));
      expect(results).toHaveLength(1);
      // 21 distinct dates were all requested — none skipped.
      expect(seen.size).toBe(21);
    } finally {
      _setPageRetrySleep(null);
      setSearchLogger(null);
    }
  });

  test("a partial sweep warns rather than returning quietly", () => {
    // Driven through `_collect` directly: a sweep that trips the breaker
    // *and* still has prices to show depends on which concurrent fetches
    // happen to land first, which is not something to race in a test.
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    let results: ReturnType<typeof SearchDates._collect>;
    try {
      results = SearchDates._collect(
        [
          priced(180),
          priced(210),
          { price: null, failure: "blocked", error: null, attempted: true },
        ],
        30,
        24,
      );
    } finally {
      setSearchLogger(null);
    }
    expect(results).toHaveLength(2);
    const partial = warnings.filter((w) => w.includes("real but incomplete"));
    expect(partial).toHaveLength(1);
    expect(partial[0]).toContain("2 of 30");
    expect(partial[0]).toContain("24 were skipped");
    expect(partial[0]).toContain("FLI_SOCS_COOKIE");
  });

  test("a complete sweep says nothing about skipping", () => {
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    try {
      expect(SearchDates._collect([priced(180), priced(210)], 2, 0)).toHaveLength(2);
    } finally {
      setSearchLogger(null);
    }
    expect(warnings).toEqual([]);
  });

  test("a tripped breaker with nothing priced raises and names the count", () => {
    setSearchLogger({ warn: () => {}, debug: () => {} });
    try {
      expect(() =>
        SearchDates._collect(
          [{ price: null, failure: "blocked", error: null, attempted: true }],
          30,
          29,
        ),
      ).toThrow(/29 skipped/);
    } finally {
      setSearchLogger(null);
    }
  });

  test("a sweep where nothing was attempted at all returns null quietly", () => {
    expect(
      SearchDates._collect([{ price: null, failure: null, error: null, attempted: false }], 1, 0),
    ).toBeNull();
  });

  test("unsupported filters are dropped with a warning", async () => {
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    try {
      const { client } = clientReturning(() => searchPage([flightRow(100)]));
      const filters = oneWayFilters(10, 10);
      filters.bags = { checked_bags: 2, carry_on: false };
      await new SearchDates(client).search(filters);
    } finally {
      setSearchLogger(null);
    }
    expect(warnings.filter((w) => w.includes("bags"))).toHaveLength(1);
  });
});
