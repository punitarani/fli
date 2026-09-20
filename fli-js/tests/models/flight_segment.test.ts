/**
 * Validation tests for FlightSegment.
 * Mirrors tests/models/test_flight_segment_validation.py.
 */

import { describe, expect, test } from "bun:test";
import { Airport } from "../../src/models/airport.ts";
import { FlightSegment } from "../../src/models/google-flights/base.ts";

function futureDate(daysAhead = 30): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + daysAhead);
  return d.toISOString().slice(0, 10);
}

describe("FlightSegment validation", () => {
  test("rejects past travel date", () => {
    const past = new Date();
    past.setUTCDate(past.getUTCDate() - 1);
    const pastStr = past.toISOString().slice(0, 10);
    expect(
      () =>
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: pastStr,
        }),
    ).toThrow(/past/);
  });

  test("accepts today's date", () => {
    const today = new Date().toISOString().slice(0, 10);
    expect(
      () =>
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: today,
        }),
    ).not.toThrow();
  });

  test("rejects same departure and arrival", () => {
    expect(
      () =>
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.JFK, 0]]],
          travel_date: futureDate(),
        }),
    ).toThrow(/different/);
  });

  test("rejects empty departure airport list", () => {
    expect(
      () =>
        new FlightSegment({
          departure_airport: [],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: futureDate(),
        }),
    ).toThrow(/must be specified/);
  });

  test("rejects empty arrival airport list", () => {
    expect(
      () =>
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [],
          travel_date: futureDate(),
        }),
    ).toThrow(/must be specified/);
  });

  test("parsed_travel_date returns a Date", () => {
    const seg = new FlightSegment({
      departure_airport: [[[Airport.JFK, 0]]],
      arrival_airport: [[[Airport.LAX, 0]]],
      travel_date: futureDate(60),
    });
    expect(seg.parsed_travel_date).toBeInstanceOf(Date);
  });

  test("rejects invalid date format", () => {
    expect(
      () =>
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: "12/25/2026",
        }),
    ).toThrow();
  });
});
