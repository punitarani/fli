/**
 * Minimal protobuf encoder for the GetBookingResults token.
 *
 * 1:1 port of fli/search/_proto.py — preserves the byte-perfect
 * reproduction of a captured live booking token.
 */

import { Buffer } from "node:buffer";
import type { PassengerInfo } from "../models/google-flights/base.ts";

function concatBytes(...parts: Uint8Array[]): Uint8Array {
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

function varint(value: number): Uint8Array {
  if (value < 0) throw new Error("varint encoder takes non-negative ints only");
  const bytes: number[] = [];
  let v = value;
  while (true) {
    const byte = v & 0x7f;
    v >>>= 7;
    if (v > 0) {
      bytes.push(byte | 0x80);
    } else {
      bytes.push(byte);
      break;
    }
  }
  return new Uint8Array(bytes);
}

function tag(field: number, wire: number): Uint8Array {
  return varint((field << 3) | wire);
}

function lengthDelim(field: number, payload: Uint8Array): Uint8Array {
  return concatBytes(tag(field, 2), varint(payload.length), payload);
}

function varintField(field: number, value: number): Uint8Array {
  return concatBytes(tag(field, 0), varint(value));
}

function base64Encode(bytes: Uint8Array): string {
  if (typeof Buffer !== "undefined") {
    return Buffer.from(bytes).toString("base64");
  }
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i] as number);
  return btoa(binary);
}

