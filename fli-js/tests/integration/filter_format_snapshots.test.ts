/**
 * Snapshot tests for FlightSearchFilters.format() / DateSearchFilters.format().
 *
 * These expected outputs are copied verbatim from the Python upstream
 * tests/models/test_flight_search_filters.py — keeping these passing means
 * the request body we send Google is byte-identical to the Python client.
 */

import { describe, expect, test } from "bun:test";
import { Airline } from "../../src/models/airline.ts";
import { Airport } from "../../src/models/airport.ts";
import {
  EmissionsFilter,
  FlightSegment,
  MaxStops,
  SeatType,
  SortBy,
  TripType,
} from "../../src/models/google-flights/base.ts";
import { DateSearchFilters } from "../../src/models/google-flights/dates.ts";
import { FlightSearchFilters } from "../../src/models/google-flights/flights.ts";

function travelDate(daysAhead = 30): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + daysAhead);
  return d.toISOString().slice(0, 10);
}

const TD = travelDate(30);

describe("FlightSearchFilters.format() snapshots (parity with Python)", () => {
  test("Test 1: PHX→SFO PREMIUM_ECONOMY NON_STOP", () => {
    const filters = new FlightSearchFilters({
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.PHX, 0]]],
          arrival_airport: [[[Airport.SFO, 0]]],
          time_restrictions: null,
          travel_date: TD,
        }),
      ],
      price_limit: null,
      stops: MaxStops.NON_STOP,
      seat_type: SeatType.PREMIUM_ECONOMY,
      sort_by: SortBy.CHEAPEST,
    });
    expect(filters.format()).toEqual([
      [],
      [
        null,
        null,
        2,
        null,
        [],
        2,
        [1, 0, 0, 0],
        null,
        null,
        null,
        null,
        null,
        null,
        [
          [
            [[["PHX", 0]]],
            [[["SFO", 0]]],
            null,
            1,
            null,
            null,
            TD,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            3,
          ],
        ],
        null,
        null,
        null,
        1,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        0,
      ],
      2,
      1,
      0,
      1,
    ]);
  });

  test("Test 2: PHX→SFO FIRST 4-passenger TOP_FLIGHTS", () => {
    const filters = new FlightSearchFilters({
      passenger_info: { adults: 2, children: 1, infants_in_seat: 3, infants_on_lap: 1 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.PHX, 0]]],
          arrival_airport: [[[Airport.SFO, 0]]],
          time_restrictions: null,
          travel_date: TD,
        }),
      ],
      price_limit: null,
      stops: MaxStops.ONE_STOP_OR_FEWER,
      seat_type: SeatType.FIRST,
      sort_by: SortBy.TOP_FLIGHTS,
    });
    expect(filters.format()).toEqual([
      [],
      [
        null,
        null,
        2,
        null,
        [],
        4,
        [2, 1, 1, 3],
        null,
        null,
        null,
        null,
        null,
        null,
        [
          [
            [[["PHX", 0]]],
            [[["SFO", 0]]],
            null,
            2,
            null,
            null,
            TD,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            3,
          ],
        ],
        null,
        null,
        null,
        1,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        0,
      ],
      0,
      1,
      0,
      1,
    ]);
  });

  test("Test 3: airlines + price_limit + layover_restrictions + time_restrictions", () => {
    const filters = new FlightSearchFilters({
      passenger_info: { adults: 2, children: 3, infants_in_seat: 0, infants_on_lap: 1 },
      price_limit: { max_price: 900, currency: null },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.PHX, 0]]],
          arrival_airport: [[[Airport.SFO, 0]]],
          time_restrictions: {
            earliest_departure: 9,
            latest_departure: 20,
            earliest_arrival: 13,
            latest_arrival: 21,
          },
          travel_date: TD,
        }),
      ],
      stops: MaxStops.ANY,
      airlines: [Airline.AA, Airline.F9, Airline.UA],
      max_duration: 660,
      layover_restrictions: { airports: [Airport.LAX], max_duration: 420 },
    });
    expect(filters.format()).toEqual([
      [],
      [
        null,
        null,
        2,
        null,
        [],
        1,
        [2, 3, 1, 0],
        [null, 900],
        null,
        null,
        null,
        null,
        null,
        [
          [
            [[["PHX", 0]]],
            [[["SFO", 0]]],
            [9, 20, 13, 21],
            0,
            ["AA", "F9", "UA"],
            null,
            TD,
            [660],
            null,
            ["LAX"],
            null,
            null,
            420,
            null,
            3,
          ],
        ],
        null,
        null,
        null,
        1,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        0,
      ],
      1,
      1,
      0,
      1,
    ]);
  });

  test("Test 4: exclude_basic_economy", () => {
    const filters = new FlightSearchFilters({
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.EWR, 0]]],
          arrival_airport: [[[Airport.CHS, 0]]],
          time_restrictions: null,
          travel_date: TD,
        }),
      ],
      stops: MaxStops.NON_STOP,
      seat_type: SeatType.ECONOMY,
      sort_by: SortBy.CHEAPEST,
      exclude_basic_economy: true,
    });
    const out = filters.format() as unknown[];
    // outer[1][28] is the exclude_basic_economy slot
    expect((out[1] as unknown[])[28]).toBe(1);
  });

  test("Test 5: emissions filter", () => {
    const filters = new FlightSearchFilters({
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: TD,
        }),
      ],
      stops: MaxStops.ANY,
      sort_by: SortBy.CHEAPEST,
      emissions: EmissionsFilter.LESS,
    });
    const out = filters.format() as unknown[];
    const seg = ((out[1] as unknown[])[13] as unknown[][])[0] as unknown[];
    expect(seg[13]).toEqual([1]);
  });

  test("Test 6: bags filter", () => {
    const filters = new FlightSearchFilters({
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: TD,
        }),
      ],
      bags: { checked_bags: 1, carry_on: true },
    });
    const out = filters.format() as unknown[];
    expect((out[1] as unknown[])[10]).toEqual([1, 1]);
  });

  test("Test 7: show_all_results = false", () => {
    const filters = new FlightSearchFilters({
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: TD,
        }),
      ],
      sort_by: SortBy.CHEAPEST,
      show_all_results: false,
    });
    const out = filters.format() as unknown[];
    expect(out[3]).toBe(0);
  });

  test("selected_flight encodes the leg's local departure date (not UTC-shifted)", () => {
    // Regression guard: parseDateTime in decoders.ts builds Date via the
    // local-time constructor; formatting back with UTC getters would
    // shift the date by ±1 day for any non-UTC caller.
    //
    // Construct a FlightResult with a known local date+time that's
    // close to local midnight (8pm) — UTC-aware getters would roll
    // forward to the next day for any western-hemisphere TZ.
    const TD_FUTURE = travelDate(60);
    const localDepart = new Date(2026, 11, 15, 20, 0); // Dec 15 8pm local
    const filters = new FlightSearchFilters({
      trip_type: TripType.ROUND_TRIP,
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: TD_FUTURE,
          selected_flight: {
            legs: [
              {
                airline: Airline.AA,
                flight_number: "100",
                departure_airport: Airport.JFK,
                arrival_airport: Airport.LAX,
                departure_datetime: localDepart,
                arrival_datetime: new Date(2026, 11, 15, 23, 30),
                duration: 210,
              },
            ],
            price: 250,
            currency: "USD",
            duration: 210,
            stops: 0,
          },
        }),
        new FlightSegment({
          departure_airport: [[[Airport.LAX, 0]]],
          arrival_airport: [[[Airport.JFK, 0]]],
          travel_date: travelDate(67),
        }),
      ],
    });
    const out = filters.format() as unknown[];
    const seg = ((out[1] as unknown[])[13] as unknown[][])[0] as unknown[];
    const selectedFlights = seg[8] as unknown[][];
    expect(selectedFlights[0]?.[1]).toBe("2026-12-15");
  });

  test("Test 8: alliance filter (STAR_ALLIANCE via Airline enum)", () => {
    const filters = new FlightSearchFilters({
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: TD,
        }),
      ],
      sort_by: SortBy.CHEAPEST,
      airlines: [Airline.STAR_ALLIANCE],
    });
    const out = filters.format() as unknown[];
    const seg = ((out[1] as unknown[])[13] as unknown[][])[0] as unknown[];
    expect(seg[4]).toEqual(["STAR_ALLIANCE"]);
  });

  test("URL encoding produces a non-empty string", () => {
    const filters = new FlightSearchFilters({
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: TD,
        }),
      ],
    });
    const encoded = filters.encode();
    expect(typeof encoded).toBe("string");
    expect(encoded.length).toBeGreaterThan(0);
    // Must be URL-safe (no raw brackets or quotes).
    expect(encoded).not.toMatch(/[[\]"]/);
  });
});

