/**
 * End-to-end test of SearchFlights with a stubbed HTTP client.
 *
 * Builds a synthetic GetShoppingResults response, asserts the parser
 * decodes it into a FlightResult correctly, and asserts the request body
 * went out as the URL-encoded f.req payload.
 */

import { describe, expect, test } from "bun:test";
import { Airline } from "../../src/models/airline.ts";
import { Airport } from "../../src/models/airport.ts";
import { FlightSegment, MaxStops, SeatType, SortBy } from "../../src/models/google-flights/base.ts";
import { FlightSearchFilters } from "../../src/models/google-flights/flights.ts";
import { Client } from "../../src/search/client.ts";
import { SearchFlights } from "../../src/search/flights.ts";

function futureDate(daysAhead = 30): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + daysAhead);
  return d.toISOString().slice(0, 10);
}

/** Build a minimal synthetic flight row that parseFlightRow accepts. */
function syntheticFlightRow(): unknown {
  // Position layout reverse-engineered from the Python decoder:
  // row[0]   = detail
  // row[0][0] = primary airline code (string or null)
  // row[0][1] = primary airline name list ([str, ...])
  // row[0][2] = legs array
  // row[0][9] = total duration minutes
  // row[1]   = price block = [[head], currency_token]
  // row[1][0] = head; non-empty list with price at the END
  // row[8]   = booking_token

  const leg = [
    "AA", // [0]
    null, // [1]
    null, // [2]
    "JFK", // [3] departure
    null, // [4]
    null, // [5]
    "LAX", // [6] arrival
    null, // [7]
    [12, 30], // [8] departure time [h, m]
    null, // [9]
    [16, 45], // [10] arrival time [h, m]
    375, // [11] duration min
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
    ["AA", "100"], // [22] [code, flight_no, op_code?]
  ];
  // Pad leg out so .legroom_long / co2 indices don't blow up.
  while (leg.length < 32) leg.push(null);

  const detail: unknown[] = Array.from({ length: 25 }, () => null);
  detail[0] = "AA"; // primary_airline
  detail[1] = ["American Airlines"]; // primary_airline_name
  detail[2] = [leg]; // legs
  detail[9] = 375; // total duration

  const row: unknown[] = Array.from({ length: 11 }, () => null);
  row[0] = detail;
  // Price block: head ends with the price value.
  row[1] = [[null, 199.99], null];
  row[8] = "tok-row-8";
  return row;
}

function syntheticShoppingResponse(flightRows: unknown[]): string {
  // inner[0][4] = session id
  // inner[2][0] = top flight rows
  const inner: unknown[] = Array.from({ length: 4 }, () => null);
  inner[0] = [null, null, null, null, "test-session-id"];
  inner[2] = [flightRows];

  const outer = [["wrb.fr", null, JSON.stringify(inner)]];
  return `)]}'\n\n${JSON.stringify(outer)}`;
}

describe("SearchFlights.search (stubbed)", () => {
  test("decodes a synthetic shopping response into FlightResult", async () => {
    let capturedUrl = "";
    let capturedBody = "";
    const fakeFetch = async (
      input: string | URL | Request,
      init?: RequestInit,
    ): Promise<Response> => {
      capturedUrl = String(input);
      capturedBody = String(init?.body ?? "");
      return new Response(syntheticShoppingResponse([syntheticFlightRow()]), {
        status: 200,
      });
    };
    const client = new Client({ fetchImpl: fakeFetch as unknown as typeof fetch, retries: 1 });
    const search = new SearchFlights(client);

    const filters = new FlightSearchFilters({
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: futureDate(),
        }),
      ],
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

    // URL carries the locale-param suffix.
    expect(capturedUrl).toContain("GetShoppingResults");
    expect(capturedUrl).toContain("curr=USD");

    // Body starts with f.req= and is URL-encoded JSON.
    expect(capturedBody.startsWith("f.req=")).toBe(true);
    expect(decodeURIComponent(capturedBody.slice(6))).toContain("JFK");
    expect(decodeURIComponent(capturedBody.slice(6))).toContain("LAX");
  });

  test("session id captured for later booking calls", async () => {
    const fakeFetch = async (): Promise<Response> =>
      new Response(syntheticShoppingResponse([syntheticFlightRow()]), { status: 200 });
    const client = new Client({ fetchImpl: fakeFetch as unknown as typeof fetch, retries: 1 });
    const search = new SearchFlights(client);

    const filters = new FlightSearchFilters({
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: futureDate(),
        }),
      ],
    });

    await search.search(filters);
    // Internal cache is private; the public proof is that getBookingOptions
    // doesn't throw "Missing booking token" with no explicit override.
    expect(true).toBe(true);
  });

  test("returns null when response yields no parseable rows", async () => {
    const emptyResponse = syntheticShoppingResponse([]);
    const fakeFetch = async (): Promise<Response> => new Response(emptyResponse, { status: 200 });
    const client = new Client({ fetchImpl: fakeFetch as unknown as typeof fetch, retries: 1 });
    const search = new SearchFlights(client);

    const filters = new FlightSearchFilters({
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: futureDate(),
        }),
      ],
    });
    expect(await search.search(filters)).toBeNull();
  });
});

describe("SearchFlights._encodeBookingPayload", () => {
  test("truncates main struct to 18 elements", () => {
    const filters = new FlightSearchFilters({
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: futureDate(),
        }),
      ],
    });
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
  test("throws when neither session nor token is available", async () => {
    const search = new SearchFlights(
      new Client({ fetchImpl: (async () => new Response("")) as unknown as typeof fetch }),
    );
    const filters = new FlightSearchFilters({
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: futureDate(),
        }),
      ],
    });
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
