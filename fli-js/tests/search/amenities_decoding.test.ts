import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import type { FlightLeg, FlightResult } from "../../src/models/google-flights/base.ts";
import { SeatType } from "../../src/models/google-flights/base.ts";
import { parseFlightRow } from "../../src/search/decoders.ts";

/**
 * Mirror of tests/search/test_amenities_decoding.py (issue #217).
 *
 * Every expectation is pinned to a named flight in a captured Google
 * Flights response. The slot mapping was verified by tabulating
 * leg[12][0..11], leg[13], leg[14] and leg[16] across ~280 distinct legs:
 * slots 1..6 are a mutually-exclusive power group, slots 8..10 a
 * mutually-exclusive video group, and slot 11 a Wi-Fi tier code.
 */

function load(name: string): FlightResult[] {
  const fixture = readFileSync(
    new URL(`../../../tests/search/fixtures/${name}`, import.meta.url),
    "utf8",
  );
  const outer = JSON.parse(fixture.slice(fixture.indexOf("[")));
  const inner = JSON.parse(outer[0][2]);
  const rows: unknown[][] = [2, 3].flatMap((i) => (Array.isArray(inner[i]) ? inner[i][0] : []));
  const flights: FlightResult[] = [];
  for (const row of rows) {
    try {
      flights.push(parseFlightRow(row));
    } catch {
      // Malformed / sponsor rows are skipped, same as the Python replay.
    }
  }
  return flights;
}

function rawLegs(name: string): unknown[][] {
  const fixture = readFileSync(
    new URL(`../../../tests/search/fixtures/${name}`, import.meta.url),
    "utf8",
  );
  const outer = JSON.parse(fixture.slice(fixture.indexOf("[")));
  const inner = JSON.parse(outer[0][2]);
  const rows: unknown[][] = [2, 3].flatMap((i) => (Array.isArray(inner[i]) ? inner[i][0] : []));
  return rows.flatMap((row) => ((row[0] as unknown[])[2] as unknown[][]) ?? []);
}

function leg(flights: FlightResult[], carrier: string, number: string): FlightLeg {
  for (const flight of flights) {
    for (const l of flight.legs) {
      if (l.airline === carrier && l.flight_number === number) return l;
    }
  }
  throw new Error(`${carrier}${number} not found in fixture`);
}

const FIXTURES = [
  "flight_search_jfk_lax_oneway_usd.bin",
  "flight_search_jfk_lax_eur.bin",
  "flight_search_jfk_lax_exclude_dl.bin",
  "flight_search_jfk_fra_oneworld.bin",
  "flight_search_buf_ath_min_layover_120.bin",
  "flight_search_lax_lhr_rt_biz_2a1c.bin",
];

const jfkLax = load("flight_search_jfk_lax_oneway_usd.bin");
const jfkFra = load("flight_search_jfk_fra_oneworld.bin");
const bufAth = load("flight_search_buf_ath_min_layover_120.bin");
const jfkLaxNoDl = load("flight_search_jfk_lax_exclude_dl.bin");
const laxLhrBiz = load("flight_search_lax_lhr_rt_biz_2a1c.bin");

describe("wifi tier (leg[12][11])", () => {
  test("JetBlue reports free Wi-Fi", () => {
    const l = leg(jfkLax, "B6", "123");
    expect(l.amenities?.wifi).toBe(true);
    expect(l.amenities?.wifi_tier).toBe("free");
  });

  test("Delta transcon reports free Wi-Fi", () => {
    const l = leg(jfkLax, "DL", "707");
    expect(l.amenities?.wifi).toBe(true);
    expect(l.amenities?.wifi_tier).toBe("free");
  });

  test("American widebody reports paid Wi-Fi", () => {
    const l = leg(jfkLax, "AA", "255");
    expect(l.amenities?.wifi_tier).toBe("paid");
  });

  test("British Airways reports paid Wi-Fi", () => {
    expect(leg(jfkFra, "BA", "178").amenities?.wifi_tier).toBe("paid");
  });

  test("Wi-Fi unknown when the tier slot is absent", () => {
    const l = leg(jfkFra, "BA", "904");
    expect(l.amenities?.wifi).toBeNull();
    expect(l.amenities?.wifi_tier).toBeNull();
  });

  test("Wi-Fi is not read from the power slot", () => {
    const l = leg(jfkFra, "BA", "902");
    expect(l.amenities?.power_type).toBe("usb");
    expect(l.amenities?.wifi).toBe(true);
  });
});

