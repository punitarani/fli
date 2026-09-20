/**
 * Tests for the airport-search relevance cascade.
 * Mirrors tests/core/test_airports.py.
 */

import { describe, expect, test } from "bun:test";
import { searchAirports } from "../../src/core/airports.ts";

describe("searchAirports", () => {
  test("exact IATA wins with score 100", () => {
    const results = searchAirports("JFK");
    expect(results[0]?.code).toBe("JFK");
    expect(results[0]?.match_type).toBe("iata_exact");
    expect(results[0]?.score).toBe(100);
  });

  test("city alias expands to multiple airports (score 90)", () => {
    const results = searchAirports("new york");
    const codes = results.map((r) => r.code);
    expect(codes).toContain("JFK");
    expect(codes).toContain("LGA");
    expect(codes).toContain("EWR");
    for (const r of results) {
      if (codes.includes(r.code) && r.match_type === "city") {
        expect(r.score).toBe(90);
      }
    }
  });

  test("city prefix match (score 80)", () => {
    const results = searchAirports("new yo");
    const codes = results.map((r) => r.code);
    expect(codes).toContain("JFK");
    const jfk = results.find((r) => r.code === "JFK" && r.match_type === "city");
    expect(jfk?.score).toBe(80);
  });

  test("airport name substring match (score ≤70)", () => {
    const results = searchAirports("heathrow");
    expect(results[0]?.code).toBe("LHR");
    expect(results[0]?.match_type).toBe("name");
    expect(results[0]?.score).toBeLessThanOrEqual(70);
  });

  test("IATA prefix only for ≤3-char queries", () => {
    const results = searchAirports("SF");
    const codes = results.map((r) => r.code);
    // "SF" matches "san francisco" city aliases — those score higher.
    expect(codes).toContain("SFO");
  });

  test("limit caps results", () => {
    const r5 = searchAirports("new york", 5);
    expect(r5.length).toBeLessThanOrEqual(5);
  });

  test("empty / whitespace query returns []", () => {
    expect(searchAirports("")).toEqual([]);
    expect(searchAirports("   ")).toEqual([]);
  });

  test("limit < 1 returns []", () => {
    expect(searchAirports("JFK", 0)).toEqual([]);
  });

  test("aliases like 'sf' and 'la' are honoured", () => {
    expect(searchAirports("sf")[0]?.match_type).toBe("city");
    expect(searchAirports("la").some((r) => r.code === "LAX")).toBe(true);
  });

  test("higher-priority match wins for the same code", () => {
    // 'JFK' resolves first as iata_exact (100) — no duplicate.
    const r = searchAirports("JFK");
    const jfkCount = r.filter((m) => m.code === "JFK").length;
    expect(jfkCount).toBe(1);
  });
});
