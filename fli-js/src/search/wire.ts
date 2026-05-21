/**
 * Parser for Google Flights' FlightsFrontendService wire format.
 *
 * 1:1 port of fli/search/_wire.py — handles both the legacy single-chunk
 * JSONP shape and the multi-chunk format used by GetBookingResults.
 *
 * Important quirk: the length headers count UTF-8 BYTES, not characters,
 * so the parser operates on `Uint8Array` rather than the JS string.
 */

const PREFIX = ")]}'";
const PREFIX_BYTES = new TextEncoder().encode(PREFIX);

const decoder = new TextDecoder("utf-8", { fatal: false });

function toBytes(body: string | Uint8Array): Uint8Array {
  if (body instanceof Uint8Array) return body;
  return new TextEncoder().encode(body);
}

function lstrip(buf: Uint8Array): Uint8Array {
  let i = 0;
  while (i < buf.length) {
    const b = buf[i];
    if (b !== 0x20 && b !== 0x09 && b !== 0x0a && b !== 0x0d) break;
    i++;
  }
  return buf.subarray(i);
}

function startsWith(buf: Uint8Array, prefix: Uint8Array): boolean {
  if (buf.length < prefix.length) return false;
  for (let i = 0; i < prefix.length; i++) {
    if (buf[i] !== prefix[i]) return false;
  }
  return true;
}

function indexOfByte(buf: Uint8Array, byte: number, from = 0): number {
  for (let i = from; i < buf.length; i++) {
    if (buf[i] === byte) return i;
  }
  return -1;
}

function* chunksFromOuter(outer: unknown): Generator<unknown> {
  if (!Array.isArray(outer)) return;
  for (const row of outer) {
    if (!Array.isArray(row) || row.length < 3) continue;
    if (row[0] !== "wrb.fr") continue;
    const inner = row[2];
    if (typeof inner !== "string" || inner.length === 0) continue;
    try {
      yield JSON.parse(inner);
    } catch {
      // Skip malformed inner JSON.
    }
  }
}

/** Yield the inner JSON of every `wrb.fr` chunk in `body`. */
export function* iterWrbChunks(body: string | Uint8Array): Generator<unknown> {
  let raw = toBytes(body);
  raw = lstrip(raw);
  if (startsWith(raw, PREFIX_BYTES)) {
    raw = raw.subarray(PREFIX_BYTES.length);
  }
  raw = lstrip(raw);
  if (raw.length === 0) return;

  // Fast path: legacy single-chunk responses with no length headers.
  const first = raw[0];
  if (first === undefined || first < 0x30 || first > 0x39) {
    try {
      const outer = JSON.parse(decoder.decode(raw));
      yield* chunksFromOuter(outer);
    } catch {
      // Discard malformed body.
    }
    return;
  }

  let cursor = 0;
  while (cursor < raw.length) {
    const end = indexOfByte(raw, 0x0a, cursor);
    if (end === -1) break;
    const headerText = decoder.decode(raw.subarray(cursor, end));
    // Python's `int(...)` raises on `"12abc"`; `Number.parseInt` returns 12,
    // which would slip the parser into garbage chunk offsets. Require a pure
    // decimal header to keep wire-format strictness in sync.
    if (!/^[0-9]+$/.test(headerText)) break;
    const length = Number.parseInt(headerText, 10);
    if (!Number.isFinite(length)) break;
    cursor = end + 1;
    const chunkBytes = Math.max(length - 1, 0);
    const payload = raw.subarray(cursor, cursor + chunkBytes);
    cursor += chunkBytes;
    try {
      const trimmed = decoder.decode(payload).trim();
      const outer = JSON.parse(trimmed);
      yield* chunksFromOuter(outer);
    } catch {
      // Discard malformed chunks.
    }
  }
}

/** Return the inner JSON of the first `wrb.fr` chunk, or `null`. */
export function parseFirstWrbPayload(body: string | Uint8Array): unknown {
  for (const chunk of iterWrbChunks(body)) {
    return chunk;
  }
  return null;
}
