/**
 * Tests for the GetBookingResults protobuf token builder + tfu URL parser.
 *
 * The builder must reproduce a byte-perfect copy of the captured token —
 * any change to the encoder must keep the captured fixture passing.
 */

import { describe, expect, test } from "bun:test";
import { Buffer } from "node:buffer";
import type { PassengerInfo } from "../../src/models/google-flights/base.ts";
import {
  _readVarint,
  buildBookingToken,
  buildTfsToken,
  decodeBookingToken,
  extractBookingTokenFromTfu,
  extractSessionIdFromTfu,
  type LegSpec,
  passengerCodes,
} from "../../src/search/proto.ts";

// Captured live 2026-05-14 (JFK → LAX outbound AA171, return AA28, RT $346.80).
const CAPTURED_TOKEN =
  "CjRIUHJ1SE9pTmdoeUVBQ0U1S2dCRy0tLS0tLS0tLS1wZm4zOUFBQUFBR29GZ2tjSG5SRHdBEgZBQTI4IzEaCwj4jgIQAhoDVVNEOBxw+I4C";
const CAPTURED_SESSION = "HPruHOiNghyEACE5KgBG----------pfn39AAAAAGoFgkcHnRDwA";

function unpadBase64(token: string): string {
  const pad = (4 - (token.length % 4)) % 4;
  return token + "=".repeat(pad);
}

function decodeUrlsafe(token: string): Uint8Array {
  return new Uint8Array(
    Buffer.from(unpadBase64(token).replace(/-/g, "+").replace(/_/g, "/"), "base64"),
  );
}

describe("buildBookingToken", () => {
  test("byte-perfect reproduction of captured token", () => {
    const built = buildBookingToken({
      sessionId: CAPTURED_SESSION,
      airlineCode: "AA",
      flightNumber: "28",
      legIndex: 1,
      priceCents: 34680,
      currency: "USD",
    });
    const bBuilt = new Uint8Array(Buffer.from(unpadBase64(built), "base64"));
    const bCapt = decodeUrlsafe(CAPTURED_TOKEN);
    expect(Buffer.from(bBuilt).toString("hex")).toBe(Buffer.from(bCapt).toString("hex"));
  });

  test("round-trip decode", () => {
    const token = buildBookingToken({
      sessionId: "ABC123",
      airlineCode: "DL",
      flightNumber: "100",
      legIndex: 1,
      priceCents: 12345,
      currency: "EUR",
    });
    const decoded = decodeBookingToken(token);
    expect(decoded.field_1).toBe("ABC123");
    expect(decoded.field_2).toBe("DL100#1");
    expect(decoded.field_3).toEqual({ field_1: 12345, field_2: 2, field_3: "EUR" });
    expect(decoded.field_7).toBe(28);
    expect(decoded.field_14).toBe(12345);
  });

  test.each(["USD", "EUR", "GBP", "JPY", "INR"])("currency %s round-trips", (code) => {
    const token = buildBookingToken({
      sessionId: "S",
      airlineCode: "DL",
      flightNumber: "1",
      legIndex: 1,
      priceCents: 100,
      currency: code,
    });
    const decoded = decodeBookingToken(token);
    expect((decoded.field_3 as Record<string, unknown>).field_3).toBe(code);
  });

  test.each([0, 1, 2, 5, 10])("leg index %d appears in field 2", (idx) => {
    const token = buildBookingToken({
      sessionId: "S",
      airlineCode: "AA",
      flightNumber: "100",
      legIndex: idx,
      priceCents: 100,
      currency: "USD",
    });
    const decoded = decodeBookingToken(token);
    expect(decoded.field_2).toBe(`AA100#${idx}`);
  });

  test("price varint encoding (3-byte case)", () => {
    const token = buildBookingToken({
      sessionId: "S",
      airlineCode: "AA",
      flightNumber: "1",
      legIndex: 1,
      priceCents: 34680,
      currency: "USD",
    });
    const decoded = decodeBookingToken(token);
    expect((decoded.field_3 as Record<string, unknown>).field_1).toBe(34680);
    expect(decoded.field_14).toBe(34680);
  });

  test("large price (>6 digits)", () => {
    const token = buildBookingToken({
      sessionId: "S",
      airlineCode: "AA",
      flightNumber: "1",
      legIndex: 1,
      priceCents: 1_234_567,
      currency: "USD",
    });
    const decoded = decodeBookingToken(token);
    expect((decoded.field_3 as Record<string, unknown>).field_1).toBe(1_234_567);
  });

  test("decode captured token", () => {
    const decoded = decodeBookingToken(CAPTURED_TOKEN);
    expect(decoded.field_1).toBe(CAPTURED_SESSION);
    expect(decoded.field_2).toBe("AA28#1");
    expect(decoded.field_3).toEqual({ field_1: 34680, field_2: 2, field_3: "USD" });
    expect(decoded.field_7).toBe(28);
    expect(decoded.field_14).toBe(34680);
  });
});

