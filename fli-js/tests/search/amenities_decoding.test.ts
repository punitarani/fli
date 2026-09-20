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

function rawRows(name: string): unknown[][] {
  const fixture = readFileSync(
    new URL(`../../../tests/search/fixtures/${name}`, import.meta.url),
    "utf8",
  );
  const outer = JSON.parse(fixture.slice(fixture.indexOf("[")));
  const inner = JSON.parse(outer[0][2]);
  return [2, 3].flatMap((i) => (Array.isArray(inner[i]) ? inner[i][0] : []));
}

/**
 * Parse a real fixture row with leg[12]/[13]/[14] overridden. Cloning a
 * genuine row keeps every other position realistic. Mirrors
 * `_synthetic_leg` in tests/search/test_amenities_decoding.py.
 */
function syntheticLeg(
  slots: unknown = null,
  seatQuality: unknown = 1,
  legroom: unknown = "31 in",
): FlightLeg {
  const row = structuredClone(rawRows("flight_search_jfk_lax_oneway_usd.bin")[0]) as unknown[];
  const l = ((row[0] as unknown[])[2] as unknown[][])[0] as unknown[];
  l[12] = slots;
  l[13] = seatQuality;
  l[14] = legroom;
  l[30] = null; // isolate leg[14] from the long-form fallback
  return parseFlightRow(row).legs[0] as FlightLeg;
}

function emptySlots(): unknown[] {
  return Array.from({ length: 12 }, () => null);
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

  test("legacy AC-only cabin reports plug but does not deny USB", () => {
    // Slot 3 occurs 7 times across 2 carriers in the whole corpus — too
    // thin to put a `false` on a public tri-state boolean.
    const l = leg(bufAth, "AA", "1195");
    expect(l.amenities?.power).toBe(true);
    expect(l.amenities?.power_type).toBe("plug");
    expect(l.amenities?.usb_power).toBeNull();
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
    // A live-TV seatback usually carries on-demand content too, so the
    // absence of slot 9 is not evidence that on-demand is missing.
    expect(l.amenities?.on_demand_video).toBeNull();
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
    // The one negative these slots license: "stream to your own device"
    // is Google's way of saying there is no seatback screen.
    expect(l.amenities?.in_seat_video).toBe(false);
    // Streamed content is itself on-demand, so this stays unknown.
    expect(l.amenities?.on_demand_video).toBeNull();
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

describe("unobserved slots", () => {
  for (const slot of [2, 4, 6]) {
    test(`"some seats" power slot ${slot} does not assert power`, () => {
      // Slots 2/4/6 occur zero times in 481 legs; nothing is inferred.
      const slots = emptySlots();
      slots[slot] = true;
      const a = syntheticLeg(slots).amenities;
      expect(a?.power).toBeNull();
      expect(a?.power_type).toBeNull();
      expect(a?.usb_power).toBeNull();
    });
  }

  test("unknown Wi-Fi tier code still reports Wi-Fi", () => {
    const slots = emptySlots();
    slots[11] = 1;
    const a = syntheticLeg(slots).amenities;
    expect(a?.wifi).toBe(true);
    expect(a?.wifi_tier).toBeNull();
  });

  test("unknown seat-quality code keeps the raw rating", () => {
    const a = syntheticLeg(emptySlots(), 9).amenities;
    expect(a?.legroom_rating).toBe(9);
    expect(a?.seat_quality).toBeNull();
  });

  test("first set power slot wins even when unlabelled", () => {
    // Impossible per the corpus, but Python and TypeScript must agree:
    // both scan 1..6 in wire order and refuse to skip past a set slot
    // they cannot name.
    const slots = emptySlots();
    slots[2] = true;
    slots[3] = true;
    const a = syntheticLeg(slots).amenities;
    expect(a?.power).toBeNull();
    expect(a?.power_type).toBeNull();
    expect(a?.usb_power).toBeNull();
  });
});

describe("slot value types", () => {
  for (const flag of [true, 1]) {
    test(`${JSON.stringify(flag)} counts as a set slot`, () => {
      const slots = emptySlots();
      slots[1] = flag;
      expect(syntheticLeg(slots).amenities?.power_type).toBe("plug_and_usb");
    });
  }

  for (const value of [false, 0, -1, 1.5, "1", null]) {
    test(`${JSON.stringify(value)} does not set a slot`, () => {
      const slots = emptySlots();
      slots[1] = value;
      expect(syntheticLeg(slots).amenities?.power).toBeNull();
    });
  }

  // 2.0 is deliberately absent: JavaScript has no float/int distinction for
  // whole numbers (JSON.parse("2.0") === 2), so it cannot be rejected here
  // the way Python's isinstance(v, int) rejects the float 2.0. Every
  // genuinely non-integral value behaves identically in both ports.
  for (const value of [2.5, "2", true]) {
    test(`Wi-Fi code ${JSON.stringify(value)} is ignored`, () => {
      const slots = emptySlots();
      slots[11] = value;
      const a = syntheticLeg(slots).amenities;
      expect(a?.wifi).toBeNull();
      expect(a?.wifi_tier).toBeNull();
    });
  }
});

describe("legroom inches parsing", () => {
  const cases: [string, number | null][] = [
    ["31 in", 31],
    ["31 inches", 31],
    ["7 in", 7],
    // Non-ASCII digits are not seat pitches. Python's str.isdigit() is
    // True for these, so the shared guard must be ASCII-only.
    ["² in", null],
    ["١٢ in", null],
    ["", null],
    ["lie flat", null],
    ["0 in", null],
    ["-3 in", null],
  ];
  for (const [text, expected] of cases) {
    test(`parses ${JSON.stringify(text)} as ${expected}`, () => {
      expect(syntheticLeg(emptySlots(), 1, text).amenities?.legroom_inches).toBe(expected);
    });
  }

  test("unparseable legroom does not drop the row", () => {
    const row = structuredClone(rawRows("flight_search_jfk_lax_oneway_usd.bin")[0]) as unknown[];
    (((row[0] as unknown[])[2] as unknown[][])[0] as unknown[])[14] = "² in";
    const flight = parseFlightRow(row);
    expect(flight.legs.length).toBeGreaterThan(0);
    expect(flight.legs[0]?.amenities?.legroom_inches).toBeNull();
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
