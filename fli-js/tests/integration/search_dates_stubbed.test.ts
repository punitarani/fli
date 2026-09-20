/**
 * End-to-end test of SearchDates with a stubbed HTTP client.
 */

import { describe, expect, test } from "bun:test";
import { Airport } from "../../src/models/airport.ts";
import { FlightSegment, TripType } from "../../src/models/google-flights/base.ts";
import { DateSearchFilters } from "../../src/models/google-flights/dates.ts";
import { Client } from "../../src/search/client.ts";
import { SearchDates } from "../../src/search/dates.ts";

function futureDate(daysAhead = 30): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + daysAhead);
  return d.toISOString().slice(0, 10);
}

function calendarResponse(dates: Array<[string, number]>): string {
  // The price decoder walks data[-1] for an array of items.
  // item layout (one-way): [date, _, [[null, price], currency_token]]
  const items = dates.map(([date, price]) => [date, null, [[null, price], null]]);
  // Inner JSON is an array where the last element is `items`.
  const inner = [null, null, items];
  const outer = [["wrb.fr", null, JSON.stringify(inner)]];
  return `)]}'\n\n${JSON.stringify(outer)}`;
}

describe("SearchDates.search (stubbed)", () => {
  test("decodes a synthetic calendar response into DatePrice array", async () => {
    const fakeFetch = async (): Promise<Response> =>
      new Response(
        calendarResponse([
          ["2026-07-15", 199.0],
          ["2026-07-16", 215.5],
          ["2026-07-17", 188.25],
        ]),
        { status: 200 },
      );
    const client = new Client({ fetchImpl: fakeFetch as unknown as typeof fetch, retries: 1 });
    const search = new SearchDates(client);

    const fromD = futureDate(10);
    const toD = futureDate(30);
    const filters = new DateSearchFilters({
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: fromD,
        }),
      ],
      from_date: fromD,
      to_date: toD,
    });

    const results = await search.search(filters, { currency: "USD" });
    expect(results).not.toBeNull();
    expect(results).toHaveLength(3);
    expect(results?.[0]?.price).toBe(199.0);
    expect(results?.[2]?.price).toBe(188.25);
  });

  test("date range > 61 days splits into chunks", async () => {
    let callCount = 0;
    const fakeFetch = async (): Promise<Response> => {
      callCount++;
      return new Response(calendarResponse([["2026-07-15", 100.0]]), { status: 200 });
    };
    const client = new Client({ fetchImpl: fakeFetch as unknown as typeof fetch, retries: 1 });
    const search = new SearchDates(client);

    const fromD = futureDate(10);
    const toD = futureDate(150); // 140-day range → 3 chunks
    const filters = new DateSearchFilters({
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: fromD,
        }),
      ],
      from_date: fromD,
      to_date: toD,
    });
    await search.search(filters);
    // 141 days at 61 per chunk → 3 requests.
    expect(callCount).toBe(3);
  });

  test("returns null on empty calendar response", async () => {
    const fakeFetch = async (): Promise<Response> =>
      new Response(calendarResponse([]), { status: 200 });
    const client = new Client({ fetchImpl: fakeFetch as unknown as typeof fetch, retries: 1 });
    const search = new SearchDates(client);

    const fromD = futureDate(10);
    const toD = futureDate(30);
    const filters = new DateSearchFilters({
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: fromD,
        }),
      ],
      from_date: fromD,
      to_date: toD,
    });
    const out = await search.search(filters);
    expect(out == null || (out?.length ?? 0) === 0).toBe(true);
  });
});

describe("SearchDates static parsers", () => {
  test("_parsePrice extracts a numeric price", () => {
    expect(SearchDates._parsePrice(["2026-07-15", null, [[null, 199.5]]])).toBe(199.5);
  });
  test("_parsePrice returns null when shape is wrong", () => {
    expect(SearchDates._parsePrice([])).toBeNull();
    expect(SearchDates._parsePrice(["2026", null, [[null]]])).toBeNull();
  });
  test("_parseDate one-way returns single-element tuple", () => {
    const parsed = SearchDates._parseDate(["2026-07-15"], TripType.ONE_WAY);
    expect(parsed).toHaveLength(1);
    expect(parsed[0]).toBeInstanceOf(Date);
  });
  test("_parseDate rejects non-numeric date components", () => {
    // The canonical `parseIsoDate` in `core/dates.ts` checks the YYYY-MM-DD
    // shape with a regex first and rejects format errors with
    // `Expected YYYY-MM-DD`; out-of-range calendar dates produce
    // `Invalid date`. Either error is a valid rejection here.
    expect(() => SearchDates._parseDate(["2026-XX-15"], TripType.ONE_WAY)).toThrow(
      /Expected YYYY-MM-DD|Invalid date/,
    );
    expect(() => SearchDates._parseDate(["bad"], TripType.ONE_WAY)).toThrow(
      /Expected YYYY-MM-DD|Invalid date/,
    );
  });
});
