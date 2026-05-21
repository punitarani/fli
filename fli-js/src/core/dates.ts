/**
 * Shared YYYY-MM-DD parsing and formatting helpers.
 *
 * Lives in `core/` so the same canonical implementation backs every part
 * of the package — `models/google-flights/base.ts`, the date-search
 * filters, and `search/dates.ts` — rather than each maintaining its own
 * subtly-different copy.
 */

/** Strict YYYY-MM-DD shape (4 digit year, 2 digit month, 2 digit day). */
export const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Parse a YYYY-MM-DD string into a UTC `Date`.
 *
 * Rejects strings that don't match {@link ISO_DATE_RE} and rejects
 * out-of-range calendar dates (e.g. `2026-02-30` would round-trip to
 * March, so the round-trip check catches it). Throws {@link TypeError}
 * on any malformed input — consistent with the rest of the package.
 */
export function parseIsoDate(s: string): Date {
  if (!ISO_DATE_RE.test(s)) {
    throw new TypeError(`Expected YYYY-MM-DD date, got: ${s}`);
  }
  const parts = s.split("-").map((p) => Number.parseInt(p, 10));
  const [year, month, day] = parts;
  if (year == null || month == null || day == null) {
    throw new TypeError(`Expected YYYY-MM-DD date, got: ${s}`);
  }
  const d = new Date(Date.UTC(year, month - 1, day));
  if (d.getUTCFullYear() !== year || d.getUTCMonth() !== month - 1 || d.getUTCDate() !== day) {
    throw new TypeError(`Invalid date: ${s}`);
  }
  return d;
}

/** Format a `Date` as YYYY-MM-DD in UTC. */
export function formatIsoDate(d: Date): string {
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
