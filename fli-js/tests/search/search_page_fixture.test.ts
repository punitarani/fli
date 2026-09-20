/**
 * `extractPayload` against a real captured search page.
 *
 * Every other fixture the JS suite reads is an RPC body; this one is the
 * page HTML the transport actually reads now, so it is the only offline
 * guard on the regex that finds the `ds:1` blob among the page's other
 * `AF_initDataCallback` blocks. The file keeps that script block exactly
 * as Google served it, inside a minimal HTML shell.
 *
 * It is the same capture the Python suite pins
 * (`tests/search/fixtures/search_page_jfk_lhr_nonstop_ds1.html`), read
 * from its existing path rather than duplicated — the other fixture
 * tests in this directory already share the Python fixtures that way.
 *
 * Same drift policy as the rest: assert structure, never prices or
 * flight numbers.
 */

import { describe, expect, test } from "bun:test";
import { parseFlightRow } from "../../src/search/decoders.ts";
import { extractPayload } from "../../src/search/tfs.ts";

const PAGE = await Bun.file(
  new URL("../../../tests/search/fixtures/search_page_jfk_lhr_nonstop_ds1.html", import.meta.url),
).text();

describe("real search page", () => {
  test("payload is extracted", () => {
    const payload = extractPayload(PAGE);
    expect(Array.isArray(payload)).toBe(true);
    expect((payload as unknown[]).length).toBeGreaterThan(3);
  });

  test("payload decodes into flights through the existing row decoder", () => {
    const payload = extractPayload(PAGE) as unknown[];
    const flights = [];
    for (const index of [2, 3]) {
      const block = index < payload.length ? payload[index] : null;
      if (!Array.isArray(block) || block.length === 0) continue;
      const rows = block[0];
      if (!Array.isArray(rows)) continue;
      for (const row of rows) {
        try {
          flights.push(parseFlightRow(row as unknown[]));
        } catch {
          // One unparseable row must not sink the page.
        }
      }
    }
    expect(flights.length).toBeGreaterThan(0);
    expect(flights.every((f) => f.legs.length > 0)).toBe(true);
    expect(new Set(flights.map((f) => String(f.legs[0]?.departure_airport)))).toEqual(
      new Set(["JFK"]),
    );
  });

  test("fixture carries nothing account-specific", () => {
    const lowered = PAGE.toLowerCase();
    for (const marker of ["set-cookie", "sapisid", "apisid", "hsid", "__secure-", "authuser"]) {
      expect(lowered).not.toContain(marker);
    }
  });
});
