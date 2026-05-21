/**
 * Smoke tests for the generated Airport / Airline enums and the core
 * Google Flights enums.
 */

import { describe, expect, test } from "bun:test";
import { AIRLINE_NAMES, Airline } from "../../src/models/airline.ts";
import { AIRPORT_NAMES, Airport } from "../../src/models/airport.ts";
import {
  Alliance,
  EmissionsFilter,
  MaxStops,
  SeatType,
  SortBy,
  TripType,
} from "../../src/models/google-flights/base.ts";

describe("Airport enum", () => {
  test("common codes are present", () => {
    expect(Airport.JFK).toBe("JFK");
    expect(Airport.LAX).toBe("LAX");
    expect(Airport.LHR).toBe("LHR");
    expect(Airport.NRT).toBe("NRT");
  });
  test("AIRPORT_NAMES carries the name", () => {
    expect(AIRPORT_NAMES.JFK).toMatch(/John F[\s\S]*Kennedy/);
    expect(AIRPORT_NAMES.LHR).toMatch(/Heathrow/);
  });
  test("enum covers >7000 codes", () => {
    expect(Object.keys(AIRPORT_NAMES).length).toBeGreaterThan(7000);
  });
});

describe("Airline enum", () => {
  test("major carriers are present", () => {
    expect(Airline.AA).toBe("AA");
    expect(Airline.DL).toBe("DL");
    expect(Airline.UA).toBe("UA");
    expect(Airline.BA).toBe("BA");
  });
  test("digit-prefixed codes use underscore", () => {
    expect(Airline._3F).toBe("_3F");
  });
  test("alliance pseudo-codes are included", () => {
    expect(Airline.ONEWORLD).toBe("ONEWORLD");
    expect(Airline.SKYTEAM).toBe("SKYTEAM");
    expect(Airline.STAR_ALLIANCE).toBe("STAR_ALLIANCE");
  });
  test("AIRLINE_NAMES carries the name", () => {
    expect(AIRLINE_NAMES.AA).toBe("American Airlines");
    expect(AIRLINE_NAMES.BA).toBe("British Airways");
  });
  test("CSV-quoted names with embedded commas are unquoted", () => {
    // These three rows in data/airlines.csv use RFC4180 quoting because the
    // name contains a comma. The CSV parser must strip the surrounding "..."
    // — naive split-on-first-comma leaves literal quote chars in the value.
    expect(AIRLINE_NAMES.Y2).toBe("Air Century, S.A.");
    expect(AIRLINE_NAMES._2D).toBe("Eastern Airlines, LLC");
    expect(AIRLINE_NAMES._2W).toBe("World 2 Fly, S.L");
  });
});

describe("Airport CSV quoting", () => {
  test("names with embedded commas are unquoted", () => {
    expect(AIRPORT_NAMES.BTR).toBe("Baton Rouge Metro, Ryan Field");
    expect(AIRPORT_NAMES.KQH).toBe("Kishangarh Airport, Ajmer");
    expect(AIRPORT_NAMES.USC).toBe("Union County, Troy Shelton Field");
  });
  test('RFC4180 escaped quotes (`""`) decode to a single `"`', () => {
    // data/airports.csv: PAQ,"Warren ""Bud"" Woods Palmer Municipal Airport"
    expect(AIRPORT_NAMES.PAQ).toBe('Warren "Bud" Woods Palmer Municipal Airport');
  });
});

describe("Google Flights enums", () => {
  test("SeatType wire values", () => {
    expect(SeatType.ECONOMY).toBe(1);
    expect(SeatType.PREMIUM_ECONOMY).toBe(2);
    expect(SeatType.BUSINESS).toBe(3);
    expect(SeatType.FIRST).toBe(4);
  });
  test("SortBy wire values", () => {
    expect(SortBy.TOP_FLIGHTS).toBe(0);
    expect(SortBy.BEST).toBe(1);
    expect(SortBy.CHEAPEST).toBe(2);
  });
  test("TripType wire values", () => {
    expect(TripType.ROUND_TRIP).toBe(1);
    expect(TripType.ONE_WAY).toBe(2);
    expect(TripType.MULTI_CITY).toBe(3);
  });
  test("MaxStops wire values", () => {
    expect(MaxStops.ANY).toBe(0);
    expect(MaxStops.NON_STOP).toBe(1);
  });
  test("EmissionsFilter wire values", () => {
    expect(EmissionsFilter.ALL).toBe(0);
    expect(EmissionsFilter.LESS).toBe(1);
  });
  test("Alliance string identifiers", () => {
    expect(Alliance.ONEWORLD).toBe("ONEWORLD");
    expect(Alliance.STAR_ALLIANCE).toBe("STAR_ALLIANCE");
  });
});
