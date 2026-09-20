/**
 * Tests for core parser utilities.
 * Mirrors tests/core/test_parsers.py.
 */

import { describe, expect, test } from "bun:test";
import {
  ParseError,
  parseAirlines,
  parseAlliances,
  parseCabinClass,
  parseEmissions,
  parseMaxStops,
  parseSortBy,
  parseTimeRange,
  resolveAirport,
} from "../../src/core/parsers.ts";
import { Airline } from "../../src/models/airline.ts";
import { Airport } from "../../src/models/airport.ts";
import {
  Alliance,
  EmissionsFilter,
  MaxStops,
  SeatType,
  SortBy,
} from "../../src/models/google-flights/base.ts";

describe("parseEmissions", () => {
  test("ALL", () => {
    expect(parseEmissions("ALL")).toBe(EmissionsFilter.ALL);
  });
  test("LESS", () => {
    expect(parseEmissions("LESS")).toBe(EmissionsFilter.LESS);
  });
  test("case-insensitive", () => {
    expect(parseEmissions("less")).toBe(EmissionsFilter.LESS);
    expect(parseEmissions("All")).toBe(EmissionsFilter.ALL);
  });
  test("invalid throws ParseError", () => {
    expect(() => parseEmissions("NONE")).toThrow(ParseError);
  });
});

describe("parseAirlines", () => {
  test("null returns null", () => {
    expect(parseAirlines(null)).toBeNull();
    expect(parseAirlines([])).toBeNull();
  });
  test("repeated items", () => {
    expect(parseAirlines(["BA", "KL"])).toEqual([Airline.BA, Airline.KL]);
  });
  test("comma-separated in one item", () => {
    expect(parseAirlines(["BA,KL"])).toEqual([Airline.BA, Airline.KL]);
  });
  test("space-separated in one item", () => {
    expect(parseAirlines(["BA KL"])).toEqual([Airline.BA, Airline.KL]);
  });
  test("tab separator", () => {
    expect(parseAirlines(["BA\tKL"])).toEqual([Airline.BA, Airline.KL]);
  });
  test("collapses consecutive separators", () => {
    expect(parseAirlines(["BA,,KL", "AA  UA"])).toEqual([
      Airline.BA,
      Airline.KL,
      Airline.AA,
      Airline.UA,
    ]);
  });
  test("alliance pseudo-codes", () => {
    expect(parseAirlines(["STAR_ALLIANCE"])).toEqual([Airline.STAR_ALLIANCE]);
    expect(parseAirlines(["ONEWORLD"])).toEqual([Airline.ONEWORLD]);
  });
  test("mixed airlines and alliances", () => {
    const r = parseAirlines(["STAR_ALLIANCE", "AA"]) as Airline[];
    expect(r).toContain(Airline.STAR_ALLIANCE);
    expect(r).toContain(Airline.AA);
  });
  test("lowercase uppercased in split", () => {
    expect(parseAirlines(["ba,kl"])).toEqual([Airline.BA, Airline.KL]);
  });
  test("numeric prefix in split", () => {
    expect(parseAirlines(["BA,3F"])).toEqual([Airline.BA, Airline._3F]);
  });
  test("invalid code propagates", () => {
    expect(() => parseAirlines(["BA,XXX"])).toThrow(/Invalid airline code: 'XXX'/);
  });
  test.each<string[]>([
    [","],
    [" "],
    [""],
    ["", " ", ","],
  ])("no valid codes throws %#", (...codes) => {
    expect(() => parseAirlines(codes)).toThrow(/No valid airline codes/);
  });
});

describe("parseAlliances", () => {
  test("null returns null", () => {
    expect(parseAlliances(null)).toBeNull();
  });
  test("hyphens normalize to underscores", () => {
    expect(parseAlliances(["star-alliance"])).toEqual([Alliance.STAR_ALLIANCE]);
  });

  test("lowercase normalized", () => {
    expect(parseAlliances(["star_alliance", "oneworld"])).toEqual([
      Alliance.STAR_ALLIANCE,
      Alliance.ONEWORLD,
    ]);
  });
  test("invalid throws", () => {
    expect(() => parseAlliances(["UNKNOWN"])).toThrow(/Invalid alliance/);
  });
});

describe("parseMaxStops", () => {
  test("integer values", () => {
    expect(parseMaxStops("0")).toBe(MaxStops.NON_STOP);
    expect(parseMaxStops("1")).toBe(MaxStops.ONE_STOP_OR_FEWER);
    expect(parseMaxStops("2")).toBe(MaxStops.TWO_OR_FEWER_STOPS);
  });
  test("string names", () => {
    expect(parseMaxStops("ANY")).toBe(MaxStops.ANY);
    expect(parseMaxStops("NON_STOP")).toBe(MaxStops.NON_STOP);
    expect(parseMaxStops("NONSTOP")).toBe(MaxStops.NON_STOP);
    expect(parseMaxStops("ONE_STOP")).toBe(MaxStops.ONE_STOP_OR_FEWER);
    expect(parseMaxStops("TWO_PLUS_STOPS")).toBe(MaxStops.TWO_OR_FEWER_STOPS);
  });
  test("invalid throws", () => {
    expect(() => parseMaxStops("FOUR")).toThrow(ParseError);
  });
});

describe("parseCabinClass", () => {
  test("known cabins", () => {
    expect(parseCabinClass("ECONOMY")).toBe(SeatType.ECONOMY);
    expect(parseCabinClass("Business")).toBe(SeatType.BUSINESS);
    expect(parseCabinClass("FIRST")).toBe(SeatType.FIRST);
  });
  test("invalid throws", () => {
    expect(() => parseCabinClass("COACH")).toThrow(ParseError);
  });
});

describe("parseSortBy", () => {
  test.each([
    ["TOP_FLIGHTS", SortBy.TOP_FLIGHTS],
    ["BEST", SortBy.BEST],
    ["CHEAPEST", SortBy.CHEAPEST],
    ["EMISSIONS", SortBy.EMISSIONS],
  ])("%s → %d", (input, expected) => {
    expect(parseSortBy(input)).toBe(expected);
  });
  test("invalid throws", () => {
    expect(() => parseSortBy("NONE")).toThrow(ParseError);
  });
});

describe("parseTimeRange", () => {
  test("basic range", () => {
    expect(parseTimeRange("6-20")).toEqual([6, 20]);
  });
  test("midnight to midnight", () => {
    expect(parseTimeRange("0-23")).toEqual([0, 23]);
  });
  test("invalid format throws", () => {
    expect(() => parseTimeRange("bad")).toThrow(ParseError);
    expect(() => parseTimeRange("6-25")).toThrow(ParseError);
    expect(() => parseTimeRange("-5-20")).toThrow(ParseError);
  });
});

describe("resolveAirport", () => {
  test("uppercase known code", () => {
    expect(resolveAirport("JFK")).toBe(Airport.JFK);
  });
  test("lowercase normalized", () => {
    expect(resolveAirport("jfk")).toBe(Airport.JFK);
  });
  test("invalid throws", () => {
    expect(() => resolveAirport("ZZZ")).toThrow(ParseError);
  });
});
