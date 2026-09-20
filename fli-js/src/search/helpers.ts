/**
 * Defensive accessors for the nested-list response payloads. Mirrors
 * fli/search/_helpers.py.
 */

export function safeGet(seq: unknown, idx: number): unknown {
  if (Array.isArray(seq) && idx >= 0 && idx < seq.length) {
    return seq[idx];
  }
  return null;
}

export function asBool(v: unknown): boolean | null {
  return typeof v === "boolean" ? v : null;
}

export function asStr(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 ? v : null;
}

export function asInt(v: unknown): number | null {
  if (typeof v === "boolean") return null;
  if (typeof v !== "number") return null;
  if (!Number.isInteger(v)) return null;
  return v;
}

export function asNonNegativeInt(v: unknown): number | null {
  const n = asInt(v);
  return n != null && n >= 0 ? n : null;
}
