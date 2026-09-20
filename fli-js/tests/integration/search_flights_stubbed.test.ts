/**
 * End-to-end test of SearchFlights with a stubbed HTTP client.
 *
 * Builds a synthetic search page, asserts the parser decodes it into a
 * FlightResult, and asserts the request went out as a GET for the
 * `/travel/flights` page with the expected `tfs` token.
 *
 * These stubs used to encode the old `GetShoppingResults` POST shape
 * (`f.req=` body, `wrb.fr` response). They were updated rather than
 * deleted when the transport moved to the page, so the same behaviour
 * stays covered.
 */

import { describe, expect, test } from "bun:test";
import { Airline } from "../../src/models/airline.ts";
import { Airport } from "../../src/models/airport.ts";
import {
  FlightSegment,
  MaxStops,
  SeatType,
  SortBy,
  TripType,
} from "../../src/models/google-flights/base.ts";
import { FlightSearchFilters } from "../../src/models/google-flights/flights.ts";
import { Client } from "../../src/search/client.ts";
import {
  SearchParseError,
  SearchRejectedError,
  SearchUnsupportedError,
} from "../../src/search/exceptions.ts";
import { SearchFlights } from "../../src/search/flights.ts";
import { setSearchLogger } from "../../src/search/logging.ts";
import { _setPageRetrySleep, buildTfs } from "../../src/search/tfs.ts";

function futureDate(daysAhead = 30): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + daysAhead);
  return d.toISOString().slice(0, 10);
}

/** Build a minimal synthetic flight row that parseFlightRow accepts. */
function syntheticFlightRow(
  options: { airline?: string; price?: number; duration?: number; hour?: number } = {},
): unknown {
  // Position layout reverse-engineered from the Python decoder:
  // row[0]   = detail
  // row[0][0] = primary airline code (string or null)
  // row[0][1] = primary airline name list ([str, ...])
  // row[0][2] = legs array
  // row[0][9] = total duration minutes
  // row[1]   = price block = [[head], currency_token]
  // row[1][0] = head; non-empty list with price at the END
  // row[8]   = booking_token
  const airline = options.airline ?? "AA";
  const duration = options.duration ?? 375;
  const hour = options.hour ?? 12;

  const leg = [
    airline, // [0]
    null, // [1]
    null, // [2]
    "JFK", // [3] departure
    null, // [4]
    null, // [5]
    "LAX", // [6] arrival
    null, // [7]
    [hour, 30], // [8] departure time [h, m]
    null, // [9]
    [hour + 4, 45], // [10] arrival time [h, m]
    duration, // [11] duration min
    null, // [12] amenities
    null, // [13]
    null, // [14] legroom_short
    null, // [15]
    null, // [16]
    "Boeing 737", // [17] aircraft
    null, // [18]
    false, // [19] overnight
    [2026, 12, 25], // [20] departure date [y, m, d]
    [2026, 12, 25], // [21] arrival date
    [airline, "100"], // [22] [code, flight_no, op_code?]
  ];
  // Pad leg out so .legroom_long / co2 indices don't blow up.
  while (leg.length < 32) leg.push(null);

  const detail: unknown[] = Array.from({ length: 25 }, () => null);
  detail[0] = airline; // primary_airline
  detail[1] = ["American Airlines"]; // primary_airline_name
  detail[2] = [leg]; // legs
  detail[9] = duration; // total duration

  const row: unknown[] = Array.from({ length: 11 }, () => null);
  row[0] = detail;
  // Price block: head ends with the price value.
  row[1] = [[null, options.price ?? 199.99], null];
  row[8] = "tok-row-8";
  return row;
}

/** Wrap a payload as the `ds:1` blob of a rendered search page. */
function asSearchPage(payload: unknown): string {
  return `<script>AF_initDataCallback({key: 'ds:0', hash: '1', data:["decoy"], sideChannel: {}});</script><script>AF_initDataCallback({key: 'ds:1', hash: '2', data:${JSON.stringify(payload)}, sideChannel: {}});</script>`;
}

function syntheticSearchPage(flightRows: unknown[]): string {
  // payload[0][4] = session id
  // payload[2][0] = "best" flight rows
  const payload: unknown[] = Array.from({ length: 4 }, () => null);
  payload[0] = [null, null, null, null, "test-session-id"];
  payload[2] = [flightRows];
  return asSearchPage(payload);
}

