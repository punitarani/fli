/**
 * Search transport built on Google Flights' public `/travel/flights` page.
 *
 * Since 2026-08 the `FlightsFrontendService` RPC endpoints
 * (`GetShoppingResults`, `GetCalendarGraph`) require an
 * `x-goog-batchexecute-bgr` header that only the page's own JavaScript can
 * produce. The signature is bound to the exact request bytes, so a captured
 * token cannot be replayed against a different body — every plain HTTP
 * client gets HTTP 200 with a payload-less `wrb.fr` row carrying error 13.
 *
 * The public search page is not gated that way. It serves the same result
 * payload inline, in an `AF_initDataCallback` blob keyed `ds:1`, whose
 * elements `[2]` and `[3]` hold exactly the flight rows the RPC used to
 * return — so `decoders.ts` keeps working untouched. The page is addressed
 * by a `tfs` protobuf parameter instead of the `f.req` JSON struct, which
 * is what this module builds.
 *
 * Scope note: `tfs` carries trip type, segments, stop limit, cabin,
 * passengers, alliances and layover restrictions. Filters with no known
 * `tfs` field (airline include/exclude, price cap, duration, departure
 * window) are applied to the decoded results instead — see
 * {@link applyClientSideFilters}. Anything that can be neither encoded nor
 * filtered after the fact is reported by {@link unsupportedFilters} so the
 * caller can warn rather than silently return results that ignore it.
 *
 * Multi-city is out of reach here entirely: the page inlines no rows for
 * it, so {@link buildTfs} refuses those searches rather than returning the
 * first leg's one-way board.
 *
 * 1:1 port of fli/search/_tfs.py.
 */

import type { Airline } from "../models/airline.ts";
import type {
  FlightResult,
  FlightSegment,
  TimeRestrictions,
} from "../models/google-flights/base.ts";
import { TripType } from "../models/google-flights/base.ts";
import type { DateSearchFilters } from "../models/google-flights/dates.ts";
import type { FlightSearchFilters } from "../models/google-flights/flights.ts";
import type { Client } from "./client.ts";
import { SearchUnsupportedError } from "./exceptions.ts";
import { getSearchLogger } from "./logging.ts";
import { encodeTfsPayload, encodeTfsSegment, type LegSpec } from "./proto.ts";

/** Filter objects this transport can encode — both carry the same core fields. */
export type TfsFilters = FlightSearchFilters | DateSearchFilters;

export const PAGE_URL = "https://www.google.com/travel/flights";

/**
 * How many times one page is fetched before giving up on its `ds:1` blob.
 *
 * Roughly one page in sixty comes back HTTP 200 with every other
 * `AF_initDataCallback` block present but no `ds:1` one — a transient
 * variant, not a block: the identical request succeeds seconds later. A
 * round trip fetches six pages and a date sweep one per date, so at that
 * rate an unretried search fails noticeably often.
 *
 * Retry only this exact case. HTTP errors and error-13 rejections are
 * already handled (and retried, where appropriate) by the client, and
 * re-fetching them here would just multiply a hard failure. Worst case is
 * 3 fetches per page, so a healthy N-date sweep stays N requests.
 */
export const PAGE_FETCH_ATTEMPTS = 3;

/** Backoff in milliseconds between page fetch attempts. */
export const PAGE_RETRY_BACKOFF_MS = [500, 1500] as const;

type SleepFn = (ms: number) => Promise<void>;

const defaultSleep: SleepFn = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let sleepImpl: SleepFn = defaultSleep;

/**
 * Replace the page-retry backoff (test seam).
 *
 * Pass `null` to restore the real `setTimeout` sleep. Mirrors the
 * `_tfs._sleep` indirection the Python tests patch, so a retry test can
 * observe the backoff without waiting two seconds for it.
 */
export function _setPageRetrySleep(sleep: SleepFn | null): void {
  sleepImpl = sleep ?? defaultSleep;
}

// `AF_initDataCallback({key: 'ds:1', hash: '..', data:[...], sideChannel: {}});`
const DS_BLOB = /AF_initDataCallback\((\{[\s\S]*?\})\);/g;
const DS_KEY = /key:\s*'([^']+)'/;
const DS_DATA = /data:([\s\S]*?), sideChannel/;

