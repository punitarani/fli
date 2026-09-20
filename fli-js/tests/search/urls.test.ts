/**
 * Tests for the URL query-parameter helper.
 * Mirrors tests/search/test_locale_params.py.
 */

import { describe, expect, test } from "bun:test";
import { withLocaleParams } from "../../src/search/urls.ts";

const BASE = "https://www.google.com/_/FlightsFrontendUi/data/x/y";

describe("withLocaleParams", () => {
  test("no params returns url unchanged", () => {
    expect(withLocaleParams(BASE, null, null, null)).toBe(BASE);
  });

  test("currency only appends curr", () => {
    expect(withLocaleParams(BASE, "EUR", null, null)).toBe(`${BASE}?curr=EUR`);
  });

  test("currency is uppercased", () => {
    expect(withLocaleParams(BASE, "eur", null, null)).toBe(`${BASE}?curr=EUR`);
  });

  test("language only", () => {
    expect(withLocaleParams(BASE, null, "en-GB", null)).toBe(`${BASE}?hl=en-GB`);
  });

  test("country is uppercased", () => {
    expect(withLocaleParams(BASE, null, null, "gb")).toBe(`${BASE}?gl=GB`);
  });

  test("all three params in order", () => {
    expect(withLocaleParams(BASE, "JPY", "ja", "JP")).toBe(`${BASE}?curr=JPY&hl=ja&gl=JP`);
  });

  test("appends to existing query string", () => {
    expect(withLocaleParams(`${BASE}?foo=bar`, "EUR", null, null)).toBe(`${BASE}?foo=bar&curr=EUR`);
  });

  test("non-ASCII language is percent-encoded", () => {
    // 日本 → E6 97 A5 E6 9C AC
    expect(withLocaleParams(BASE, null, "日本", null)).toBe(`${BASE}?hl=%E6%97%A5%E6%9C%AC`);
  });

  test("query-param injection is blocked", () => {
    const out = withLocaleParams(BASE, null, "en&gl=XX", null);
    expect(out).not.toContain("&gl=XX");
    expect(out).toContain("%26gl%3DXX");
  });

  test("equals sign in value encoded", () => {
    expect(withLocaleParams(BASE, null, "x=y", null)).toContain("?hl=x%3Dy");
  });
});