function oneWayFilters(
  overrides: Partial<ConstructorParameters<typeof FlightSearchFilters>[0]> = {},
) {
  return new FlightSearchFilters({
    passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
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

describe("SearchFlights.search (stubbed)", () => {
  test("decodes a synthetic search page into FlightResult", async () => {
    let capturedUrl = "";
    let capturedMethod = "";
    let capturedBody: unknown;
    const fakeFetch = async (
      input: string | URL | Request,
      init?: RequestInit,
    ): Promise<Response> => {
      capturedUrl = String(input);
      capturedMethod = String(init?.method ?? "");
      capturedBody = init?.body;
      return new Response(syntheticSearchPage([syntheticFlightRow()]), { status: 200 });
    };
    const client = new Client({ fetchImpl: fakeFetch as unknown as typeof fetch, retries: 1 });
    const search = new SearchFlights(client);

    const filters = oneWayFilters({
      stops: MaxStops.NON_STOP,
      seat_type: SeatType.ECONOMY,
      sort_by: SortBy.CHEAPEST,
    });

    const results = await search.search(filters, { currency: "USD" });
    expect(results).not.toBeNull();
    expect(results).toHaveLength(1);

    const flight = (results as unknown as Array<{ legs: unknown[]; price: number }>)[0];
    expect(flight?.price).toBe(199.99);
    expect(flight?.legs).toHaveLength(1);

    // A GET for the public search page, not a POST to the gated RPC.
    expect(capturedMethod).toBe("GET");
    expect(capturedBody).toBeUndefined();
    expect(capturedUrl.startsWith("https://www.google.com/travel/flights?")).toBe(true);
    expect(capturedUrl).toContain(`tfs=${buildTfs(filters)}`);
    expect(capturedUrl).toContain("curr=USD");
    expect(capturedUrl).toContain("hl=en");
    expect(capturedUrl).toContain("gl=US");
  });

  test("session id captured for later booking calls", async () => {
    const fakeFetch = async (): Promise<Response> =>
      new Response(syntheticSearchPage([syntheticFlightRow()]), { status: 200 });
    const client = new Client({ fetchImpl: fakeFetch as unknown as typeof fetch, retries: 1 });
    const search = new SearchFlights(client);
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    try {
      await search.search(oneWayFilters());
    } finally {
      setSearchLogger(null);
    }
    // The page carried a well-formed session id, so nothing was warned about.
    expect(warnings).toEqual([]);
  });

  test("returns null when the page yields no parseable rows", async () => {
    const fakeFetch = async (): Promise<Response> =>
      new Response(syntheticSearchPage([]), { status: 200 });
    const client = new Client({ fetchImpl: fakeFetch as unknown as typeof fetch, retries: 1 });
    const search = new SearchFlights(client);
    expect(await search.search(oneWayFilters())).toBeNull();
  });

  test("a page with no ds:1 blob raises instead of reporting no flights", async () => {
    let calls = 0;
    const fakeFetch = async (): Promise<Response> => {
      calls++;
      return new Response("<html><body>consent wall</body></html>", { status: 200 });
    };
    const client = new Client({
      fetchImpl: fakeFetch as unknown as typeof fetch,
      retries: 1,
      backoffMs: 1,
    });
    const search = new SearchFlights(client);
    _setPageRetrySleep(async () => {});
    try {
      await expect(search.search(oneWayFilters())).rejects.toThrow(SearchParseError);
    } finally {
      _setPageRetrySleep(null);
    }
    // Three page attempts, and no more — the client's own retry does not
    // multiply with this one for a 200 response.
    expect(calls).toBe(3);
  });

  describe("a shape-changed payload is a parse error, not 'no flights'", () => {
    // Python raises SearchParseError when the payload loads but the row
    // blocks are not where they should be. Returning null instead would
    // report the likeliest future Google change — rows moving out of
    // `[2][0]` — to users as "no flights on this route", which is the
    // failure this transport exists to prevent.
    async function searchPayload(payload: unknown) {
      const client = new Client({
        retries: 1,
        backoffMs: 1,
        fetchImpl: (async () =>
          new Response(asSearchPage(payload), { status: 200 })) as unknown as typeof fetch,
      });
      // These payloads have no session id either; that warning is correct
      // but is not what these tests are about.
      setSearchLogger({ warn: () => {}, debug: () => {} });
      try {
        return await new SearchFlights(client).search(oneWayFilters());
      } finally {
        setSearchLogger(null);
      }
    }

    test("payload too short to hold the row blocks raises", async () => {
      // `inner[2]` does not exist at all.
      await expect(searchPayload(["x", [1, 2, 3]])).rejects.toThrow(SearchParseError);
      await expect(searchPayload(["x", [1, 2, 3]])).rejects.toThrow(
        /no flights array at inner\[2\]\/\[3\]/,
      );
    });

    test("an empty row block raises — there is no [0] to read", async () => {
      await expect(searchPayload(["x", [1, 2, 3], [], []])).rejects.toThrow(SearchParseError);
    });

    test("a row block whose [0] is not a list raises", async () => {
      await expect(searchPayload([null, null, [42], [42]])).rejects.toThrow(SearchParseError);
    });

    test("present-but-empty row blocks are genuinely no flights", async () => {
      // `[[]]` is what Google serves for a route with no service: the
      // block is there, `[0]` is there, and it holds no rows.
      const payload: unknown[] = Array.from({ length: 4 }, () => null);
      payload[0] = [null, null, null, null, "sid"];
      payload[2] = [[]];
      payload[3] = [[]];
      expect(await searchPayload(payload)).toBeNull();
    });

    test("a block of scalar rows raises, rather than reporting no flights", async () => {
      // Python hands each row to `parse_flight_row`, which raises
      // `TypeError: 'int' object is not subscriptable`, so all three rows
      // fail and the "parsed 0 of N" tripwire fires. Skipping them
      // silently left the TS port returning `null` — "no flights on this
      // route" — for a payload that is plainly the wrong shape.
      const payload: unknown[] = Array.from({ length: 4 }, () => null);
      payload[0] = [null, null, null, null, "sid"];
      payload[2] = [[1, 2, 3]];
      payload[3] = [[]];
      await expect(searchPayload(payload)).rejects.toThrow(SearchParseError);
      await expect(searchPayload(payload)).rejects.toThrow(/Parsed 0\/3 flight rows/);
    });

    test("one scalar row among good ones still does not sink the search", async () => {
      const payload: unknown[] = Array.from({ length: 4 }, () => null);
      payload[0] = [null, null, null, null, "sid"];
      payload[2] = [[7, syntheticFlightRow(), null]];
      payload[3] = [[]];
      const results = (await searchPayload(payload)) as Array<{ price: number }>;
      expect(results).toHaveLength(1);
      expect(results[0]?.price).toBe(199.99);
    });

    test("a non-list block is skipped, exactly as Python's isinstance check does", async () => {
      // Google parks other things in these slots; only a list is read.
      const payload: unknown[] = Array.from({ length: 4 }, () => null);
      payload[0] = [null, null, null, null, "sid"];
      payload[2] = [[syntheticFlightRow()]];
      payload[3] = "not a block";
      const results = (await searchPayload(payload)) as Array<{ price: number }>;
      expect(results).toHaveLength(1);
    });
  });

  test("multi-city is refused before any request goes out", async () => {
    let calls = 0;
    const client = new Client({
      retries: 1,
      fetchImpl: (async () => {
        calls++;
        return new Response("", { status: 200 });
      }) as unknown as typeof fetch,
    });
    const filters = new FlightSearchFilters({
      trip_type: TripType.MULTI_CITY,
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: futureDate(10),
        }),
        new FlightSegment({
          departure_airport: [[[Airport.LAX, 0]]],
          arrival_airport: [[[Airport.SEA, 0]]],
          travel_date: futureDate(14),
        }),
      ],
    });
    await expect(new SearchFlights(client).search(filters)).rejects.toThrow(SearchUnsupportedError);
    expect(calls).toBe(0);
  });

  test("client-side filters are applied to the decoded rows", async () => {
    const fakeFetch = async (): Promise<Response> =>
      new Response(
        syntheticSearchPage([
          syntheticFlightRow({ airline: "AA", price: 500 }),
          syntheticFlightRow({ airline: "DL", price: 100 }),
        ]),
        { status: 200 },
      );
    const client = new Client({ fetchImpl: fakeFetch as unknown as typeof fetch, retries: 1 });
    const search = new SearchFlights(client);

    const results = (await search.search(oneWayFilters({ airlines: [Airline.AA] }))) as Array<{
      price: number;
    }>;
    expect(results).toHaveLength(1);
    expect(results[0]?.price).toBe(500);
  });

  test("sortBy CHEAPEST orders the page's rows by price", async () => {
    const fakeFetch = async (): Promise<Response> =>
      new Response(
        syntheticSearchPage([
          syntheticFlightRow({ price: 500 }),
          syntheticFlightRow({ price: 100 }),
          syntheticFlightRow({ price: 300 }),
        ]),
        { status: 200 },
      );
    const client = new Client({ fetchImpl: fakeFetch as unknown as typeof fetch, retries: 1 });
    const search = new SearchFlights(client);
    const results = (await search.search(oneWayFilters({ sort_by: SortBy.CHEAPEST }))) as Array<{
      price: number;
    }>;
    expect(results.map((f) => f.price)).toEqual([100, 300, 500]);
  });

  test("unsupported filters are dropped with a warning, not silently", async () => {
    const fakeFetch = async (): Promise<Response> =>
      new Response(syntheticSearchPage([syntheticFlightRow()]), { status: 200 });
    const client = new Client({ fetchImpl: fakeFetch as unknown as typeof fetch, retries: 1 });
    const warnings: string[] = [];
    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    try {
      await new SearchFlights(client).search(
        oneWayFilters({ exclude_basic_economy: true, bags: { checked_bags: 1, carry_on: true } }),
      );
    } finally {
      setSearchLogger(null);
    }
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain("bags");
    expect(warnings[0]).toContain("exclude_basic_economy");
  });

  test("a round trip fetches one return page per expanded outbound", async () => {
    const urls: string[] = [];
    const fakeFetch = async (input: string | URL | Request): Promise<Response> => {
      urls.push(String(input));
      return new Response(syntheticSearchPage([syntheticFlightRow()]), { status: 200 });
    };
    const client = new Client({ fetchImpl: fakeFetch as unknown as typeof fetch, retries: 1 });
    const filters = new FlightSearchFilters({
      trip_type: TripType.ROUND_TRIP,
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: futureDate(20),
        }),
        new FlightSegment({
          departure_airport: [[[Airport.LAX, 0]]],
          arrival_airport: [[[Airport.JFK, 0]]],
          travel_date: futureDate(27),
        }),
      ],
    });
    const results = await new SearchFlights(client).search(filters, { topN: 2 });
    // One outbound page; the page returned one row, so one return page.
    expect(urls).toHaveLength(2);
    expect(urls.every((u) => u.startsWith("https://www.google.com/travel/flights?"))).toBe(true);
    // The return request pins the chosen outbound, so its token differs.
    expect(urls[0]).not.toBe(urls[1]);
    expect(results).toHaveLength(1);
    expect((results as unknown[][])[0]).toHaveLength(2);
  });
});