describe("buildBookingToken validation", () => {
  const cases: Array<{
    args: Parameters<typeof buildBookingToken>[0];
    match: string;
  }> = [
    {
      args: {
        sessionId: "S",
        airlineCode: "AA",
        flightNumber: "1",
        legIndex: 1,
        priceCents: -1,
        currency: "USD",
      },
      match: "price_cents must be non-negative",
    },
    {
      args: {
        sessionId: "",
        airlineCode: "AA",
        flightNumber: "1",
        legIndex: 1,
        priceCents: 100,
        currency: "USD",
      },
      match: "session_id must be non-empty",
    },
    {
      args: {
        sessionId: "S",
        airlineCode: "",
        flightNumber: "1",
        legIndex: 1,
        priceCents: 100,
        currency: "USD",
      },
      match: "airline_code must be non-empty",
    },
    {
      args: {
        sessionId: "S",
        airlineCode: "AA",
        flightNumber: "",
        legIndex: 1,
        priceCents: 100,
        currency: "USD",
      },
      match: "flight_number must be non-empty",
    },
    {
      args: {
        sessionId: "S",
        airlineCode: "AA",
        flightNumber: "1",
        legIndex: 1,
        priceCents: 100,
        currency: "",
      },
      match: "currency must be non-empty",
    },
  ];
  test.each(cases)("rejects bad input (%#)", ({ args, match }) => {
    expect(() => buildBookingToken(args)).toThrow(match);
  });
});

describe("_readVarint", () => {
  test.each<[Uint8Array, [number, number]]>([
    [new Uint8Array([0x00]), [0, 1]],
    [new Uint8Array([0x7f]), [127, 1]],
    [new Uint8Array([0x80, 0x01]), [128, 2]],
  ])("decodes correctly", (data, expected) => {
    expect(_readVarint(data, 0)).toEqual(expected);
  });

  test("truncated varint raises", () => {
    expect(() => _readVarint(new Uint8Array([0x80]), 0)).toThrow();
  });

  test("decodes values ≥ 2^31 without sign-bit corruption", () => {
    // Naive `|= <<` decoders break here: shift=28 yields a 5th byte whose
    // top bits land at bit 31+, which JavaScript's signed-32 bitwise ops
    // would render as a negative number.
    const cases: Array<[number, Uint8Array]> = [
      [2 ** 31, new Uint8Array([0x80, 0x80, 0x80, 0x80, 0x08])],
      [2 ** 32, new Uint8Array([0x80, 0x80, 0x80, 0x80, 0x10])],
      [2 ** 40, new Uint8Array([0x80, 0x80, 0x80, 0x80, 0x80, 0x20])],
    ];
    for (const [expected, bytes] of cases) {
      const [decoded] = _readVarint(bytes, 0);
      expect(decoded).toBe(expected);
    }
  });
});

// Live `tfu` URL parameter captured 2026-05-14 from a JFK→LAX RT booking page.
const LIVE_TFU =
  "CmxDalJJVVZwUk1FOUJjRVZyZEVWQlEzaFRkVkZDUnkwdExTMHRMUzB0TFhCcVltWjZOMEZCUVVGQlIyOUdPVlpGU0U5SVVXRkJFZ1pCUVRJNEl6RWFDd2o0amdJUUFob0RWVk5FT0J4dytJNEMSAggAIgA";
const LIVE_BOOKING_URL = `https://www.google.com/travel/flights/booking?tfs=CBwQAho_EgoyMDI2LTA3LTE1Ih8KA0pGSxIKMjAyNi0wNy0xNRoDTEFYKgJBQTIDMTcxagcIARIDSkZLcgcIARIDTEFYGj4SCjIwMjYtMDctMTkiHgoDTEFYEgoyMDI2LTA3LTE5GgNKRksqAkFBMgIyOGoHCAESA0xBWHIHCAESA0pGS0ABSAFwAYIBCwj___________8BmAEB&tfu=${LIVE_TFU}&hl=en&gl=US&curr=USD`;

