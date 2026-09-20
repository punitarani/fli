/**
 * Direct decoder function coverage.
 * Mirrors tests/search/test_decoders.py for the in-process bits.
 */

import { describe, expect, test } from "bun:test";
import { Airline } from "../../src/models/airline.ts";
import {
  _parseDateTime,
  _parseEmissions,
  _safeAirline,
  parseBookingChunk,
} from "../../src/search/decoders.ts";

describe("_safeAirline", () => {
  test("known code returns enum value", () => {
    expect(_safeAirline("DL")).toBe(Airline.DL);
  });

  test("null returns null", () => {
    expect(_safeAirline(null)).toBeNull();
  });

  test("empty string returns null", () => {
    expect(_safeAirline("")).toBeNull();
  });

  test("number returns null", () => {
    expect(_safeAirline(42)).toBeNull();
  });

  test("sentinel 'multi' returns null silently", () => {
    expect(_safeAirline("multi")).toBeNull();
  });

  test("unknown code returns null", () => {
    expect(_safeAirline("ZZFAKE")).toBeNull();
  });

  test("digit-prefixed code (e.g. '3F') resolves with underscore lookup", () => {
    expect(_safeAirline("3F")).toBe(Airline._3F);
  });
});

describe("_parseDateTime", () => {
  test("valid arrays produce datetime", () => {
    const d = _parseDateTime([2026, 7, 15], [20, 25]);
    expect(d.getFullYear()).toBe(2026);
    expect(d.getMonth()).toBe(6); // July
    expect(d.getDate()).toBe(15);
    expect(d.getHours()).toBe(20);
    expect(d.getMinutes()).toBe(25);
  });

  test("all-null date raises", () => {
    expect(() => _parseDateTime([null, null, null], [0, 0])).toThrow();
  });

  test("all-null time raises", () => {
    expect(() => _parseDateTime([2026, 1, 1], [null, null])).toThrow();
  });

  test("null minute coerced to 0", () => {
    const d = _parseDateTime([2026, 7, 15], [10, null]);
    expect(d.getMinutes()).toBe(0);
  });

  test("partial-null date raises rather than producing a silently-shifted Date", () => {
    // Python's `datetime(2026, 0, 0)` raises ValueError. JS `new Date(2026, -1, 0)`
    // returns "Nov 30 2025" silently — guard against that drift.
    expect(() => _parseDateTime([2026, null, null], [10, 0])).toThrow();
    expect(() => _parseDateTime([2026, 6, null], [10, 0])).toThrow();
    expect(() => _parseDateTime([2026, 13, 1], [10, 0])).toThrow();
    expect(() => _parseDateTime([2026, 6, 32], [10, 0])).toThrow();
  });
});

describe("_parseEmissions", () => {
  function detailWith(block: unknown): unknown[] {
    const detail: unknown[] = Array.from({ length: 23 }, () => null);
    detail[22] = block;
    return detail;
  }

  test("missing block returns all null", () => {
    expect(_parseEmissions([])).toEqual({
      this_g: null,
      typical_g: null,
      delta_pct: null,
      tag: null,
    });
  });

  test("non-list block returns all null", () => {
    expect(_parseEmissions(detailWith("bad"))).toEqual({
      this_g: null,
      typical_g: null,
      delta_pct: null,
      tag: null,
    });
  });

  test.each<[number, string]>([
    [1, "lower"],
    [2, "typical"],
    [3, "higher"],
  ])("tag %d maps to %s", (tagInt, expected) => {
    const block: unknown[] = Array.from({ length: 12 }, () => null);
    block[11] = tagInt;
    expect(_parseEmissions(detailWith(block)).tag).toBe(expected);
  });

  test("unknown tag is null", () => {
    const block: unknown[] = Array.from({ length: 12 }, () => null);
    block[11] = 99;
    expect(_parseEmissions(detailWith(block)).tag).toBeNull();
  });
});

describe("parseBookingChunk", () => {
  test("returns empty for non-list input", () => {
    expect(parseBookingChunk(null)).toEqual([]);
    expect(parseBookingChunk("string")).toEqual([]);
  });

  test("returns empty when no booking rows present", () => {
    expect(parseBookingChunk([[1, 2, 3]])).toEqual([]);
  });

  test("decodes a synthetic booking row", () => {
    // Minimal valid booking row shape: [int, vendor_block, _, flights, _, urls, _, price_block]
    const row = [
      1,
      [["VendorCode", "Vendor Name", null, true]],
      null,
      [["AA", "123"]],
      null,
      ["https://book.example.com", null, ["https://www.google.com/travel/clk?x=1"]],
      null,
      [[null, 234.5], "token-here"],
    ];
    const wrapped = [row];
    const result = parseBookingChunk(wrapped);
    expect(result).toHaveLength(1);
    expect(result[0]?.vendor_code).toBe("VendorCode");
    expect(result[0]?.vendor_name).toBe("Vendor Name");
    expect(result[0]?.is_airline_direct).toBe(true);
    expect(result[0]?.price).toBe(234.5);
    expect(result[0]?.flights).toEqual([["AA", "123"]]);
    expect(result[0]?.booking_url).toBe("https://book.example.com");
    expect(result[0]?.google_click_url).toBe("https://www.google.com/travel/clk?x=1");
  });
});
