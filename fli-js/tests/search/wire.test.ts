/**
 * Tests for the wire-format parser shared by all FlightsFrontendService responses.
 * Mirrors tests/search/test_wire.py from the Python tree.
 */

import { describe, expect, test } from "bun:test";
import { iterWrbChunks, parseFirstWrbPayload } from "../../src/search/wire.ts";

function singleChunk(payload: unknown): string {
  // Legacy single-chunk response (no length headers).
  const innerJson = JSON.stringify(payload);
  const outer = [["wrb.fr", null, innerJson]];
  return `)]}'\n\n${JSON.stringify(outer)}`;
}

function multiChunk(...payloads: unknown[]): string {
  // Multi-chunk response with byte-length headers (matches Google's actual format).
  const parts: string[] = [")]}'\n\n"];
  for (const p of payloads) {
    const innerJson = JSON.stringify(p);
    const outerJson = JSON.stringify([["wrb.fr", null, innerJson]]);
    const byteLen = new TextEncoder().encode(outerJson).length + 2;
    parts.push(`${byteLen}\n${outerJson}\n`);
  }
  return parts.join("");
}

describe("iterWrbChunks", () => {
  test("legacy single-chunk format", () => {
    const body = singleChunk([1, "hello", [2, 3]]);
    expect([...iterWrbChunks(body)]).toEqual([[1, "hello", [2, 3]]]);
  });

  test("multi-chunk format yields both", () => {
    const body = multiChunk([1, "alpha"], [2, "beta"]);
    expect([...iterWrbChunks(body)]).toEqual([
      [1, "alpha"],
      [2, "beta"],
    ]);
  });

  test("returns nothing for empty body", () => {
    expect([...iterWrbChunks("")]).toEqual([]);
  });

  test("skips non-wrb rows", () => {
    const body = `)]}'\n\n${JSON.stringify([
      ["di", 44],
      ["af.httprm", 43, "x", 32],
      ["wrb.fr", null, JSON.stringify([1])],
    ])}`;
    expect([...iterWrbChunks(body)]).toEqual([[1]]);
  });

  test("handles malformed inner JSON gracefully", () => {
    const body = `)]}'\n\n${JSON.stringify([["wrb.fr", null, "{not valid"]])}`;
    expect([...iterWrbChunks(body)]).toEqual([]);
  });

  test("non-ASCII chunk payload — UTF-8 byte-length headers", () => {
    const body = multiChunk([1, "東京", "café", "résumé"]);
    expect([...iterWrbChunks(body)]).toEqual([[1, "東京", "café", "résumé"]]);
  });
});

describe("parseFirstWrbPayload", () => {
  test("returns first chunk only", () => {
    const body = multiChunk([1, "alpha"], [2, "beta"]);
    expect(parseFirstWrbPayload(body)).toEqual([1, "alpha"]);
  });

  test("returns null when empty", () => {
    expect(parseFirstWrbPayload("")).toBeNull();
  });
});

describe("iterWrbChunks edge cases", () => {
  test("bytes input works", () => {
    const body = singleChunk([1, "hello"]);
    const fromStr = [...iterWrbChunks(body)];
    const fromBytes = [...iterWrbChunks(new TextEncoder().encode(body))];
    expect(fromBytes).toEqual(fromStr);
  });

  test("prefix-only body returns nothing", () => {
    expect([...iterWrbChunks(")]}'\n\n")]).toEqual([]);
  });

  test("whitespace-only body returns nothing", () => {
    expect([...iterWrbChunks("   \n\n  ")]).toEqual([]);
  });

  test("malformed length header truncates stream", () => {
    const body = ")]}'\n\nabc\n[not parsed]";
    expect([...iterWrbChunks(body)]).toEqual([]);
  });

  test("dict outer is skipped", () => {
    const body = `)]}'\n\n${JSON.stringify({ key: "value" })}`;
    expect([...iterWrbChunks(body)]).toEqual([]);
  });

  test("wrb row with null inner is skipped", () => {
    const body = `)]}'\n\n${JSON.stringify([["wrb.fr", null, null]])}`;
    expect([...iterWrbChunks(body)]).toEqual([]);
  });

  test("wrb row with non-string inner is skipped", () => {
    const body = `)]}'\n\n${JSON.stringify([["wrb.fr", null, [1, 2, 3]]])}`;
    expect([...iterWrbChunks(body)]).toEqual([]);
  });

  test("wrb row too short is skipped", () => {
    const body = `)]}'\n\n${JSON.stringify([["wrb.fr", null]])}`;
    expect([...iterWrbChunks(body)]).toEqual([]);
  });

  test("skips invalid inner to find second valid chunk via parseFirstWrbPayload", () => {
    const goodInner = JSON.stringify([42]);
    const outer = [
      ["wrb.fr", null, "{not valid"],
      ["wrb.fr", null, goodInner],
    ];
    const body = `)]}'\n\n${JSON.stringify(outer)}`;
    expect(parseFirstWrbPayload(body)).toEqual([42]);
  });
});
