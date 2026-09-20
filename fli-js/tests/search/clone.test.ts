/**
 * Filter-cloning tests.
 *
 * Round-trip expansion and the date sweep both copy the caller's filters
 * before mutating them. The copies used to be hand-written field lists,
 * one per file — the exact pattern that silently dropped
 * `airlines_exclude` and the alliance lists in Python until `model_copy`
 * replaced it. A dropped field does not raise; it just quietly widens the
 * search past what the caller asked for.
 *
 * So the guard is structural: every own field on the filters object must
 * survive the copy, whatever it is called.
 */

import { describe, expect, test } from "bun:test";
import { Airline } from "../../src/models/airline.ts";
import { Airport } from "../../src/models/airport.ts";
import {
  Alliance,
  EmissionsFilter,
  FlightSegment,
  MaxStops,
  SeatType,
  SortBy,
  TripType,
} from "../../src/models/google-flights/base.ts";
import { DateSearchFilters } from "../../src/models/google-flights/dates.ts";
import { FlightSearchFilters } from "../../src/models/google-flights/flights.ts";
import { cloneFilters } from "../../src/search/clone.ts";

function futureDate(daysAhead: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + daysAhead);
  return d.toISOString().slice(0, 10);
}

function fullyPopulatedFlightFilters(): FlightSearchFilters {
  return new FlightSearchFilters({
    trip_type: TripType.ROUND_TRIP,
    passenger_info: { adults: 2, children: 1, infants_in_seat: 1, infants_on_lap: 1 },
    flight_segments: [
      new FlightSegment({
        departure_airport: [
          [
            [Airport.JFK, 0],
            [Airport.EWR, 0],
          ],
        ],
        arrival_airport: [[[Airport.LHR, 0]]],
        travel_date: futureDate(30),
        time_restrictions: { earliest_departure: 6, latest_departure: 12 },
      }),
      new FlightSegment({
        departure_airport: [[[Airport.LHR, 0]]],
        arrival_airport: [[[Airport.JFK, 0]]],
        travel_date: futureDate(37),
      }),
    ],
    stops: MaxStops.ONE_STOP_OR_FEWER,
    seat_type: SeatType.BUSINESS,
    price_limit: { max_price: 2000, currency: "USD" },
    airlines: [Airline.BA],
    airlines_exclude: [Airline.AA],
    alliances: [Alliance.ONEWORLD],
    alliances_exclude: [Alliance.SKYTEAM],
    max_duration: 1200,
    layover_restrictions: { airports: [Airport.DUB], min_duration: 60, max_duration: 240 },
    sort_by: SortBy.CHEAPEST,
    exclude_basic_economy: true,
    emissions: EmissionsFilter.LESS,
    bags: { checked_bags: 2, carry_on: true },
    show_all_results: false,
  });
}

function fullyPopulatedDateFilters(): DateSearchFilters {
  return new DateSearchFilters({
    passenger_info: { adults: 2, children: 1, infants_in_seat: 0, infants_on_lap: 1 },
    flight_segments: [
      new FlightSegment({
        departure_airport: [[[Airport.JFK, 0]]],
        arrival_airport: [[[Airport.LHR, 0]]],
        travel_date: futureDate(30),
        time_restrictions: { earliest_departure: 6, latest_departure: 12 },
      }),
    ],
    stops: MaxStops.NON_STOP,
    seat_type: SeatType.PREMIUM_ECONOMY,
    price_limit: { max_price: 900, currency: "EUR" },
    airlines: [Airline.BA],
    airlines_exclude: [Airline.AA],
    alliances: [Alliance.ONEWORLD],
    alliances_exclude: [Alliance.SKYTEAM],
    max_duration: 900,
    layover_restrictions: { airports: [Airport.DUB], min_duration: 45, max_duration: 300 },
    emissions: EmissionsFilter.LESS,
    bags: { checked_bags: 1, carry_on: false },
    from_date: futureDate(30),
    to_date: futureDate(40),
  });
}

describe("cloneFilters carries every field", () => {
  for (const [label, build] of [
    ["FlightSearchFilters", fullyPopulatedFlightFilters],
    ["DateSearchFilters", fullyPopulatedDateFilters],
  ] as const) {
    test(`${label}: no own field is dropped`, () => {
      const original = build();
      const copy = cloneFilters(original);

      const originalKeys = Object.keys(original).sort();
      expect(Object.keys(copy as object).sort()).toEqual(originalKeys);

      // Every field must compare equal. `toEqual` is structural, so this
      // catches a field that was copied as `undefined` or `null`.
      for (const key of originalKeys) {
        const from = (original as unknown as Record<string, unknown>)[key];
        const to = (copy as unknown as Record<string, unknown>)[key];
        expect(to).toEqual(from as never);
      }
    });

    test(`${label}: the copy keeps its class`, () => {
      const copy = cloneFilters(build());
      expect(copy).toBeInstanceOf(
        label === "FlightSearchFilters" ? FlightSearchFilters : DateSearchFilters,
      );
      // Prototype getters still resolve.
      expect(copy.flight_segments[0]?.parsed_travel_date).toBeInstanceOf(Date);
    });

    test(`${label}: mutating the copy does not touch the original`, () => {
      const original = build();
      const copy = cloneFilters(original);

      // The two mutations the search actually performs.
      const seg = copy.flight_segments[0];
      if (seg) {
        seg.travel_date = "2031-01-01";
        seg.selected_flight = {
          legs: [],
          price: 1,
          currency: "USD",
          duration: 1,
          stops: 0,
        };
      }
      copy.flight_segments.push(copy.flight_segments[0] as FlightSegment);
      (copy.airlines as Airline[]).push(Airline.DL);
      copy.passenger_info.adults = 9;

      expect(original.flight_segments[0]?.travel_date).not.toBe("2031-01-01");
      expect(original.flight_segments[0]?.selected_flight).toBeNull();
      expect(original.flight_segments).toHaveLength(build().flight_segments.length);
      expect(original.airlines).toEqual([Airline.BA]);
      expect(original.passenger_info.adults).toBe(2);
    });
  }

  test("a field added to the filters later is carried without editing the clone", () => {
    // The regression guard: the old hand-written copies listed fields by
    // name, so a new one was silently dropped until someone noticed the
    // search ignoring it.
    const original = fullyPopulatedFlightFilters() as FlightSearchFilters & Record<string, unknown>;
    original.some_future_filter = { nested: ["value"] };
    const copy = cloneFilters(original) as FlightSearchFilters & Record<string, unknown>;
    expect(copy.some_future_filter).toEqual({ nested: ["value"] });
    // …and it is a copy, not the same object.
    expect(copy.some_future_filter).not.toBe(original.some_future_filter);
  });

  test("null-valued fields stay null rather than becoming undefined", () => {
    const original = new FlightSearchFilters({
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LHR, 0]]],
          travel_date: futureDate(30),
        }),
      ],
    });
    const copy = cloneFilters(original);
    expect(copy.airlines).toBeNull();
    expect(copy.price_limit).toBeNull();
    expect(copy.layover_restrictions).toBeNull();
    expect(copy.bags).toBeNull();
    expect(copy.flight_segments[0]?.time_restrictions).toBeNull();
  });
});