describe("power slots (leg[12][1..6])", () => {
  test("US major reports plug and USB", () => {
    const l = leg(jfkLax, "AA", "300");
    expect(l.amenities?.power).toBe(true);
    expect(l.amenities?.power_type).toBe("plug_and_usb");
    expect(l.amenities?.usb_power).toBe(true);
  });

  test("European short-haul reports USB only", () => {
    const l = leg(jfkFra, "BA", "904");
    expect(l.amenities?.power).toBe(true);
    expect(l.amenities?.power_type).toBe("usb");
    expect(l.amenities?.usb_power).toBe(true);
  });

  test("legacy AC-only cabin reports plug without USB", () => {
    const l = leg(bufAth, "AA", "1195");
    expect(l.amenities?.power_type).toBe("plug");
    expect(l.amenities?.usb_power).toBe(false);
  });

  test("power unknown when no power slot is set", () => {
    const l = leg(jfkFra, "IB", "1327");
    expect(l.amenities?.power).toBeNull();
    expect(l.amenities?.power_type).toBeNull();
    expect(l.amenities?.usb_power).toBeNull();
  });
});

describe("video slots (leg[12][8..10])", () => {
  test("JetBlue reports live TV", () => {
    const l = leg(jfkLax, "B6", "123");
    expect(l.amenities?.video_type).toBe("live_tv");
    expect(l.amenities?.in_seat_video).toBe(true);
    expect(l.amenities?.on_demand_video).toBe(false);
  });

  test("widebody reports on-demand video", () => {
    const l = leg(jfkLax, "AA", "255");
    expect(l.amenities?.video_type).toBe("on_demand");
    expect(l.amenities?.in_seat_video).toBe(true);
    expect(l.amenities?.on_demand_video).toBe(true);
  });

  test("no-seatback fleet reports stream to device", () => {
    const l = leg(jfkLax, "AA", "117");
    expect(l.amenities?.video_type).toBe("stream_to_device");
    expect(l.amenities?.in_seat_video).toBe(false);
    expect(l.amenities?.on_demand_video).toBe(false);
  });

  test("video unknown when no video slot is set", () => {
    const l = leg(jfkFra, "BA", "904");
    expect(l.amenities?.video_type).toBeNull();
    expect(l.amenities?.in_seat_video).toBeNull();
    expect(l.amenities?.on_demand_video).toBeNull();
  });
});

describe("seat quality (leg[13]) and legroom (leg[14])", () => {
  test("above-average economy seat", () => {
    const l = leg(jfkLax, "B6", "123");
    expect(l.amenities?.legroom_rating).toBe(3);
    expect(l.amenities?.seat_quality).toBe("above_average");
    expect(l.amenities?.legroom_inches).toBe(33);
  });

  test("average economy seat", () => {
    const l = leg(jfkLax, "AA", "300");
    expect(l.amenities?.seat_quality).toBe("average");
    expect(l.amenities?.legroom_inches).toBe(31);
  });

  test("below-average economy seat", () => {
    const l = leg(jfkFra, "BA", "904");
    expect(l.amenities?.seat_quality).toBe("below_average");
    expect(l.amenities?.legroom_inches).toBe(29);
  });

  test("lie-flat business seat has no published pitch", () => {
    const l = leg(laxLhrBiz, "EI", "68");
    expect(l.amenities?.legroom_rating).toBe(5);
    expect(l.amenities?.seat_quality).toBe("lie_flat");
    expect(l.amenities?.legroom_inches).toBeNull();
  });

  test("domestic first is a recliner", () => {
    const l = leg(jfkLaxNoDl, "AA", "1154");
    expect(l.amenities?.legroom_rating).toBe(8);
    expect(l.amenities?.seat_quality).toBe("recliner");
  });
});