function base64UrlsafeDecode(token: string): Uint8Array {
  const padLen = (4 - (token.length % 4)) % 4;
  const padded = token + "=".repeat(padLen);
  const standard = padded.replace(/-/g, "+").replace(/_/g, "/");
  if (typeof Buffer !== "undefined") {
    return new Uint8Array(Buffer.from(standard, "base64"));
  }
  const bin = atob(standard);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

const utf8 = new TextEncoder();
const utf8Decoder = new TextDecoder("utf-8", { fatal: false });

/**
 * Construct the GetBookingResults outer[0][1] token.
 *
 * @returns base64-encoded protobuf token.
 * @throws Error when any string argument is empty or price_cents is negative.
 */
export function buildBookingToken(args: {
  sessionId: string;
  airlineCode: string;
  flightNumber: string;
  legIndex: number;
  priceCents: number;
  currency?: string;
}): string {
  const { sessionId, airlineCode, flightNumber, legIndex, priceCents } = args;
  const currency = args.currency ?? "USD";

  if (priceCents < 0) throw new Error("price_cents must be non-negative");
  if (!sessionId) throw new Error("session_id must be non-empty");
  if (!airlineCode) throw new Error("airline_code must be non-empty");
  if (!flightNumber) throw new Error("flight_number must be non-empty");
  if (!currency) throw new Error("currency must be non-empty");

  const nested = concatBytes(
    varintField(1, priceCents),
    varintField(2, 2),
    lengthDelim(3, utf8.encode(currency)),
  );

  const payload = concatBytes(
    lengthDelim(1, utf8.encode(sessionId)),
    lengthDelim(2, utf8.encode(`${airlineCode}${flightNumber}#${legIndex}`)),
    lengthDelim(3, nested),
    varintField(7, 28),
    varintField(14, priceCents),
  );

  return base64Encode(payload);
}

/** Varint reader; returns `[value, newOffset]`.
 *
 * Uses `+= chunk * 2**shift` instead of `|= chunk << shift` because
 * JavaScript's bitwise operators coerce to signed 32-bit integers, so
 * `<<` past bit 30 corrupts the result. Numbers stay accurate up to
 * `Number.MAX_SAFE_INTEGER` (2^53 − 1), which is plenty for prices and
 * field tags but stops short of the full protobuf 64-bit varint range.
 */
export function _readVarint(buf: Uint8Array, off: number): [number, number] {
  let value = 0;
  let shift = 0;
  let offset = off;
  while (true) {
    const byte = buf[offset];
    if (byte === undefined) throw new RangeError(`Truncated varint at offset ${offset}`);
    offset++;
    value += (byte & 0x7f) * 2 ** shift;
    if ((byte & 0x80) === 0) {
      if (!Number.isSafeInteger(value)) {
        throw new Error("Varint exceeds Number.MAX_SAFE_INTEGER");
      }
      return [value, offset];
    }
    shift += 7;
    if (shift >= 64) throw new Error("Varint is too large to decode");
  }
}

type DecodedNested = Record<string, string | number>;
type DecodedToken = Record<string, string | number | DecodedNested>;

/** Decode a booking token (round-trip helper used by tests). */
export function decodeBookingToken(token: string): DecodedToken {
  const raw = base64UrlsafeDecode(token);
  const result: DecodedToken = {};
  let offset = 0;
  while (offset < raw.length) {
    const [tagVal, afterTag] = _readVarint(raw, offset);
    offset = afterTag;
    const field = tagVal >> 3;
    const wire = tagVal & 0x07;
    if (wire === 0) {
      const [val, afterVal] = _readVarint(raw, offset);
      offset = afterVal;
      result[`field_${field}`] = val;
    } else if (wire === 2) {
      const [length, afterLen] = _readVarint(raw, offset);
      offset = afterLen;
      const data = raw.subarray(offset, offset + length);
      offset += length;
      // Try printable ASCII string.
      let ascii = "";
      let printable = true;
      for (let i = 0; i < data.length; i++) {
        const c = data[i] as number;
        if (c < 0x20 || c > 0x7e) {
          printable = false;
          break;
        }
        ascii += String.fromCharCode(c);
      }
      if (printable && data.length > 0) {
        result[`field_${field}`] = ascii;
        continue;
      }
      // Otherwise try nested message.
      try {
        const nested: DecodedNested = {};
        let noff = 0;
        let bailedOut = false;
        while (noff < data.length) {
          const [ntag, afterNtag] = _readVarint(data, noff);
          noff = afterNtag;
          const nfield = ntag >> 3;
          const nwire = ntag & 0x07;
          if (nwire === 0) {
            const [v, afterV] = _readVarint(data, noff);
            noff = afterV;
            nested[`field_${nfield}`] = v;
          } else if (nwire === 2) {
            const [nl, afterNl] = _readVarint(data, noff);
            noff = afterNl;
            const slice = data.subarray(noff, noff + nl);
            nested[`field_${nfield}`] = utf8Decoder.decode(slice);
            noff += nl;
          } else {
            bailedOut = true;
            break;
          }
        }
        if (bailedOut) throw new Error("nested parse bailed");
        result[`field_${field}`] = nested;
      } catch {
        // Not a nested message — store as hex.
        let hex = "";
        for (let i = 0; i < data.length; i++) {
          hex += (data[i] as number).toString(16).padStart(2, "0");
        }
        result[`field_${field}`] = hex;
      }
    } else {
      throw new Error(`unsupported wire type ${wire} at offset ${offset}`);
    }
  }
  return result;
}

/** Extract the booking token from a `tfu` URL parameter (or full URL). */
export function extractBookingTokenFromTfu(tfu: string): string {
  let value = tfu;
  if (value.includes("tfu=")) {
    let parsed: URL;
    try {
      parsed = new URL(value);
    } catch (e) {
      throw new Error(`tfu input is not a parseable URL: ${(e as Error).message}`);
    }
    const fromUrl = parsed.searchParams.get("tfu");
    if (!fromUrl) throw new Error("URL has no `tfu` query parameter");
    value = fromUrl;
  }

  let raw: Uint8Array;
  try {
    raw = base64UrlsafeDecode(value);
  } catch (e) {
    throw new Error(`tfu is not valid base64: ${(e as Error).message}`);
  }

  let off = 0;
  while (off < raw.length) {
    const [tagVal, afterTag] = _readVarint(raw, off);
    off = afterTag;
    const field = tagVal >> 3;
    const wire = tagVal & 0x07;
    if (wire === 0) {
      const [, afterVal] = _readVarint(raw, off);
      off = afterVal;
    } else if (wire === 2) {
      const [length, afterLen] = _readVarint(raw, off);
      off = afterLen;
      const data = raw.subarray(off, off + length);
      off += length;
      if (field === 1) {
        // Decode as ASCII (the inner field is itself base64 text).
        let ascii = "";
        for (let i = 0; i < data.length; i++) {
          const c = data[i] as number;
          if (c > 0x7e) throw new Error("tfu field 1 is not ASCII");
          ascii += String.fromCharCode(c);
        }
        // Re-normalise to the standard base64 alphabet so the downstream parser accepts it.
        return ascii.trim().replace(/=+$/, "");
      }
    } else if (wire === 5) {
      off += 4;
    } else if (wire === 1) {
      off += 8;
    } else {
      throw new Error(`unsupported wire type ${wire} at offset ${off}`);
    }
  }
  throw new Error("tfu protobuf has no field 1 (booking token)");
}

/** Extract the booking session id from a `tfu` parameter. */
export function extractSessionIdFromTfu(tfu: string): string {
  const inner = extractBookingTokenFromTfu(tfu);
  const decoded = decodeBookingToken(inner);
  const session = decoded.field_1;
  if (typeof session !== "string") {
    throw new Error("inner booking token has no field 1 (session id)");
  }
  return session;
}

// ---------------------------------------------------------------------------
// Deep-link URL parameter builder (tfs)
// ---------------------------------------------------------------------------

/**
 * Encode a non-negative BigInt as a protobuf varint.
 *
 * The `number`-based {@link varint} cannot represent values above
 * `Number.MAX_SAFE_INTEGER`; the `tfs` token's f16 field is max-uint64, so it
 * needs a BigInt encoder.
 */
function varintBig(value: bigint): Uint8Array {
  if (value < 0n) throw new Error("varint encoder takes non-negative ints only");
  const bytes: number[] = [];
  let v = value;
  while (true) {
    const byte = Number(v & 0x7fn);
    v >>= 7n;
    if (v > 0n) {
      bytes.push(byte | 0x80);
    } else {
      bytes.push(byte);
      break;
    }
  }
  return new Uint8Array(bytes);
}

/**
 * Encode bytes as URL-safe base64 without `=` padding.
 *
 * The `tfs` query parameter uses the urlsafe alphabet (`-`/`_`) with padding
 * stripped.
 */
function toUrlsafeB64(bytes: Uint8Array): string {
  if (typeof Buffer !== "undefined") {
    return Buffer.from(bytes).toString("base64url");
  }
  return base64Encode(bytes).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** One physical leg within a booking-URL segment. */
export interface LegSpec {
  /** IATA code of the departure airport (e.g. `"SFO"`). */
  origin: string;
  /** Departure date in `YYYY-MM-DD` format. */
  depDate: string;
  /** IATA code of the arrival airport (e.g. `"PHX"`). */
  dest: string;
  /** Airline IATA code (e.g. `"AA"`). */
  airline: string;
  /** Flight number string (e.g. `"2413"`). */
  flightNumber: string;
}

export interface BuildTfsTokenOptions {
  /** `true` for one-way (incl. multi-city); `false` for round-trip. */
  isOneWay?: boolean;
  /**
   * Passenger kind codes, one entry per traveller (field 8). Build these
   * from a search's `PassengerInfo` with {@link passengerCodes}. Defaults
   * to a single adult so existing callers keep producing the captured
   * tokens.
   */
  passengers?: readonly number[];
  /**
   * Cabin class encoded in field 9.
   * `1` = economy, `2` = premium economy, `3` = business, `4` = first.
   * Defaults to economy so existing callers keep producing the captured tokens.
   */
  seat?: number;
}

// `tfs` is the itinerary parameter shared by booking deep links and the
// public search page. Both builders below write the same message, so the
// field layout lives here once:
//
//   1  = 28 (constant)          8  = passenger kind, repeated
//   2  = 2 (constant)           9  = cabin class
//   3  = segment, repeated      14 = 1 (constant)
//   3.2  = departure date       16 = max-uint64 pin (deep links only)
//   3.4  = selected leg, rep.   19 = 2 one-way / multi-city, 1 round-trip
//   3.5  = stop ceiling
//   3.6  = carrier include, repeated (IATA code or alliance name)
//   3.7  = carrier exclude, repeated (same values as 3.6)
//   3.13 = origin  3.14 = destination
//   3.15 = layover airport include, repeated
//   3.17 = min layover minutes  3.18 = max layover minutes
//
// Reverse-engineered from live browser captures; 1:1 with the Python
// `fli/search/_proto.py`.

const MAX_U64 = (1n << 64n) - 1n;

/**
 * Passenger kinds, in the order Google's repeated field 8 numbers them:
 * 1 = adult, 2 = child, 3 = infant on lap, 4 = infant in own seat.
 *
 * The two infant codes are easy to transpose and the mistake is expensive
 * rather than loud: on an international route a lap infant prices at ~10%
 * of the adult fare and an infant in its own seat at ~100%, so a swap
 * quotes a plausible but wrong fare instead of erroring. The legacy RPC
 * struct orders the same four counts
 * `[adults, children, infants_on_lap, infants_in_seat]`.
 */
const PASSENGER_FIELDS: ReadonlyArray<readonly [keyof PassengerInfo, number]> = [
  ["adults", 1],
  ["children", 2],
  ["infants_on_lap", 3],
  ["infants_in_seat", 4],
];

/**
 * Convert a `PassengerInfo` into `tfs` field-8 codes, one per traveller.
 *
 * Shared by {@link buildTfs} in `tfs.ts` (the search token) and
 * {@link buildTfsToken} (the per-flight booking token) so the two cannot
 * drift on how they encode the passenger mix.
 *
 * @param passengerInfo A `PassengerInfo`, or any duck-typed object exposing
 *   some subset of `adults`/`children`/`infants_on_lap`/`infants_in_seat`
 *   (missing ones count as zero). `null`/`undefined` is treated as an
 *   all-zero mix.
 * @returns One code per traveller, in field order. Falls back to `[1]` (a
 *   single adult) when the mix would otherwise be empty.
 */
export function passengerCodes(passengerInfo: Partial<PassengerInfo> | null | undefined): number[] {
  const codes: number[] = [];
  for (const [field, code] of PASSENGER_FIELDS) {
    const count = (passengerInfo as Partial<PassengerInfo> | null)?.[field] ?? 0;
    for (let i = 0; i < count; i++) codes.push(code);
  }
  return codes.length > 0 ? codes : [1];
}

/** Optional per-segment restrictions Google reads out of the `tfs` segment. */
export interface EncodeTfsSegmentOptions {
  /**
   * Physical flights pinned for this direction, if any. Supplying them
   * narrows a search to itineraries that include them — that is how a
   * round-trip search asks for return options against a chosen outbound.
   */
  legs?: readonly LegSpec[];
  /**
   * Stop ceiling, zero-based (`0` = non-stop, `1` = one stop or fewer).
   * `null`/`undefined` leaves the search unconstrained; passing `0` for
   * "any" would pin it to non-stop instead.
   */
  maxStops?: number | null;
  /**
   * Only itineraries on these carriers. Google takes airline IATA codes
   * and alliance names (`"STAR_ALLIANCE"`) in the same list.
   */
  carriers?: readonly string[];
  /** The same values, as an exclude list. */
  carriersExclude?: readonly string[];
  /** Only these airports may be used as layover stops. */
  layoverAirports?: readonly string[];
  /** Minimum layover wait, in minutes. */
  minLayover?: number | null;
  /** Maximum layover wait, in minutes. */
  maxLayover?: number | null;
}

/**
 * Encode one travel direction of a `tfs` itinerary.
 *
 * @param origin IATA code (or codes) the direction departs from.
 * @param dest IATA code (or codes) the direction arrives at.
 * @param date Departure date in `YYYY-MM-DD` format.
 * @returns The length-delimited field 3 bytes for this segment.
 */
export function encodeTfsSegment(
  origin: string | readonly string[],
  dest: string | readonly string[],
  date: string,
  options: EncodeTfsSegmentOptions = {},
): Uint8Array {
  const {
    legs = [],
    maxStops = null,
    carriers = [],
    carriersExclude = [],
    layoverAirports = [],
    minLayover = null,
    maxLayover = null,
  } = options;

  let body = lengthDelim(2, utf8.encode(date));
  if (maxStops != null) body = concatBytes(body, varintField(5, maxStops));
  for (const code of carriers) body = concatBytes(body, lengthDelim(6, utf8.encode(code)));
  for (const code of carriersExclude) body = concatBytes(body, lengthDelim(7, utf8.encode(code)));
  for (const leg of legs) {
    body = concatBytes(
      body,
      lengthDelim(
        4,
        concatBytes(
          lengthDelim(1, utf8.encode(leg.origin)),
          lengthDelim(2, utf8.encode(leg.depDate)),
          lengthDelim(3, utf8.encode(leg.dest)),
          lengthDelim(5, utf8.encode(leg.airline)),
          lengthDelim(6, utf8.encode(leg.flightNumber)),
        ),
      ),
    );
  }
  for (const code of typeof origin === "string" ? [origin] : origin) {
    body = concatBytes(
      body,
      lengthDelim(13, concatBytes(varintField(1, 1), lengthDelim(2, utf8.encode(code)))),
    );
  }
  for (const code of typeof dest === "string" ? [dest] : dest) {
    body = concatBytes(
      body,
      lengthDelim(14, concatBytes(varintField(1, 1), lengthDelim(2, utf8.encode(code)))),
    );
  }
  for (const code of layoverAirports) body = concatBytes(body, lengthDelim(15, utf8.encode(code)));
  if (minLayover != null) body = concatBytes(body, varintField(17, minLayover));
  if (maxLayover != null) body = concatBytes(body, varintField(18, maxLayover));
  return lengthDelim(3, body);
}

/** Envelope options for {@link encodeTfsPayload}. */
export interface EncodeTfsPayloadOptions {
  /**
   * `true` for one-way, `false` for round-trip. Controls field 19.
   * Multi-city is a third value (3) that the search page cannot serve.
   */
  isOneWay: boolean;
  /**
   * Passenger kind codes, one entry per traveller (1 = adult, 2 = child,
   * 3 = infant on lap, 4 = infant in own seat). The two infant codes are
   * the ones to get right: a lap infant prices at ~10% of the adult fare
   * and an infant in its own seat at ~100%, and transposing them produces
   * a plausible wrong quote rather than an error.
   */
  passengers?: readonly number[];
  /** Cabin class (1 = economy, 2 = premium, 3 = business, 4 = first). */
  seat?: number;
  /**
   * Emit the field 16 constant that booking deep links carry. The search
   * page does not need it.
   */
  pinMaxU64?: boolean;
}

/**
 * Wrap encoded segments in the `tfs` envelope and base64 it.
 *
 * @param segments Concatenated output of {@link encodeTfsSegment}.
 * @returns URL-safe base64 string with padding stripped.
 */
export function encodeTfsPayload(segments: Uint8Array, options: EncodeTfsPayloadOptions): string {
  const { isOneWay, passengers = [1], seat = 1, pinMaxU64 = false } = options;
  let payload = concatBytes(varintField(1, 28), varintField(2, 2), segments);
  for (const kind of passengers) payload = concatBytes(payload, varintField(8, kind));
  payload = concatBytes(payload, varintField(9, seat), varintField(14, 1));
  if (pinMaxU64) {
    payload = concatBytes(payload, lengthDelim(16, concatBytes(tag(1, 0), varintBig(MAX_U64))));
  }
  payload = concatBytes(payload, varintField(19, isOneWay ? 2 : 1));
  return toUrlsafeB64(payload);
}

/**
 * Build the `tfs` query parameter for a Google Flights deep-link URL.
 *
 * The `tfs` token encodes the complete itinerary — one segment per travel
 * direction, each segment containing one leg per physical flight. It is
 * deterministic (no session id required) and can be constructed purely from
 * search-result data.
 *
 * 1:1 port of fli/search/_proto.py::build_tfs_token.
 *
 * @throws Error when `segments` is empty or any segment has no legs.
 */
export function buildTfsToken(segments: LegSpec[][], options: BuildTfsTokenOptions = {}): string {
  const isOneWay = options.isOneWay ?? true;
  const passengers = options.passengers ?? [1];
  const seat = options.seat ?? 1;
  if (segments.length === 0) throw new Error("segments must be non-empty");
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];
    if (!seg || seg.length === 0) throw new Error(`segment ${i} has no legs`);
  }

  let segmentProtos: Uint8Array = new Uint8Array(0);
  for (const seg of segments) {
    const first = seg[0] as LegSpec;
    const last = seg[seg.length - 1] as LegSpec;
    segmentProtos = concatBytes(
      segmentProtos,
      encodeTfsSegment(first.origin, last.dest, first.depDate, { legs: seg }),
    );
  }

  return encodeTfsPayload(segmentProtos, { isOneWay, passengers, seat, pinMaxU64: true });
}
