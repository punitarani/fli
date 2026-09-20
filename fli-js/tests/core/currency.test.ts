/**
 * Tests for currency token extraction + price formatting.
 * Mirrors tests/core/test_currency.py and tests/core/test_currency_parser.py.
 */

import { describe, expect, test } from "bun:test";
import {
  _clearCurrencyCache,
  extractCurrencyFromPriceToken,
  formatPrice,
  formatPriceAxisLabel,
} from "../../src/core/currency.ts";
import { ParseError, parseCurrency } from "../../src/core/parsers.ts";

const SHOPPING_TOKEN =
  "CjRIQktCNmV1UjNqNjhBR043X0FCRy0tLS0tLS0tLS12dGpkN0FBQUFBR25JcWZNS2pGTTBBEgZVQTIyMDkaCgjcWxACGgNVU0Q4HHDcWw==";

describe("extractCurrencyFromPriceToken", () => {
  test("decodes USD from captured shopping token", () => {
    _clearCurrencyCache();
    expect(extractCurrencyFromPriceToken(SHOPPING_TOKEN)).toBe("USD");
  });

  test("returns null for invalid token (fail closed)", () => {
    expect(extractCurrencyFromPriceToken("not-a-valid-token")).toBeNull();
  });

  test("null/empty returns null", () => {
    expect(extractCurrencyFromPriceToken(null)).toBeNull();
    expect(extractCurrencyFromPriceToken("")).toBeNull();
    expect(extractCurrencyFromPriceToken(undefined)).toBeNull();
  });

  test("repeat calls hit cache (smoke)", () => {
    _clearCurrencyCache();
    expect(extractCurrencyFromPriceToken(SHOPPING_TOKEN)).toBe("USD");
    expect(extractCurrencyFromPriceToken(SHOPPING_TOKEN)).toBe("USD"); // cached
  });
});

describe("formatPrice", () => {
  test("formats with currency code", () => {
    // Intl behavior is locale-stable; HKD uses "HK$" in en-US narrowSymbol.
    expect(formatPrice(118, "HKD")).toContain("118");
    expect(formatPrice(118, "HKD")).toMatch(/HK\$|HK \$|HKD/);
  });

  test("formats USD with $", () => {
    const out = formatPrice(99.5, "USD");
    expect(out).toContain("99.50");
    expect(out).toContain("$");
  });

  test("no currency renders plain number", () => {
    expect(formatPrice(118, null)).toBe("118.00");
  });

  test("null amount with currency yields placeholder", () => {
    expect(formatPrice(null, "USD")).toBe("USD —");
  });

  test("null amount with no currency is bare em dash", () => {
    expect(formatPrice(null, null)).toBe("—");
  });

  test("null amount with empty currency is bare em dash", () => {
    expect(formatPrice(null, "")).toBe("—");
  });
});

describe("formatPriceAxisLabel", () => {
  test("single currency", () => {
    expect(formatPriceAxisLabel(["EUR", "EUR"])).toBe("Price (EUR)");
  });
  test("mixed currencies", () => {
    expect(formatPriceAxisLabel(["EUR", "USD"])).toBe("Price");
  });
});

describe("parseCurrency", () => {
  test("null/empty pass through", () => {
    expect(parseCurrency(null)).toBeNull();
    expect(parseCurrency("")).toBeNull();
  });
  test("known uppercase", () => {
    expect(parseCurrency("USD")).toBe("USD");
  });
  test("lowercase is uppercased", () => {
    expect(parseCurrency("eur")).toBe("EUR");
  });
  test("whitespace stripped", () => {
    expect(parseCurrency("  gbp  ")).toBe("GBP");
  });
  test("unknown 3-letter passes through", () => {
    expect(parseCurrency("xpf")).toBe("XPF");
  });
  test("too short throws", () => {
    expect(() => parseCurrency("EU")).toThrow(ParseError);
  });
  test("too long throws", () => {
    expect(() => parseCurrency("EUROS")).toThrow(ParseError);
  });
  test("digits throws", () => {
    expect(() => parseCurrency("US1")).toThrow(ParseError);
  });
});
