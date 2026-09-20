/**
 * Currency extraction from Google Flights price tokens.
 *
 * 1:1 port of fli/core/currency.py — varint walk over a base64-urlsafe
 * protobuf payload to extract the nested ISO currency code, cached to
 * avoid repeated decoding for the common one-currency-per-response case.
 */

const _decodeCache = new Map<string, string | null>();
const MAX_CACHE = 256;

function readVarint(data: Uint8Array, offset: number): [number, number] {
  // `+= chunk * 2**shift` instead of `|= chunk << shift` — JavaScript's
  // bitwise operators coerce to signed 32-bit and would corrupt the
  // result for shifts ≥ 31 (i.e. varint values ≥ 2^31).
  let value = 0;
  let shift = 0;
  let off = offset;
  while (off < data.length) {
    const byte = data[off];
    if (byte === undefined) break;
    off += 1;
    value += (byte & 0x7f) * 2 ** shift;
    if ((byte & 0x80) === 0) {
      if (!Number.isSafeInteger(value)) {
        throw new Error("Varint exceeds Number.MAX_SAFE_INTEGER");
      }
      return [value, off];
    }
    shift += 7;
    if (shift >= 64) throw new Error("Varint is too large to decode");
  }
  throw new Error("Unexpected end of data while decoding varint");
}

function readLengthDelimited(data: Uint8Array, offset: number): [Uint8Array, number] {
  const [length, after] = readVarint(data, offset);
  const end = after + length;
  if (end > data.length) throw new Error("Length-delimited field exceeds payload size");
  return [data.subarray(after, end), end];
}

function skipField(data: Uint8Array, offset: number, wireType: number): number {
  if (wireType === 0) return readVarint(data, offset)[1];
  if (wireType === 1) {
    const end = offset + 8;
    if (end > data.length) throw new Error("Fixed64 field exceeds payload size");
    return end;
  }
  if (wireType === 2) return readLengthDelimited(data, offset)[1];
  if (wireType === 5) {
    const end = offset + 4;
    if (end > data.length) throw new Error("Fixed32 field exceeds payload size");
    return end;
  }
  throw new Error(`Unsupported wire type: ${wireType}`);
}

function extractCurrencyFromMessage(data: Uint8Array): string | null {
  let offset = 0;
  while (offset < data.length) {
    const [tag, afterTag] = readVarint(data, offset);
    offset = afterTag;
    const fieldNumber = tag >> 3;
    const wireType = tag & 0x07;

    if (fieldNumber === 3 && wireType === 2) {
      const [nested, after] = readLengthDelimited(data, offset);
      offset = after;
      let nestedOffset = 0;
      while (nestedOffset < nested.length) {
        const [ntag, na] = readVarint(nested, nestedOffset);
        nestedOffset = na;
        const nfield = ntag >> 3;
        const nwire = ntag & 0x07;
        if (nfield === 3 && nwire === 2) {
          const [bytes, _end] = readLengthDelimited(nested, nestedOffset);
          return new TextDecoder("utf-8").decode(bytes).toUpperCase();
        }
        nestedOffset = skipField(nested, nestedOffset, nwire);
      }
      continue;
    }

    offset = skipField(data, offset, wireType);
  }
  return null;
}

function base64UrlsafeDecode(token: string): Uint8Array {
  const padLen = (4 - (token.length % 4)) % 4;
  const padded = token + "=".repeat(padLen);
  const standard = padded.replace(/-/g, "+").replace(/_/g, "/");
  if (typeof atob !== "undefined") {
    const binary = atob(standard);
    const out = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
    return out;
  }
  return new Uint8Array(Buffer.from(standard, "base64"));
}

/**
 * Extract the ISO currency code from a Google Flights price token.
 *
 * Cached so the same token returned for every row in a response decodes
 * the protobuf payload exactly once.
 */
export function extractCurrencyFromPriceToken(token: string | null | undefined): string | null {
  if (!token) return null;
  if (_decodeCache.has(token)) return _decodeCache.get(token) ?? null;
  let result: string | null = null;
  try {
    const decoded = base64UrlsafeDecode(token);
    result = extractCurrencyFromMessage(decoded);
  } catch {
    result = null;
  }
  // LRU-ish bound: drop oldest if we hit the cap.
  if (_decodeCache.size >= MAX_CACHE) {
    const firstKey = _decodeCache.keys().next().value;
    if (firstKey !== undefined) _decodeCache.delete(firstKey);
  }
  _decodeCache.set(token, result);
  return result;
}

/** Currency-code-aware formatter built on `Intl.NumberFormat`. */
export function formatPrice(
  amount: number | null | undefined,
  currencyCode: string | null | undefined,
): string {
  if (amount == null) {
    return currencyCode ? `${currencyCode.toUpperCase()} —` : "—";
  }
  if (!currencyCode) {
    return amount.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }
  const normalized = currencyCode.toUpperCase();
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: normalized,
    }).format(amount);
  } catch {
    return `${normalized} ${amount.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }
}

/** Build a chart-axis label for one or more result currencies. */
export function formatPriceAxisLabel(currencies: Iterable<string | null | undefined>): string {
  const set = new Set<string>();
  for (const c of currencies) {
    if (c) set.add(c.toUpperCase());
  }
  if (set.size === 1) {
    const [only] = set;
    return `Price (${only})`;
  }
  return "Price";
}

/** Clear the in-memory token-decode cache (test helper). */
export function _clearCurrencyCache(): void {
  _decodeCache.clear();
}
