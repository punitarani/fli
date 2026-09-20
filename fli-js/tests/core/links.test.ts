/**
 * Tests for the shared Google Flights deep-link helpers.
 */

import { describe, expect, test } from "bun:test";
import { googleFlightsUrl, withLocaleParams } from "../../src/core/links.ts";

describe("withLocaleParams", () => {
  const BASE = "https://www.google.com/travel/flights";

  test("no-op when all null", () => {
    expect(withLocaleParams(BASE, null, null, null)).toBe(BASE);
  });

  test("uppercases currency", () => {
    expect(withLocaleParams(BASE, "eur", null, null)).toBe(`${BASE}?curr=EUR`);
  });

  test("passes language verbatim, uppercases country", () => {
    expect(withLocaleParams(BASE, null, "en-GB", "gb")).toBe(`${BASE}?hl=en-GB&gl=GB`);
  });

  test("uses & when url already has a query", () => {
    expect(withLocaleParams(`${BASE}?q=x`, "USD", null, null)).toBe(`${BASE}?q=x&curr=USD`);
  });
});

describe("googleFlightsUrl", () => {
  test("one-way contains route and date", () => {
    const url = googleFlightsUrl("JFK", "LHR", "2026-07-15");
    expect(url.startsWith("https://www.google.com/travel/flights?q=")).toBe(true);
    expect(url).toContain("JFK");
    expect(url).toContain("LHR");
    expect(url).toContain("2026-07-15");
  });

  test("encodes the natural-language query", () => {
    const url = googleFlightsUrl("JFK", "LHR", "2026-07-15");
    expect(url).toBe(
      "https://www.google.com/travel/flights?q=Flights%20from%20JFK%20to%20LHR%20on%202026-07-15",
    );
  });

  test("round-trip appends the return date", () => {
    const url = googleFlightsUrl("JFK", "LHR", "2026-07-15", "2026-07-22");
    expect(url).toContain("2026-07-22");
    expect(decodeURIComponent(url)).toContain("through 2026-07-22");
  });

  test("locale params appended", () => {
    const url = googleFlightsUrl("JFK", "LHR", "2026-07-15", null, {
      currency: "EUR",
      language: "en-GB",
      country: "GB",
    });
    expect(url).toContain("curr=EUR");
    expect(url).toContain("hl=en-GB");
    expect(url).toContain("gl=GB");
  });
});