describe("DateSearchFilters.format() snapshots", () => {
  test("One-way date search has from_date/to_date at index 2", () => {
    const fromD = travelDate(10);
    const toD = travelDate(30);
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
    const formatted = filters.format() as unknown[];
    expect(formatted[2]).toEqual([fromD, toD]);
  });

  test("Round-trip date search appends duration pair", () => {
    const fromD = travelDate(10);
    const toD = travelDate(30);
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
          travel_date: travelDate(17),
        }),
      ],
      from_date: fromD,
      to_date: toD,
      duration: 7,
    });
    const formatted = filters.format() as unknown[];
    expect(formatted[3]).toBeNull();
    expect(formatted[4]).toEqual([7, 7]);
  });

  test("encode() returns a URL-safe string", () => {
    const fromD = travelDate(10);
    const toD = travelDate(30);
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
    const encoded = filters.encode();
    expect(typeof encoded).toBe("string");
    expect(encoded.length).toBeGreaterThan(0);
  });

  test("round-trip without duration throws", () => {
    const fromD = travelDate(10);
    const toD = travelDate(30);
    expect(
      () =>
        new DateSearchFilters({
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
              travel_date: travelDate(17),
            }),
          ],
          from_date: fromD,
          to_date: toD,
        }),
    ).toThrow(/Duration/);
  });

  test("one-way with two segments throws", () => {
    const fromD = travelDate(10);
    expect(
      () =>
        new DateSearchFilters({
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
              travel_date: travelDate(17),
            }),
          ],
          from_date: fromD,
          to_date: travelDate(30),
        }),
    ).toThrow(/one flight segment/);
  });
});