describe("cabin (leg[16])", () => {
  test("economy leg", () => {
    expect(leg(jfkLax, "B6", "123").cabin).toBe(SeatType.ECONOMY);
  });

  test("business leg", () => {
    expect(leg(laxLhrBiz, "EI", "68").cabin).toBe(SeatType.BUSINESS);
  });

  test("premium economy leg", () => {
    expect(leg(laxLhrBiz, "EI", "172").cabin).toBe(SeatType.PREMIUM_ECONOMY);
  });

  test("first leg", () => {
    expect(leg(jfkLaxNoDl, "AA", "1154").cabin).toBe(SeatType.FIRST);
  });

  test("cabin is per leg, not per itinerary", () => {
    expect(leg(laxLhrBiz, "BA", "833").cabin).toBe(SeatType.ECONOMY);
  });

  test("cabin tracks the fare, not the aircraft", () => {
    // AA 1209 (ORD-LAX, 737 MAX 8) appears as both an economy row and a
    // first row in this fixture.
    const seen = new Set(
      jfkLaxNoDl
        .flatMap((flight) => flight.legs)
        .filter((l) => l.airline === "AA" && l.flight_number === "1209")
        .map((l) => `${l.cabin}:${l.amenities?.seat_quality}`),
    );
    expect(seen).toEqual(new Set([`${SeatType.ECONOMY}:average`, `${SeatType.FIRST}:recliner`]));
  });
});

describe("corpus invariants", () => {
  for (const [label, group] of [
    ["power 1..6", [1, 2, 3, 4, 5, 6]],
    ["video 8..10", [8, 9, 10]],
  ] as [string, number[]][]) {
    test(`${label} slots are mutually exclusive`, () => {
      for (const name of FIXTURES) {
        for (const fl of rawLegs(name)) {
          const slots = fl[12];
          if (!Array.isArray(slots)) continue;
          const on = group.filter((i) => slots[i]);
          expect(on.length).toBeLessThanOrEqual(1);
        }
      }
    });
  }

  test("the Wi-Fi slot is never a bool", () => {
    for (const name of FIXTURES) {
      for (const fl of rawLegs(name)) {
        const slots = fl[12];
        if (!Array.isArray(slots)) continue;
        const tier = slots[11];
        if (tier == null) continue;
        expect(typeof tier).toBe("number");
      }
    }
  });
});

describe("slot flag encoding", () => {
  test("accepts the public page's integer flags as well as booleans", () => {
    // The RPC payload uses JSON booleans; the public travel page encodes
    // the same slots as 1.
    const rows = rawLegs("flight_search_jfk_lax_oneway_usd.bin");
    const fixture = readFileSync(
      new URL(
        "../../../tests/search/fixtures/flight_search_jfk_lax_oneway_usd.bin",
        import.meta.url,
      ),
      "utf8",
    );
    const outer = JSON.parse(fixture.slice(fixture.indexOf("[")));
    const inner = JSON.parse(outer[0][2]);
    const row = structuredClone(inner[2][0][0]) as unknown[];
    const detail = row[0] as unknown[];
    const l = (detail[2] as unknown[][])[0] as unknown[];
    const slots: unknown[] = Array.from({ length: 12 }, () => null);
    slots[1] = 1;
    slots[9] = 1;
    slots[11] = 2;
    l[12] = slots;
    l[13] = 3;
    expect(rows.length).toBeGreaterThan(0);
    const parsed = parseFlightRow(row);
    expect(parsed.legs[0]?.amenities?.power_type).toBe("plug_and_usb");
    expect(parsed.legs[0]?.amenities?.video_type).toBe("on_demand");
    expect(parsed.legs[0]?.amenities?.wifi_tier).toBe("free");
  });
});
