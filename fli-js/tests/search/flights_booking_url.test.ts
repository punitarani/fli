/**
 * Tests for SearchFlights.buildFlightBookingUrl.
 *
 * All tests are purely in-process: no network calls, no live API. The tfs
 * itinerary token is fully deterministic from the flight data.
 */

import { describe, expect, test } from "bun:test";
import { Buffer } from "node:buffer";
import { Airline } from "../../src/models/airline.ts";
import { Airport } from "../../src/models/airport.ts";
import {
  type FlightLeg,
  type FlightResult,
  SeatType,
} from "../../src/models/google-flights/base.ts";
import { SearchFlights } from "../../src/search/flights.ts";

/** Build a leg with a LOCAL departure datetime (matches the decoder). */
function makeLeg(
  airline: Airline,
  flightNumber: string,
  dep: Airport,
  arr: Airport,
  depDate: string,
): FlightLeg {
  const [y, m, d] = depDate.split("-").map((p) => Number.parseInt(p, 10)) as [
    number,
    number,
    number,
  ];
  const dt = new Date(y, m - 1, d, 8, 0);
  const arrDt = new Date(y, m - 1, d, 10, 0);
  return {
    airline,
    flight_number: flightNumber,
    departure_airport: dep,
    arrival_airport: arr,
    departure_datetime: dt,
    arrival_datetime: arrDt,
    duration: 120,
  };
}

function oneWay(airline: Airline = Airline.AA, flightNumber = "1"): FlightResult {
  return {
    legs: [makeLeg(airline, flightNumber, Airport.SFO, Airport.PHX, "2026-09-01")],
    price: 100,
    currency: "USD",
    duration: 120,
    stops: 0,
  };
}

function roundTrip(): [FlightResult, FlightResult] {
  const outbound: FlightResult = {
    legs: [makeLeg(Airline.AA, "100", Airport.JFK, Airport.LAX, "2026-09-01")],
    price: 200,
    currency: "USD",
    duration: 180,
    stops: 0,
  };
  const inbound: FlightResult = {
    legs: [makeLeg(Airline.AA, "200", Airport.LAX, Airport.JFK, "2026-09-08")],
    price: null,
    currency: "USD",
    duration: 180,
    stops: 0,
  };
  return [outbound, inbound];
}

function connection(): FlightResult {
  return {
    legs: [
      makeLeg(Airline.UA, "101", Airport.SFO, Airport.ORD, "2026-09-01"),
      makeLeg(Airline.UA, "202", Airport.ORD, Airport.JFK, "2026-09-01"),
    ],
    price: 150,
    currency: "USD",
    duration: 360,
    stops: 1,
  };
}

function tfsBytes(url: string): Uint8Array {
  const tfs = new URL(url).searchParams.get("tfs");
  if (!tfs) throw new Error("no tfs param");
  const pad = (4 - (tfs.length % 4)) % 4;
  const standard = (tfs + "=".repeat(pad)).replace(/-/g, "+").replace(/_/g, "/");
  return new Uint8Array(Buffer.from(standard, "base64"));
}

