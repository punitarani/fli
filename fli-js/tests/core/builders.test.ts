/**
 * Tests for the segment / time-restrictions / date-range builders.
 * Mirrors tests/core/test_builders.py.
 */

import { describe, expect, test } from "bun:test";
import {
  buildDateSearchSegments,
  buildFlightSegments,
  buildMultiCitySegments,
  buildTimeRestrictions,
  normalizeDate,
} from "../../src/core/builders.ts";
import { Airport } from "../../src/models/airport.ts";
import { TripType } from "../../src/models/google-flights/base.ts";

function futureDate(daysAhead = 30): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + daysAhead);
  return d.toISOString().slice(0, 10);
}

describe("normalizeDate", () => {
  test("zero-pads month and day", () => {
    expect(normalizeDate("2026-4-2")).toBe("2026-04-02");
  });
  test("preserves already-padded dates", () => {
    expect(normalizeDate("2026-12-25")).toBe("2026-12-25");
  });
  test("rejects invalid date string", () => {
    expect(() => normalizeDate("not-a-date")).toThrow();
  });
});

describe("buildTimeRestrictions", () => {
  test("both null → null", () => {
    expect(buildTimeRestrictions(null, null)).toBeNull();
  });
  test("departure only", () => {
    const r = buildTimeRestrictions("6-20", null);
    expect(r?.earliest_departure).toBe(6);
    expect(r?.latest_departure).toBe(20);
    expect(r?.earliest_arrival).toBeUndefined();
  });
  test("both windows populated", () => {
    const r = buildTimeRestrictions("6-12", "14-22");
    expect(r?.earliest_departure).toBe(6);
    expect(r?.latest_departure).toBe(12);
    expect(r?.earliest_arrival).toBe(14);
    expect(r?.latest_arrival).toBe(22);
  });
});

describe("buildFlightSegments", () => {
  test("one-way", () => {
    const { segments, tripType } = buildFlightSegments(Airport.JFK, Airport.LAX, futureDate());
    expect(segments).toHaveLength(1);
    expect(tripType).toBe(TripType.ONE_WAY);
  });
  test("round-trip", () => {
    const { segments, tripType } = buildFlightSegments(
      Airport.JFK,
      Airport.LAX,
      futureDate(10),
      futureDate(20),
    );
    expect(segments).toHaveLength(2);
    expect(tripType).toBe(TripType.ROUND_TRIP);
    // Second segment is the return — destination becomes departure.
    expect(segments[1]?.departure_airport[0]?.[0]?.[0]).toBe(Airport.LAX);
    expect(segments[1]?.arrival_airport[0]?.[0]?.[0]).toBe(Airport.JFK);
  });
  test("multi-airport origin", () => {
    const { segments } = buildFlightSegments(
      [Airport.JFK, Airport.LGA, Airport.EWR],
      Airport.LAX,
      futureDate(),
    );
    expect(segments[0]?.departure_airport[0]).toHaveLength(3);
  });
});

describe("buildMultiCitySegments", () => {
  test("creates one segment per leg", () => {
    const { segments, tripType } = buildMultiCitySegments([
      [Airport.JFK, Airport.LAX, futureDate(10)],
      [Airport.LAX, Airport.SEA, futureDate(20)],
      [Airport.SEA, Airport.JFK, futureDate(30)],
    ]);
    expect(segments).toHaveLength(3);
    expect(tripType).toBe(TripType.MULTI_CITY);
  });
});

describe("buildDateSearchSegments", () => {
  test("one-way", () => {
    const { segments, tripType } = buildDateSearchSegments(Airport.JFK, Airport.LAX, futureDate());
    expect(segments).toHaveLength(1);
    expect(tripType).toBe(TripType.ONE_WAY);
  });
  test("round-trip uses tripDuration", () => {
    const start = futureDate(10);
    const { segments, tripType } = buildDateSearchSegments(Airport.JFK, Airport.LAX, start, {
      isRoundTrip: true,
      tripDuration: 7,
    });
    expect(segments).toHaveLength(2);
    expect(tripType).toBe(TripType.ROUND_TRIP);
    const startMs = Date.parse(`${start}T00:00:00Z`);
    const expectedReturnMs = startMs + 7 * 24 * 60 * 60 * 1000;
    const expectedReturn = new Date(expectedReturnMs).toISOString().slice(0, 10);
    expect(segments[1]?.travel_date).toBe(expectedReturn);
  });
});
