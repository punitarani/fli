/**
 * Minimal protobuf encoder for the GetBookingResults token.
 *
 * 1:1 port of fli/search/_proto.py — preserves the byte-perfect
 * reproduction of a captured live booking token.
 */

import { Buffer } from "node:buffer";

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
