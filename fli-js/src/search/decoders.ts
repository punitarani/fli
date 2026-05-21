/**
 * Pure response decoders for Google Flights' RPC payloads.
 * 1:1 port of fli/search/_decoders.py.
 */

import { extractCurrencyFromPriceToken } from "../core/currency.ts";
import { AIRLINE_NAMES, type Airline } from "../models/airline.ts";
import { AIRPORT_NAMES, type Airport } from "../models/airport.ts";
import type {
  Amenities,
  BookingOption,
  FlightLeg,
  FlightResult,
  Layover,
} from "../models/google-flights/base.ts";
import { asBool, asInt, asNonNegativeInt, asStr, safeGet } from "./helpers.ts";

// Pseudo-codes Google emits in place of a real IATA carrier identifier.
const AIRLINE_SENTINELS = new Set(["multi"]);

// Pre-compute the bare-IATA-code → enum-key lookup table. Digit-prefixed
// IATA codes (e.g. "2B") are stored in the enum under a "_2B" key because
// "2B" is not a valid JavaScript identifier; we strip the leading "_" so
// callers can look up by the wire-format code Google emits.
const AIRLINE_BY_CODE: Record<string, Airline> = {};
for (const key of Object.keys(AIRLINE_NAMES)) {
  const code = key.startsWith("_") ? key.slice(1) : key;
  AIRLINE_BY_CODE[code] = key as Airline;
}

const AIRPORT_BY_CODE: Record<string, Airport> = {};
for (const key of Object.keys(AIRPORT_NAMES)) {
  AIRPORT_BY_CODE[key] = key as Airport;
}

function parseDateTime(dateArr: unknown, timeArr: unknown): Date {
  if (!Array.isArray(dateArr) || !Array.isArray(timeArr)) {
    throw new Error("Date and time arrays must contain at least one non-null value");
  }
  if (!dateArr.some((x) => x != null) || !timeArr.some((x) => x != null)) {
    throw new Error("Date and time arrays must contain at least one non-null value");
  }
  const y = dateArr[0] as number | null;
  const m = dateArr[1] as number | null;
  const d = dateArr[2] as number | null;
  // Python's `datetime(y, m, d, ...)` rejects month=0 / day=0, so a partial
  // like `[2026, null, null]` raises there. JS `new Date(2026, -1, 0, ...)`
  // silently returns a valid-but-wrong Date (Nov 30 2025), so we enforce
  // the same strictness up front. Time components default to 0 to match
  // Python's `or 0` for the time tuple.
  if (y == null || m == null || d == null || m < 1 || m > 12 || d < 1 || d > 31) {
    throw new Error(`Invalid date components: y=${y}, m=${m}, d=${d}`);
  }
  const h = (timeArr[0] as number | null) ?? 0;
  const min = (timeArr[1] as number | null) ?? 0;
  // Use local-time constructor (mirrors Python's naive datetime).
  return new Date(y, m - 1, d, h, min);
}

function parseAirport(code: unknown): Airport {
  if (typeof code !== "string" || !(code in AIRPORT_BY_CODE)) {
    throw new Error(`Unknown airport code: ${String(code)}`);
  }
  return AIRPORT_BY_CODE[code] as Airport;
}

function safeAirline(code: unknown): Airline | null {
  if (typeof code !== "string" || code.length === 0) return null;
  if (AIRLINE_SENTINELS.has(code)) return null;
  if (code in AIRLINE_BY_CODE) return AIRLINE_BY_CODE[code] as Airline;
  return null;
}

function parseAmenities(slots: unknown): Amenities | null {
  if (!Array.isArray(slots) || slots.length === 0) return null;
  const wifi = asBool(safeGet(slots, 1));
  const power = asBool(safeGet(slots, 5));
  const onDemandVideo = asBool(safeGet(slots, 9));
  const legroomRating = asNonNegativeInt(safeGet(slots, 11));
  if (wifi == null && power == null && onDemandVideo == null && legroomRating == null) {
    return null;
  }
  return {
    wifi: wifi ?? null,
    power: power ?? null,
    usb_power: null,
    in_seat_video: null,
    on_demand_video: onDemandVideo ?? null,
    legroom_rating: legroomRating ?? null,
  };
}

interface EmissionsBlock {
  this_g: number | null;
  typical_g: number | null;
  delta_pct: number | null;
  tag: string | null;
}

function parseEmissions(detail: unknown): EmissionsBlock {
  const out: EmissionsBlock = { this_g: null, typical_g: null, delta_pct: null, tag: null };
  const block = safeGet(detail, 22);
  if (!Array.isArray(block)) return out;
  out.this_g = asNonNegativeInt(safeGet(block, 7));
  out.typical_g = asNonNegativeInt(safeGet(block, 8));
  out.delta_pct = asInt(safeGet(block, 3));
  const tagInt = asInt(safeGet(block, 11));
  if (tagInt === 1) out.tag = "lower";
  else if (tagInt === 2) out.tag = "typical";
  else if (tagInt === 3) out.tag = "higher";
  return out;
}