/**
 * Passenger kinds, in the order Google's repeated field 8 numbers them:
 * 1 = adult, 2 = child, 3 = infant on lap, 4 = infant in own seat.
 *
 * The two infant codes are easy to transpose and the mistake is expensive
 * rather than loud: on an international route a lap infant prices at ~10%
 * of the adult fare and an infant in its own seat at ~100%, so a swap
 * quotes a plausible but wrong fare instead of erroring. Pricing one fixed
 * itinerary (BA178 JFK->LHR, economy) confirms the mapping — $295 for
 * `[1]`, $324 for `[1, 3]` (+10%, lap), $589 for `[1, 4]` (+100%, own
 * seat, same as the `[1, 2]` child fare). The legacy RPC struct orders the
 * same four counts `[adults, children, infants_on_lap, infants_in_seat]`.
 */
const PASSENGER_FIELDS = [
  ["adults", 1],
  ["children", 2],
  ["infants_on_lap", 3],
  ["infants_in_seat", 4],
] as const;

/**
 * Filters with no `tfs` encoding and no reliable post-hoc equivalent —
 * the decoded rows don't carry the data needed to apply them locally.
 */
const UNSUPPORTED = ["emissions", "bags", "exclude_basic_economy"] as const;

/** Return the bare IATA code for an Airport/Airline constant. */
function iata(value: unknown): string {
  return String(value).replace(/^_/, "");
}

/** Read a segment's airport list as flat IATA codes. */
function airportCodes(entries: ReadonlyArray<ReadonlyArray<readonly [string, number]>>): string[] {
  const out: string[] = [];
  for (const group of entries) {
    for (const entry of group) out.push(iata(entry[0]));
  }
  return out;
}

/** Format a `Date` as `YYYY-MM-DD` using its local components. */
function localDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Describe a chosen itinerary as the leg specs `tfs` pins it by. */
function legsOf(flight: FlightResult): LegSpec[] {
  return flight.legs.map((leg) => ({
    origin: iata(leg.departure_airport),
    depDate: localDate(leg.departure_datetime),
    dest: iata(leg.arrival_airport),
    airline: iata(leg.airline),
    flightNumber: String(leg.flight_number),
  }));
}

export interface BuildTfsOptions {
  /**
   * Per-segment date overrides, used by the date sweep to reprice one
   * segment set across a range without cloning the whole filter object
   * per day.
   */
  travelDates?: readonly string[] | null;
}

/**
 * Build the `tfs` URL parameter for `filters`.
 *
 * @returns The base64url `tfs` value, unpadded, as Google's own URLs carry it.
 * @throws {SearchUnsupportedError} For multi-city trips, which this
 *   transport cannot serve at all.
 */
export function buildTfs(filters: TfsFilters, options: BuildTfsOptions = {}): string {
  // Field 19 is the trip type. Multi-city is 3, but sending 2 (one-way)
  // makes Google ignore every segment past the first and serve the first
  // leg's one-way board, which decodes cleanly into wrong results;
  // sending 3 renders the right board in a browser but inlines no flight
  // rows — multi-city is fetched client-side through the RPC gated since
  // 2026-08.
  if (filters.trip_type === TripType.MULTI_CITY) {
    throw new SearchUnsupportedError(
      "Multi-city search is not available through the search-page transport: " +
        "Google loads those results client-side through the gated RPC, so the " +
        "page carries no rows to read. Search each leg separately. " +
        "See github.com/punitarani/fli#223.",
    );
  }

  const travelDates = options.travelDates ?? null;
  const stops = filters.stops;
  const passengers: number[] = [];
  for (const [field, code] of PASSENGER_FIELDS) {
    const count = filters.passenger_info[field] ?? 0;
    for (let i = 0; i < count; i++) passengers.push(code);
  }

  // Google reads alliances out of the same carrier lists as airline codes.
  const carriers = (filters.alliances ?? []).map((a) => String(a));
  const carriersExclude = (filters.alliances_exclude ?? []).map((a) => String(a));
  const layovers = filters.layover_restrictions;

  const parts: Uint8Array[] = [];
  filters.flight_segments.forEach((segment: FlightSegment, index: number) => {
    const selected = segment.selected_flight;
    parts.push(
      encodeTfsSegment(
        airportCodes(
          segment.departure_airport as ReadonlyArray<ReadonlyArray<readonly [string, number]>>,
        ),
        airportCodes(
          segment.arrival_airport as ReadonlyArray<ReadonlyArray<readonly [string, number]>>,
        ),
        travelDates ? (travelDates[index] ?? segment.travel_date) : segment.travel_date,
        {
          legs: selected != null ? legsOf(selected) : [],
          // MaxStops.ANY (0) must leave the field out — writing 0 for it
          // would silently pin every search to non-stop.
          maxStops: stops ? stops - 1 : null,
          carriers,
          carriersExclude,
          layoverAirports: (layovers?.airports ?? []).map(iata),
          minLayover: layovers?.min_duration ?? null,
          maxLayover: layovers?.max_duration ?? null,
        },
      ),
    );
  });

  let total = 0;
  for (const part of parts) total += part.length;
  const segments = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    segments.set(part, offset);
    offset += part.length;
  }

  return encodeTfsPayload(segments, {
    isOneWay: filters.trip_type === TripType.ONE_WAY,
    passengers: passengers.length > 0 ? passengers : [1],
    seat: filters.seat_type,
  });
}