describe("extractBookingTokenFromTfu", () => {
  test("extract from bare tfu value", () => {
    const token = extractBookingTokenFromTfu(LIVE_TFU);
    const decoded = decodeBookingToken(token);
    expect(decoded.field_2).toBe("AA28#1");
    expect((decoded.field_3 as Record<string, unknown>).field_3).toBe("USD");
  });

  test("extract from full booking URL", () => {
    const fromUrl = extractBookingTokenFromTfu(LIVE_BOOKING_URL);
    const fromBare = extractBookingTokenFromTfu(LIVE_TFU);
    expect(fromUrl).toBe(fromBare);
  });

  test("extract session id round-trips", () => {
    const session = extractSessionIdFromTfu(LIVE_TFU);
    expect(typeof session).toBe("string");
    expect(session.length).toBeGreaterThan(30);
    expect(session.startsWith("H")).toBe(true);
    expect(session.includes("-")).toBe(true);
  });

  test("URL without tfu param rejected", () => {
    expect(() =>
      extractBookingTokenFromTfu("https://www.google.com/travel/flights/booking?tfs=ABC&hl=en"),
    ).toThrow();
  });
});

// Captured live 2026-05-28 — byte-perfect golden references for the tfs token.
// Round-trip JFK→LAX (AA171 out, AA28 return).
const LIVE_TFS_RT =
  "CBwQAho_EgoyMDI2LTA3LTE1Ih8KA0pGSxIKMjAyNi0wNy0xNRoDTEFYKgJBQTIDMTcxagcIAR" +
  "IDSkZLcgcIARIDTEFYGj4SCjIwMjYtMDctMTkiHgoDTEFYEgoyMDI2LTA3LTE5GgNKRksqAkFBMgIy" +
  "OGoHCAESA0xBWHIHCAESA0pGS0ABSAFwAYIBCwj___________8BmAEB";
// One-way nonstop LAX→ORD (UA729).
const LIVE_TFS_OW =
  "CBwQAho_EgoyMDI2LTA4LTE1Ih8KA0xBWBIKMjAyNi0wOC0xNRoDT1JEKgJVQTIDNzI5" +
  "agcIARIDTEFYcgcIARIDT1JEQAFIAXABggELCP___________wGYAQI";
// One-way 2-stop BOS→DEN(WN739)→SJC(WN389)→SEA(WN389).
const LIVE_TFS_3LEG =
  "CBwQAhqBARIKMjAyNi0wOC0xNSIfCgNCT1MSCjIwMjYtMDgtMTUaA0RFTioCV04yAzczOSIfCgNERU4S" +
  "CjIwMjYtMDgtMTUaA1NKQyoCV04yAzM4OSIfCgNTSkMSCjIwMjYtMDgtMTUaA1NFQSoCV04yAzM4OWoH" +
  "CAESA0JPU3IHCAESA1NFQUABSAFwAYIBCwj___________8BmAEC";

function tfsBytes(tfs: string): Uint8Array {
  return decodeUrlsafe(tfs);
}