describe("buildFlightBookingUrl", () => {
  const search = new SearchFlights();

  test("one-way has tfs", () => {
    const url = search.buildFlightBookingUrl(oneWay());
    expect(url.startsWith("https://www.google.com/travel/flights/booking?tfs=")).toBe(true);
  });

  test("round-trip has tfs", () => {
    expect(search.buildFlightBookingUrl(roundTrip()).includes("tfs=")).toBe(true);
  });

  test("tfs is urlsafe with no padding", () => {
    const tfs = new URL(search.buildFlightBookingUrl(oneWay())).searchParams.get("tfs") ?? "";
    expect(tfs.includes("=")).toBe(false);
    expect(tfs.includes("+")).toBe(false);
    expect(tfs.includes("/")).toBe(false);
  });

  test("no tfu param emitted", () => {
    expect(search.buildFlightBookingUrl(oneWay()).includes("tfu")).toBe(false);
  });

  test("deterministic — same itinerary, same URL", () => {
    expect(search.buildFlightBookingUrl(oneWay())).toBe(search.buildFlightBookingUrl(oneWay()));
  });

  test("locale params appended", () => {
    const url = search.buildFlightBookingUrl(oneWay(), {
      currency: "EUR",
      language: "en-GB",
      country: "GB",
    });
    expect(url).toContain("curr=EUR");
    expect(url).toContain("hl=en-GB");
    expect(url).toContain("gl=GB");
  });

  test("no locale params when not provided", () => {
    const url = search.buildFlightBookingUrl(oneWay());
    expect(url).not.toContain("curr=");
    expect(url).not.toContain("hl=");
    expect(url).not.toContain("gl=");
  });

  test("connection flight encodes each leg in tfs", () => {
    const raw = tfsBytes(search.buildFlightBookingUrl(connection()));
    const text = Buffer.from(raw).toString("latin1");
    expect(text.includes("101")).toBe(true);
    expect(text.includes("202")).toBe(true);
    expect(text.includes("ORD")).toBe(true);
  });

  test("round-trip encodes two segments in tfs", () => {
    const raw = tfsBytes(search.buildFlightBookingUrl(roundTrip()));
    let count = 0;
    for (const b of raw) if (b === 0x1a) count++;
    expect(count).toBeGreaterThanOrEqual(2);
  });

  test("multi-city (3 segments) encodes f19=2 (one-way), not round-trip", () => {
    const multiCity: FlightResult[] = [
      {
        legs: [makeLeg(Airline.AA, "1", Airport.JFK, Airport.LAX, "2026-09-01")],
        price: 100,
        currency: "USD",
        duration: 120,
        stops: 0,
      },
      {
        legs: [makeLeg(Airline.AA, "2", Airport.LAX, Airport.ORD, "2026-09-05")],
        price: 100,
        currency: "USD",
        duration: 120,
        stops: 0,
      },
      {
        legs: [makeLeg(Airline.AA, "3", Airport.ORD, Airport.JFK, "2026-09-10")],
        price: 100,
        currency: "USD",
        duration: 120,
        stops: 0,
      },
    ];
    const raw = tfsBytes(search.buildFlightBookingUrl(multiCity));
    // f19 tag 0x98 0x01, value 2 (one-way/multi-city) — must not be 1 (round-trip).
    expect(Array.from(raw.slice(-3))).toEqual([0x98, 0x01, 0x02]);
  });

  test("digit-prefixed airline code strips the underscore", () => {
    const flight = oneWay(Airline._3F, "101");
    const text = Buffer.from(tfsBytes(search.buildFlightBookingUrl(flight))).toString("latin1");
    expect(text.includes("3F")).toBe(true);
    expect(text.includes("_3F")).toBe(false);
  });

  test("never throws on malformed data — falls back to a Google Flights URL", () => {
    const bad = {
      legs: [{ departure_datetime: undefined }],
      price: null,
    } as unknown as FlightResult;
    const url = search.buildFlightBookingUrl(bad);
    expect(url).toContain("google.com");
  });

  test("returns a string", () => {
    expect(typeof search.buildFlightBookingUrl(oneWay())).toBe("string");
  });

  test("seatType defaults to economy (field 9 = 1)", () => {
    const raw = tfsBytes(search.buildFlightBookingUrl(oneWay()));
    expect(Buffer.from(raw).includes(Buffer.from([0x48, 0x01]))).toBe(true);
    expect(Buffer.from(raw).includes(Buffer.from([0x48, 0x03]))).toBe(false);
  });

  test("seatType BUSINESS encodes field 9 as 3", () => {
    const economy = search.buildFlightBookingUrl(oneWay());
    const business = search.buildFlightBookingUrl(oneWay(), { seatType: SeatType.BUSINESS });
    expect(economy).not.toBe(business);
    const raw = tfsBytes(business);
    expect(Buffer.from(raw).includes(Buffer.from([0x48, 0x03]))).toBe(true);
  });
});
