/**
 * Low-level `tfs` protobuf encoder tests.
 *
 * The tokens below were issued by Google itself for the same queries (the
 * same captures the Python suite pins in `tests/search/test_tfs.py`), so a
 * byte mismatch means the encoder has drifted from what Google accepts.
 *
 * These exercise `encodeTfsSegment` / `encodeTfsPayload` directly rather
 * than through `buildTfs`, because the captures carry 2026 travel dates
 * that `FlightSegment` now rejects as past — see `tfs.test.ts` for the
 * filter-level goldens, which use dates far enough out to stay valid.
 */

import { describe, expect, test } from "bun:test";
import { buildTfsToken, encodeTfsPayload, encodeTfsSegment } from "../../src/search/proto.ts";

// Captured from Google's own search-page URLs (2026-08-26) for
// JFK -> LAX on 2026-09-15, returning 2026-09-19.
const TFS_ONE_WAY = "CBwQAhoeEgoyMDI2LTA5LTE1agcIARIDSkZLcgcIARIDTEFYQAFIAXABmAEC";
const TFS_NON_STOP = "CBwQAhogEgoyMDI2LTA5LTE1KABqBwgBEgNKRktyBwgBEgNMQVhAAUgBcAGYAQI";
const TFS_ROUND_TRIP =
  "CBwQAhoeEgoyMDI2LTA5LTE1agcIARIDSkZLcgcIARIDTEFYGh4SCjIwMjYtMDktMTlqBwgBEgNMQVhy" +
  "BwgBEgNKRktAAUgBcAGYAQE";
const TFS_MULTI_AIRPORT =
  "CBwQAho5EgoyMDI2LTEwLTE1agcIARIDQk9NagcIARIDREVMagcIARIDQU1EcgcIARIDT1JEcgcIARIDRFRX" +
  "QAFIAXABmAEC";

function concat(...parts: Uint8Array[]): Uint8Array {
  let total = 0;
  for (const p of parts) total += p.length;
  const out = new Uint8Array(total);
  let off = 0;
  for (const p of parts) {
    out.set(p, off);
    off += p.length;
  }
  return out;
}

function decode(tfs: string): Uint8Array {
  const padded = tfs + "=".repeat((4 - (tfs.length % 4)) % 4);
  return new Uint8Array(Buffer.from(padded.replace(/-/g, "+").replace(/_/g, "/"), "base64"));
}

function includesBytes(haystack: Uint8Array, needle: number[]): boolean {
  outer: for (let i = 0; i + needle.length <= haystack.length; i++) {
    for (let j = 0; j < needle.length; j++) {
      if (haystack[i + j] !== needle[j]) continue outer;
    }
    return true;
  }
  return false;
}

describe("encodeTfsSegment / encodeTfsPayload", () => {
  test("one-way matches the tfs Google issued", () => {
    const seg = encodeTfsSegment("JFK", "LAX", "2026-09-15");
    expect(encodeTfsPayload(seg, { isOneWay: true })).toBe(TFS_ONE_WAY);
  });

  test("non-stop matches the tfs Google issued", () => {
    const seg = encodeTfsSegment("JFK", "LAX", "2026-09-15", { maxStops: 0 });
    expect(encodeTfsPayload(seg, { isOneWay: true })).toBe(TFS_NON_STOP);
  });

  test("round trip matches the tfs Google issued", () => {
    const segs = concat(
      encodeTfsSegment("JFK", "LAX", "2026-09-15"),
      encodeTfsSegment("LAX", "JFK", "2026-09-19"),
    );
    expect(encodeTfsPayload(segs, { isOneWay: false })).toBe(TFS_ROUND_TRIP);
  });

  test("multi-airport matches the tfs Google issued", () => {
    const seg = encodeTfsSegment(["BOM", "DEL", "AMD"], ["ORD", "DTW"], "2026-10-15");
    expect(encodeTfsPayload(seg, { isOneWay: true })).toBe(TFS_MULTI_AIRPORT);
  });

  test("maxStops null omits the ceiling entirely", () => {
    // Writing 0 for "any" would silently pin every search to non-stop.
    const any = encodeTfsPayload(encodeTfsSegment("JFK", "LAX", "2026-09-15"), { isOneWay: true });
    expect(any).toBe(TFS_ONE_WAY);
    expect(any).not.toBe(TFS_NON_STOP);
  });

  test("stop ceiling is zero-based and sits in field 5", () => {
    for (const ceiling of [0, 1, 2]) {
      const raw = decode(
        encodeTfsPayload(encodeTfsSegment("JFK", "LAX", "2026-09-15", { maxStops: ceiling }), {
          isOneWay: true,
        }),
      );
      expect(includesBytes(raw, [0x28, ceiling])).toBe(true);
    }
  });

  test("buildTfsToken is the same encoder, not a fork", () => {
    // `buildTfsToken` (booking deep links) and `buildTfs` (search pages)
    // write the same message; the deep link only adds the field-16 pin.
    // Byte-for-byte captures for `buildTfsToken` itself live in
    // `proto.test.ts` — this pins that it composes the shared helpers.
    const legs = [
      { origin: "SFO", depDate: "2026-06-15", dest: "PHX", airline: "AA", flightNumber: "2413" },
    ];
    const viaHelpers = encodeTfsPayload(encodeTfsSegment("SFO", "PHX", "2026-06-15", { legs }), {
      isOneWay: true,
      pinMaxU64: true,
    });
    expect(buildTfsToken([legs], { isOneWay: true })).toBe(viaHelpers);
  });
});