describe("buildTfsToken", () => {
  test("round-trip reproduces captured tfs byte-for-byte", () => {
    const segments: LegSpec[][] = [
      [{ origin: "JFK", depDate: "2026-07-15", dest: "LAX", airline: "AA", flightNumber: "171" }],
      [{ origin: "LAX", depDate: "2026-07-19", dest: "JFK", airline: "AA", flightNumber: "28" }],
    ];
    const built = buildTfsToken(segments, { isOneWay: false });
    expect([...tfsBytes(built)]).toEqual([...tfsBytes(LIVE_TFS_RT)]);
  });

  test("one-way nonstop reproduces captured tfs byte-for-byte", () => {
    const segments: LegSpec[][] = [
      [{ origin: "LAX", depDate: "2026-08-15", dest: "ORD", airline: "UA", flightNumber: "729" }],
    ];
    const built = buildTfsToken(segments, { isOneWay: true });
    expect([...tfsBytes(built)]).toEqual([...tfsBytes(LIVE_TFS_OW)]);
  });

  test("multi-leg connection reproduces captured tfs byte-for-byte", () => {
    const segments: LegSpec[][] = [
      [
        { origin: "BOS", depDate: "2026-08-15", dest: "DEN", airline: "WN", flightNumber: "739" },
        { origin: "DEN", depDate: "2026-08-15", dest: "SJC", airline: "WN", flightNumber: "389" },
        { origin: "SJC", depDate: "2026-08-15", dest: "SEA", airline: "WN", flightNumber: "389" },
      ],
    ];
    const built = buildTfsToken(segments, { isOneWay: true });
    expect([...tfsBytes(built)]).toEqual([...tfsBytes(LIVE_TFS_3LEG)]);
  });

  test("f19 is 2 for one-way", () => {
    const built = buildTfsToken(
      [[{ origin: "SFO", depDate: "2026-09-01", dest: "PHX", airline: "AA", flightNumber: "100" }]],
      { isOneWay: true },
    );
    const raw = tfsBytes(built);
    expect(Array.from(raw.slice(-3))).toEqual([0x98, 0x01, 0x02]);
  });

  test("f19 is 1 for round-trip", () => {
    const built = buildTfsToken(
      [
        [{ origin: "JFK", depDate: "2026-09-01", dest: "LAX", airline: "AA", flightNumber: "1" }],
        [{ origin: "LAX", depDate: "2026-09-08", dest: "JFK", airline: "AA", flightNumber: "2" }],
      ],
      { isOneWay: false },
    );
    const raw = tfsBytes(built);
    expect(Array.from(raw.slice(-3))).toEqual([0x98, 0x01, 0x01]);
  });

  test("urlsafe, no padding", () => {
    const built = buildTfsToken([
      [{ origin: "SFO", depDate: "2026-09-01", dest: "PHX", airline: "AA", flightNumber: "100" }],
    ]);
    expect(built.includes("=")).toBe(false);
    expect(built.includes("+")).toBe(false);
    expect(built.includes("/")).toBe(false);
  });

  test("three legs encode to 159 bytes", () => {
    const segments: LegSpec[][] = [
      [
        { origin: "BOS", depDate: "2026-08-15", dest: "DEN", airline: "WN", flightNumber: "739" },
        { origin: "DEN", depDate: "2026-08-15", dest: "SJC", airline: "WN", flightNumber: "389" },
        { origin: "SJC", depDate: "2026-08-15", dest: "SEA", airline: "WN", flightNumber: "389" },
      ],
    ];
    expect(tfsBytes(buildTfsToken(segments, { isOneWay: true })).length).toBe(159);
  });

  test("empty segments throws", () => {
    expect(() => buildTfsToken([])).toThrow("non-empty");
  });

  test("empty leg list throws", () => {
    expect(() => buildTfsToken([[]])).toThrow("no legs");
  });

  test("seat defaults to economy (field 9 = 1)", () => {
    const built = buildTfsToken([
      [{ origin: "SFO", depDate: "2026-09-01", dest: "PHX", airline: "AA", flightNumber: "100" }],
    ]);
    const raw = tfsBytes(built);
    const text = Buffer.from(raw);
    expect(text.includes(Buffer.from([0x40, 0x01, 0x48, 0x01, 0x70, 0x01]))).toBe(true);
  });

  test("seat=3 encodes field 9 as business", () => {
    const segs: LegSpec[][] = [
      [{ origin: "SFO", depDate: "2026-09-01", dest: "PHX", airline: "AA", flightNumber: "100" }],
    ];
    const economy = tfsBytes(buildTfsToken(segs));
    const business = tfsBytes(buildTfsToken(segs, { seat: 3 }));
    expect(Buffer.from(economy).includes(Buffer.from([0x48, 0x01]))).toBe(true);
    expect(Buffer.from(business).includes(Buffer.from([0x48, 0x03]))).toBe(true);
    expect(Buffer.from(economy).equals(Buffer.from(business))).toBe(false);
  });

  /** Walk the top-level message and collect every field-8 (passenger) code. */
  function field8Codes(raw: Uint8Array): number[] {
    const codes: number[] = [];
    let offset = 0;
    while (offset < raw.length) {
      const [tagVal, afterTag] = _readVarint(raw, offset);
      offset = afterTag;
      const field = tagVal >> 3;
      const wire = tagVal & 0x7;
      if (wire === 0) {
        const [value, afterVal] = _readVarint(raw, offset);
        offset = afterVal;
        if (field === 8) codes.push(value);
      } else if (wire === 2) {
        const [length, afterLen] = _readVarint(raw, offset);
        offset = afterLen + length;
      } else {
        throw new Error(`unexpected wire type ${wire} at offset ${offset}`);
      }
    }
    return codes;
  }

  test("passengers defaults to a single adult", () => {
    const built = buildTfsToken([
      [{ origin: "SFO", depDate: "2026-09-01", dest: "PHX", airline: "AA", flightNumber: "100" }],
    ]);
    expect(field8Codes(tfsBytes(built))).toEqual([1]);
  });

  test("passengers=[1,1,2] (2 adults, 1 child) encodes one entry per traveller", () => {
    const built = buildTfsToken(
      [[{ origin: "SFO", depDate: "2026-09-01", dest: "PHX", airline: "AA", flightNumber: "100" }]],
      { passengers: [1, 1, 2] },
    );
    expect(field8Codes(tfsBytes(built))).toEqual([1, 1, 2]);
  });

  test("passengers do not disturb the seat or trip-type fields", () => {
    const segs: LegSpec[][] = [
      [{ origin: "SFO", depDate: "2026-09-01", dest: "PHX", airline: "AA", flightNumber: "100" }],
    ];
    const built = buildTfsToken(segs, { passengers: [1, 1, 2], seat: 3 });
    const raw = tfsBytes(built);
    const text = Buffer.from(raw);
    // Three f8 entries, then f9=3 (business), then f14=1 — same layout as
    // the single-passenger case, just with more f8 entries ahead of f9.
    expect(
      text.includes(Buffer.from([0x40, 0x01, 0x40, 0x01, 0x40, 0x02, 0x48, 0x03, 0x70, 0x01])),
    ).toBe(true);
    // f19 (trip type) is unaffected by the passenger count.
    expect(Array.from(raw.slice(-3))).toEqual([0x98, 0x01, 0x02]);
  });
});