/** Build the search-page URL for a `tfs` value and locale. */
export function pageUrl(
  tfs: string,
  currency?: string | null,
  language?: string | null,
  country?: string | null,
): string {
  const params = [`tfs=${tfs}`, `hl=${language || "en"}`, `gl=${country || "US"}`];
  if (currency) params.push(`curr=${currency}`);
  return `${PAGE_URL}?${params.join("&")}`;
}

/**
 * Pull the `ds:1` payload out of a rendered search page.
 *
 * Returns the same structure the RPC used to hand back, so callers can
 * keep reading `payload[2]` / `payload[3]` for flight rows.
 */
export function extractPayload(html: string): unknown {
  DS_BLOB.lastIndex = 0;
  let match: RegExpExecArray | null = DS_BLOB.exec(html);
  while (match !== null) {
    const blob = match[1] ?? "";
    const key = DS_KEY.exec(blob);
    if (key && key[1] === "ds:1") {
      const data = DS_DATA.exec(blob);
      if (data?.[1] != null) {
        try {
          return JSON.parse(data[1]);
        } catch (err) {
          // One concise line. This sits on the per-page path, which the
          // retry below runs up to three times and a date sweep runs once
          // per date — a stack trace here would put hundreds of them on a
          // user's stderr. The detail stays at debug.
          getSearchLogger().warn(
            `ds:1 blob is not valid JSON: ${err instanceof Error ? err.message : String(err)}`,
          );
          getSearchLogger().debug("ds:1 blob decode failed", err);
          return null;
        }
      }
    }
    match = DS_BLOB.exec(html);
  }
  return null;
}

export interface FetchPayloadOptions {
  /** Propagated to the client so a caller can cancel the fetch. */
  signal?: AbortSignal;
}

/**
 * Fetch a search page and return its `ds:1` payload, or `null`.
 *
 * The single entry point both the flight search and the date sweep use,
 * so the transient-page retry described at {@link PAGE_FETCH_ATTEMPTS}
 * applies identically to each. Only a 200 with no `ds:1` blob is retried;
 * HTTP and network errors propagate on the first attempt exactly as
 * before.
 *
 * @returns The decoded payload, or `null` when every attempt came back
 *   without one — the caller decides whether that is fatal.
 */
export async function fetchPayload(
  client: Client,
  url: string,
  options: FetchPayloadOptions = {},
): Promise<unknown> {
  for (let attempt = 0; attempt < PAGE_FETCH_ATTEMPTS; attempt++) {
    const response = await client.get(url, options.signal ? { signal: options.signal } : {});
    const payload = extractPayload(response.text);
    if (payload != null) {
      if (attempt > 0) {
        getSearchLogger().debug(`Search page carried ds:1 on attempt ${attempt + 1}`);
      }
      return payload;
    }
    if (attempt + 1 < PAGE_FETCH_ATTEMPTS) {
      const delay =
        PAGE_RETRY_BACKOFF_MS[Math.min(attempt, PAGE_RETRY_BACKOFF_MS.length - 1)] ?? 500;
      getSearchLogger().debug(
        `Search page carried no ds:1 payload (attempt ${attempt + 1}/${PAGE_FETCH_ATTEMPTS}); retrying in ${delay}ms`,
      );
      await sleepImpl(delay);
    }
  }
  return null;
}