describe("SearchFlights._encodeBookingPayload", () => {
  test("truncates main struct to 18 elements", () => {
    const filters = oneWayFilters();
    const encoded = SearchFlights._encodeBookingPayload("token", filters);
    expect(typeof encoded).toBe("string");
    // Decoded form should reconstruct: [null, "<json>"] where json starts with [[null,"token"], main, null, 0]
    const decoded = decodeURIComponent(encoded);
    const wrapper = JSON.parse(decoded) as [null, string];
    const inner = JSON.parse(wrapper[1]) as unknown[];
    expect(inner[0]).toEqual([null, "token"]);
    expect(Array.isArray(inner[1])).toBe(true);
    expect((inner[1] as unknown[]).length).toBeLessThanOrEqual(18);
    expect(inner[2]).toBeNull();
    expect(inner[3]).toBe(0);
  });
});

describe("SearchFlights.getBookingOptions error paths", () => {
  test("Google's payload-less RPC answer surfaces as SearchRejectedError", async () => {
    // The booking RPC is the one call still made against
    // FlightsFrontendService, and it is gated: Google answers HTTP 200
    // with a payload-less `wrb.fr` row carrying error 13. Reporting that
    // as an empty vendor list would read as "nobody sells this fare".
    const rejected = `)]}'\n\n${JSON.stringify([["wrb.fr", null, null, null, null, [13]]])}`;
    const search = new SearchFlights(
      new Client({
        retries: 1,
        fetchImpl: (async () => new Response(rejected, { status: 200 })) as unknown as typeof fetch,
      }),
    );
    const fakeFlight = {
      legs: [
        {
          airline: Airline.AA,
          flight_number: "100",
          departure_airport: Airport.JFK,
          arrival_airport: Airport.LAX,
          departure_datetime: new Date(2030, 0, 1, 8, 0),
          arrival_datetime: new Date(2030, 0, 1, 11, 0),
          duration: 180,
        },
      ],
      price: 199,
      currency: "USD",
      duration: 180,
      stops: 0,
      booking_token: "tok",
    } as unknown as Parameters<typeof search.getBookingOptions>[0];
    await expect(search.getBookingOptions(fakeFlight, oneWayFilters())).rejects.toThrow(
      SearchRejectedError,
    );
  });

  test("throws when neither session nor token is available", async () => {
    const search = new SearchFlights(
      new Client({ fetchImpl: (async () => new Response("")) as unknown as typeof fetch }),
    );
    const filters = oneWayFilters();
    const fakeFlight = {
      legs: [{ airline: Airline.AA, flight_number: "100" }],
      price: null,
      currency: null,
      duration: 100,
      stops: 0,
      booking_token: null,
    } as unknown as Parameters<typeof search.getBookingOptions>[0];
    await expect(search.getBookingOptions(fakeFlight, filters)).rejects.toThrow(
      /Missing booking token/,
    );
  });
});
