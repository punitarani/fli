/**
 * Copying filter objects before a search mutates them.
 *
 * Round-trip expansion pins a segment's `selected_flight` and the date
 * sweep rewrites segment dates per chunk; neither may touch the object
 * the caller handed in. Python does this with Pydantic's `model_copy`.
 *
 * There is exactly one implementation here on purpose. Both call sites
 * used to keep their own hand-written list of fields to copy, which is
 * the pattern that silently dropped `airlines_exclude` and the alliance
 * lists in Python: a filter left off the list is not an error, it is a
 * search that quietly ignores what the caller asked for. Copying every
 * own property means a filter added later is carried without anyone
 * having to remember to add it.
 */

/** A plain object literal — not a class instance, array or Date. */
function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null) return false;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

/**
 * Copy one field.
 *
 * Deep enough that nothing a search mutates is shared with the caller,
 * shallow enough to stay cheap: arrays and plain objects are copied one
 * level (recursively for nested plain values), while class instances —
 * `FlightSegment`, and `FlightResult` under `selected_flight` — are
 * handled by the caller or kept by reference. A `FlightResult` is only
 * ever read, so sharing it is safe and is what the previous
 * implementations did.
 */
function copyValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(copyValue);
  if (isPlainObject(value)) {
    const out: Record<string, unknown> = {};
    for (const [key, inner] of Object.entries(value)) out[key] = copyValue(inner);
    return out;
  }
  return value;
}

/**
 * Copy an object, keeping its prototype and every own enumerable field.
 *
 * The constructor is bypassed deliberately: re-running it would re-reject
 * a travel date that has since passed, or re-validate a range the caller
 * already got past, on a copy that is about to have those fields
 * rewritten anyway.
 */
function copyInstance<T extends object>(source: T): T {
  const out = Object.create(Object.getPrototypeOf(source)) as Record<string, unknown>;
  for (const [key, value] of Object.entries(source)) out[key] = copyValue(value);
  return out as T;
}

/** Shape shared by both filter classes: the part a search mutates. */
interface HasSegments {
  flight_segments: object[];
}

/**
 * Copy a `FlightSearchFilters` or `DateSearchFilters`.
 *
 * Every own field is carried over. `flight_segments` and the segments
 * themselves are fresh objects, so pinning a `selected_flight` or
 * rewriting a `travel_date` on the copy leaves the caller's filters
 * untouched.
 */
export function cloneFilters<T extends HasSegments>(filters: T): T {
  const out = copyInstance(filters);
  if (Array.isArray(filters.flight_segments)) {
    out.flight_segments = filters.flight_segments.map((segment) => copyInstance(segment));
  }
  return out;
}
