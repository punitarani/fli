import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { parseFlightRow } from "../../src/search/decoders.ts";

const fixture = readFileSync(
  new URL("../../../tests/search/fixtures/flight_search_jfk_lax_oneway_usd.bin", import.meta.url),
  "utf8",
);
const outer = JSON.parse(fixture.slice(fixture.indexOf("[")));
const inner = JSON.parse(outer[0][2]);
const rows: unknown[][] = [2, 3].flatMap((i) => (Array.isArray(inner[i]) ? inner[i][0] : []));

function rowWithRating(rating: unknown, slots: unknown): unknown[] {
  const row = structuredClone(rows[0]) as unknown[];
  const detail = row[0] as unknown[];
  const leg = (detail[2] as unknown[][])[0] as unknown[];
  leg[12] = slots;
  leg[13] = rating;
  return row;
}

describe("legroom rating", () => {
  test("captured flights with the same Wi-Fi tier have different seat ratings", () => {
    const legs = rows.flatMap((row) => parseFlightRow(row).legs);
    const jetblue = legs.find((leg) => leg.airline === "B6" && leg.flight_number === "123");
    const american = legs.find((leg) => leg.airline === "AA" && leg.flight_number === "300");
    expect(jetblue?.amenities?.legroom_rating).toBe(3);
    expect(american?.amenities?.legroom_rating).toBe(1);
  });

  for (const tier of [2, 3]) {
    test.each([
      1, 2, 3, 4, 5, 6, 7, 8, 9,
    ])(`reads seat rating %d with Wi-Fi tier ${tier}`, (rating) => {
      const slots: unknown[] = Array.from({ length: 12 }, () => null);
      slots[11] = tier;
      const flight = parseFlightRow(rowWithRating(rating, slots));
      expect(flight.legs[0]?.amenities?.legroom_rating).toBe(rating);
    });
  }

  test.each<[unknown]>([
    [null],
    [[]],
    ["invalid"],
  ])("preserves rating without amenities array: %j", (slots) => {
    const flight = parseFlightRow(rowWithRating(3, slots));
    expect(flight.legs[0]?.amenities?.legroom_rating).toBe(3);
    expect(flight.legs[0]?.amenities?.wifi).toBeNull();
  });

  test.each([
    null,
    -1,
    true,
    "3",
  ])("does not fall back to Wi-Fi for invalid rating: %j", (rating) => {
    const slots: unknown[] = Array.from({ length: 12 }, () => null);
    slots[1] = true;
    slots[11] = 2;
    const flight = parseFlightRow(rowWithRating(rating, slots));
    expect(flight.legs[0]?.amenities?.legroom_rating).toBeNull();
  });

  test("returns no amenities when neither source has data", () => {
    expect(parseFlightRow(rowWithRating(null, null)).legs[0]?.amenities).toBeNull();
  });
});