/** Name the set filters this transport can neither encode nor emulate. */
export function unsupportedFilters(filters: TfsFilters): string[] {
  const named: string[] = [];
  for (const attr of UNSUPPORTED) {
    const value = (filters as unknown as Record<string, unknown>)[attr];
    if (value == null || value === false) continue;
    if (Array.isArray(value) && value.length === 0) continue;
    // `EmissionsFilter.ALL` (0) is "unset" for our purposes.
    if (attr === "emissions" && value === 0) continue;
    named.push(attr);
  }
  return named;
}

/**
 * Apply the filters `tfs` has no field for, to already-decoded rows.
 *
 * Google would have applied these server-side and back-filled the result
 * list, so a filtered search returns fewer options here than the old RPC
 * did — but every option it does return honours the filter.
 */
export function applyClientSideFilters(
  flights: readonly FlightResult[],
  filters: TfsFilters,
): FlightResult[] {
  const airlines = new Set((filters.airlines ?? []).map((a: Airline) => iata(a)));
  const excluded = new Set((filters.airlines_exclude ?? []).map((a: Airline) => iata(a)));
  const maxDuration = filters.max_duration ?? null;
  const maxPrice = filters.price_limit?.max_price ?? null;

  // These rows describe whichever segment the caller is still choosing,
  // not necessarily the outbound one. Round-trip expansion pins a segment
  // by setting its `selected_flight` and re-fetches, so the flights coming
  // back belong to the first segment that is still unpinned. Filtering a
  // return leg against the outbound window drops valid evening returns and
  // keeps invalid ones, silently and in the caller's favour-looking
  // direction.
  const segments = filters.flight_segments;
  let active = segments.findIndex((s: FlightSegment) => s.selected_flight == null);
  if (active === -1) active = Math.max(0, segments.length - 1);
  const window = segments.length > 0 ? (segments[active]?.time_restrictions ?? null) : null;

  const out: FlightResult[] = [];
  for (const flight of flights) {
    const carriers = new Set(flight.legs.map((l) => iata(l.airline)));
    if (airlines.size > 0 && ![...carriers].some((c) => airlines.has(c))) continue;
    if (excluded.size > 0 && [...carriers].some((c) => excluded.has(c))) continue;
    if (maxDuration != null && flight.duration && flight.duration > maxDuration) continue;
    if (maxPrice != null && flight.price && flight.price > maxPrice) continue;
    if (!withinWindow(flight, window)) continue;
    out.push(flight);
  }
  return out;
}

/**
 * Check a flight's departure/arrival hours against a segment's window.
 *
 * `FlightResult.legs` has no minimum length and `parseFlightRow` happily
 * returns a row whose `detail[2]` was empty, so an unguarded `legs[0]`
 * here would throw out of the whole search on one odd row. A flight with
 * no legs has no departure time to judge, so it cannot satisfy a time
 * window — drop it rather than crash.
 */
function withinWindow(flight: FlightResult, restrictions: TimeRestrictions | null): boolean {
  if (restrictions == null) return true;
  const first = flight.legs[0];
  const last = flight.legs[flight.legs.length - 1];
  if (first == null || last == null) return false;
  const departure = first.departure_datetime.getHours();
  const arrival = last.arrival_datetime.getHours();
  const checks: Array<[number | null | undefined, number, "min" | "max"]> = [
    [restrictions.earliest_departure, departure, "min"],
    [restrictions.latest_departure, departure, "max"],
    [restrictions.earliest_arrival, arrival, "min"],
    [restrictions.latest_arrival, arrival, "max"],
  ];
  for (const [bound, actual, kind] of checks) {
    if (bound == null) continue;
    if (kind === "min" && actual < bound) return false;
    if (kind === "max" && actual > bound) return false;
  }
  return true;
}
