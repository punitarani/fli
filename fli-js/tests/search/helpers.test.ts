/**
 * Tests for the defensive nested-list helpers.
 * Mirrors tests/search/test_helpers.py.
 */

import { describe, expect, test } from "bun:test";
import { asBool, asInt, asNonNegativeInt, asStr, safeGet } from "../../src/search/helpers.ts";

describe("safeGet", () => {
  test("returns element at valid index", () => {
    expect(safeGet([10, 20, 30], 1)).toBe(20);
  });
  test("returns null for out-of-range", () => {
    expect(safeGet([10, 20], 5)).toBeNull();
  });
  test("returns null for negative index", () => {
    expect(safeGet([10], -1)).toBeNull();
  });
  test("returns null for non-array", () => {
    expect(safeGet("not an array", 0)).toBeNull();
    expect(safeGet(null, 0)).toBeNull();
    expect(safeGet(undefined, 0)).toBeNull();
  });
});

describe("asBool", () => {
  test("returns bool for true/false only", () => {
    expect(asBool(true)).toBe(true);
    expect(asBool(false)).toBe(false);
  });
  test("returns null for non-bool inputs", () => {
    expect(asBool(1)).toBeNull();
    expect(asBool("true")).toBeNull();
    expect(asBool(null)).toBeNull();
  });
});

describe("asStr", () => {
  test("returns non-empty string", () => {
    expect(asStr("hello")).toBe("hello");
  });
  test("returns null for empty string", () => {
    expect(asStr("")).toBeNull();
  });
  test("returns null for non-string", () => {
    expect(asStr(42)).toBeNull();
    expect(asStr(null)).toBeNull();
  });
});

describe("asInt", () => {
  test("returns integer for integer inputs", () => {
    expect(asInt(42)).toBe(42);
    expect(asInt(0)).toBe(0);
    expect(asInt(-5)).toBe(-5);
  });
  test("returns null for booleans (they're not ints)", () => {
    expect(asInt(true)).toBeNull();
    expect(asInt(false)).toBeNull();
  });
  test("returns null for non-integers", () => {
    expect(asInt(1.5)).toBeNull();
    expect(asInt("42")).toBeNull();
    expect(asInt(null)).toBeNull();
  });
});

describe("asNonNegativeInt", () => {
  test("returns non-negative integers", () => {
    expect(asNonNegativeInt(0)).toBe(0);
    expect(asNonNegativeInt(42)).toBe(42);
  });
  test("returns null for negatives", () => {
    expect(asNonNegativeInt(-1)).toBeNull();
  });
  test("returns null for non-integers", () => {
    expect(asNonNegativeInt(1.5)).toBeNull();
    expect(asNonNegativeInt(true)).toBeNull();
  });
});