function parseLeg(fl: unknown[]): FlightLeg {
  const airlineInfo = (fl[22] as unknown[]) ?? [];
  const airline = safeAirline(safeGet(airlineInfo, 0));
  if (airline == null) {
    throw new Error("Leg missing airline code");
  }
  const flightNumber = asStr(safeGet(airlineInfo, 1)) ?? "";
  const opCode = safeGet(airlineInfo, 2);
  const operatingAirline = opCode ? safeAirline(opCode) : null;

  const amenities = parseAmenities(safeGet(fl, 12));
  const aircraft = asStr(safeGet(fl, 17));
  const legroomShort = asStr(safeGet(fl, 14));
  const legroomLong = asStr(safeGet(fl, 30));
  const overnight = asBool(safeGet(fl, 19)) ?? false;
  const co2EmissionsG = asNonNegativeInt(safeGet(fl, 31));

  return {
    airline,
    flight_number: flightNumber,
    departure_airport: parseAirport(fl[3]),
    arrival_airport: parseAirport(fl[6]),
    departure_datetime: parseDateTime(fl[20], fl[8]),
    arrival_datetime: parseDateTime(fl[21], fl[10]),
    duration: fl[11] as number,
    departure_airport_name: asStr(safeGet(fl, 4)),
    arrival_airport_name: asStr(safeGet(fl, 5)),
    operating_airline: operatingAirline,
    operating_flight_number: null,
    aircraft,
    legroom_short: legroomShort,
    legroom: legroomLong ?? legroomShort,
    amenities,
    overnight,
    co2_emissions_g: co2EmissionsG,
  };
}

function deriveLayovers(legs: FlightLeg[], detailBlock: unknown): Layover[] {
  const detailEntries = Array.isArray(detailBlock) ? detailBlock : [];
  const layovers: Layover[] = [];
  for (let i = 0; i < legs.length - 1; i++) {
    const prev = legs[i] as FlightLeg;
    const next = legs[i + 1] as FlightLeg;
    const waitMs = next.departure_datetime.getTime() - prev.arrival_datetime.getTime();
    const deltaMinutes = Math.max(Math.floor(waitMs / 60000), 0);

    let airportName: string | null = null;
    let city: string | null = null;
    const entry = detailEntries[i];
    if (Array.isArray(entry)) {
      airportName = asStr(safeGet(entry, 4));
      city = asStr(safeGet(entry, 5));
    }

    layovers.push({
      airport: prev.arrival_airport,
      duration: deltaMinutes,
      overnight: prev.arrival_datetime.toDateString() !== next.departure_datetime.toDateString(),
      change_of_airport: prev.arrival_airport !== next.departure_airport,
      airport_name: airportName,
      city,
    });
  }
  return layovers;
}

function getPriceBlock(row: unknown): unknown[] | null {
  const block = safeGet(row, 1);
  return Array.isArray(block) ? block : null;
}

function parsePriceInfo(row: unknown[]): [number | null, string | null] {
  const priceBlock = getPriceBlock(row);
  if (priceBlock == null) throw new Error("price block missing — skip row");

  const head = priceBlock[0];
  if (!Array.isArray(head)) throw new Error("price head is not a list");

  let price: number | null = null;
  if (head.length > 0) {
    const rawPrice = head[head.length - 1];
    if (typeof rawPrice === "boolean" || (typeof rawPrice !== "number" && rawPrice != null)) {
      throw new Error(`price field is not numeric: ${JSON.stringify(rawPrice)}`);
    }
    price = rawPrice == null ? null : Number(rawPrice);
  }

  let currency: string | null = null;
  if (priceBlock.length > 1) {
    try {
      currency = extractCurrencyFromPriceToken(priceBlock[1] as string);
    } catch {
      currency = null;
    }
  }
  return [price, currency];
}

/** Decode a single flight row into a `FlightResult`. */
export function parseFlightRow(row: unknown[]): FlightResult {
  const detail = row[0] as unknown[];
  const [price, currency] = parsePriceInfo(row);
  const rawLegs = (detail[2] as unknown[][]) ?? [];
  const legs = rawLegs.map(parseLeg);
  const layovers = legs.length > 1 ? deriveLayovers(legs, safeGet(detail, 13)) : [];
  const emissions = parseEmissions(detail);
  const primaryAirline = safeAirline(safeGet(detail, 0));
  const namesField = safeGet(detail, 1);
  let primaryAirlineName: string | null = null;
  if (Array.isArray(namesField) && namesField.length > 0) {
    const first = namesField[0];
    if (typeof first === "string") primaryAirlineName = first;
  }

  return {
    legs,
    price,
    currency,
    duration: detail[9] as number,
    stops: Math.max(legs.length - 1, 0),
    layovers: layovers.length > 0 ? layovers : null,
    co2_emissions_g: emissions.this_g,
    co2_emissions_typical_g: emissions.typical_g,
    co2_emissions_delta_pct: emissions.delta_pct,
    emissions_tag: emissions.tag,
    self_transfer: asBool(safeGet(detail, 12)),
    mixed_cabin: asBool(safeGet(row, 10)),
    primary_airline: primaryAirline,
    primary_airline_name: primaryAirlineName,
    booking_token: asStr(safeGet(row, 8)),
  };
}