describe("passengerCodes", () => {
  // Maps a PassengerInfo to `tfs` field-8 codes — extracted out of
  // `tfs.ts::buildTfs` so the search token and the booking token
  // (buildTfsToken) cannot drift on how they encode the passenger mix.

  test("family mix", () => {
    expect(passengerCodes({ adults: 2, children: 1, infants_on_lap: 1 })).toEqual([1, 1, 2, 3]);
  });

  test("infant in seat is code 4", () => {
    expect(passengerCodes({ adults: 1, infants_in_seat: 1 })).toEqual([1, 4]);
  });

  test("null/undefined defaults to a single adult", () => {
    expect(passengerCodes(null)).toEqual([1]);
    expect(passengerCodes(undefined)).toEqual([1]);
  });

  test("object with no passenger fields defaults to a single adult", () => {
    expect(passengerCodes({})).toEqual([1]);
  });

  test("exactly nine travellers is accepted", () => {
    const info = { adults: 4, children: 2, infants_in_seat: 2, infants_on_lap: 1 };
    expect(passengerCodes(info)).toHaveLength(9);
  });

  test("ten travellers, one over the ceiling, throws", () => {
    expect(() => passengerCodes({ adults: 10, children: 0 })).toThrow(RangeError);
  });

  test("ten travellers spread across two fields throws", () => {
    expect(() => passengerCodes({ adults: 5, children: 5 })).toThrow(RangeError);
  });

  test("a negative count throws, naming the field", () => {
    expect(() => passengerCodes({ adults: -1 })).toThrow(/adults/);
  });

  test.each([2.5, "3", true])("a non-integer count (%p) throws", (bad) => {
    expect(() => passengerCodes({ adults: bad as unknown as number })).toThrow(RangeError);
  });

  test("a duck-typed count in the millions throws immediately, not after building a list", () => {
    // Before this guard, an `adults: 1_000_000`-shaped object made this
    // function (and everything downstream, including the booking token)
    // spend tens of seconds building a multi-megabyte array instead of
    // rejecting the obviously-impossible count up front.
    const start = performance.now();
    expect(() => passengerCodes({ adults: 1_000_000 })).toThrow(RangeError);
    expect(performance.now() - start).toBeLessThan(1000);
  });
});

describe("passengerCodes accept/reject table", () => {
  // Same table as Python's `TestPassengerCodesAcceptRejectTable` in
  // tests/search/test_proto.py — both languages must reach the same
  // accept/reject verdict for each row. Keep the two in sync.
  const cases: Array<[string, { adults: unknown; children?: unknown }, boolean]> = [
    ["baseline single adult", { adults: 1 }, true],
    ["all-zero mix still books one adult", { adults: 0, children: 0 }, true],
    ["exactly Google's ceiling", { adults: 9 }, true],
    ["one over the ceiling", { adults: 10 }, false],
    ["ceiling crossed by summing two fields", { adults: 5, children: 5 }, false],
    ["negative count", { adults: -1 }, false],
    ["non-integer count (float)", { adults: 2.5 }, false],
    ["non-integer count (numeric string)", { adults: "3" }, false],
    ["boolean count", { adults: true }, false],
  ];

  for (const [label, info, accepted] of cases) {
    test(`${label} -> ${accepted ? "accepted" : "rejected"}`, () => {
      if (accepted) {
        expect(() => passengerCodes(info as Partial<PassengerInfo>)).not.toThrow();
      } else {
        expect(() => passengerCodes(info as Partial<PassengerInfo>)).toThrow(RangeError);
      }
    });
  }
});