// ---------------------------------------------------------------------------
// Booking option decoding
// ---------------------------------------------------------------------------

/** Walk a decoded `wrb.fr` chunk and yield every booking-option row. */
export function parseBookingChunk(chunk: unknown): BookingOption[] {
  const out: BookingOption[] = [];
  walkForBookingRows(chunk, out);
  return out;
}

function walkForBookingRows(node: unknown, out: BookingOption[]): void {
  if (!Array.isArray(node)) return;
  const opt = tryParseBookingRow(node);
  if (opt != null) {
    out.push(opt);
    return;
  }
  for (const child of node) walkForBookingRows(child, out);
}

function tryParseBookingRow(row: unknown[]): BookingOption | null {
  if (!Array.isArray(row) || row.length < 8) return null;
  if (typeof row[0] !== "number" || !Number.isInteger(row[0])) return null;

  const vendorBlock = row[1];
  if (!Array.isArray(vendorBlock) || vendorBlock.length === 0) return null;
  const firstVendor = vendorBlock[0];
  if (
    !Array.isArray(firstVendor) ||
    firstVendor.length < 2 ||
    typeof firstVendor[0] !== "string" ||
    typeof firstVendor[1] !== "string"
  ) {
    return null;
  }
  const isDirect =
    firstVendor.length >= 4 && typeof firstVendor[3] === "boolean" ? firstVendor[3] : false;

  let flights: Array<[string, string]> | null = null;
  if (Array.isArray(row[3])) {
    const gathered: Array<[string, string]> = [];
    for (const entry of row[3] as unknown[]) {
      if (
        Array.isArray(entry) &&
        entry.length >= 2 &&
        typeof entry[0] === "string" &&
        typeof entry[1] === "string"
      ) {
        gathered.push([entry[0], entry[1]]);
      }
    }
    flights = gathered.length > 0 ? gathered : null;
  }

  const [bookingUrl, googleClickUrl] = extractBookingUrls(row[5]);

  let price: number | null = null;
  let currency: string | null = null;
  if (Array.isArray(row[7])) {
    const pblock = row[7] as unknown[];
    if (pblock.length > 0 && Array.isArray(pblock[0]) && (pblock[0] as unknown[]).length >= 2) {
      const inner = pblock[0] as unknown[];
      const rawPrice = inner[inner.length - 1];
      if (typeof rawPrice === "number" && !Number.isNaN(rawPrice)) {
        price = rawPrice;
      }
    }
    if (pblock.length > 1 && typeof pblock[1] === "string") {
      currency = extractCurrencyFromPriceToken(pblock[1]);
    }
  }

  return {
    vendor_code: firstVendor[0],
    vendor_name: firstVendor[1],
    is_airline_direct: isDirect,
    price,
    currency,
    fare_name: extractFareName(row),
    booking_url: bookingUrl,
    google_click_url: googleClickUrl,
    flights,
  };
}

function extractBookingUrls(block: unknown): [string | null, string | null] {
  if (!Array.isArray(block)) return [null, null];
  const vendorUrl = block.length > 0 && typeof block[0] === "string" ? block[0] : null;
  let googleClickUrl: string | null = null;
  if (block.length > 2 && Array.isArray(block[2]) && (block[2] as unknown[]).length > 0) {
    const candidate = (block[2] as unknown[])[0];
    if (typeof candidate === "string" && candidate.includes("/travel/clk")) {
      googleClickUrl = candidate;
    }
  }
  return [vendorUrl, googleClickUrl];
}

function extractFareName(row: unknown[]): string | null {
  if (row.length > 21 && Array.isArray(row[21]) && (row[21] as unknown[]).length > 3) {
    const candidate = (row[21] as unknown[])[3];
    if (typeof candidate === "string" && candidate.length > 0) return candidate;
  }
  if (row.length > 14 && Array.isArray(row[14]) && (row[14] as unknown[]).length > 0) {
    try {
      const label = ((((row[14] as unknown[])[0] as unknown[])[0] as unknown[])[1] as unknown[])[1];
      if (typeof label === "string" && label.length > 0) return label;
    } catch {
      // Shape mismatch — fall through.
    }
  }
  return null;
}

// Re-export the internal helpers so tests can exercise them.
export { tryParseBookingRow as _tryParseBookingRow, safeAirline as _safeAirline };
export { parseDateTime as _parseDateTime, parseEmissions as _parseEmissions };
