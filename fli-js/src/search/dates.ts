/**
 * Date-based flight search — the cheapest price for each date in a range.
 *
 * Google's `GetCalendarGraph` RPC used to hand back a whole date grid in
 * one call, but it now requires a browser-signed
 * `x-goog-batchexecute-bgr` header (see `tfs.ts`). The public search page
 * has no such grid, so each date costs its own page fetch. Those run
 * concurrently under the shared rate limiter, and the range is capped —
 * see {@link MAX_DATES_PER_SEARCH}.
 *
 * 1:1 port of fli/search/dates.py.
 */

import { formatIsoDate, parseIsoDate } from "../core/dates.ts";
import type { FlightResult } from "../models/google-flights/base.ts";
import { TripType } from "../models/google-flights/base.ts";
import type { DateSearchFilters } from "../models/google-flights/dates.ts";
import { type Client, getClient } from "./client.ts";
import { cloneFilters } from "./clone.ts";
import { parallelMap, throwIfAborted } from "./concurrency.ts";
import { parseFlightRow } from "./decoders.ts";
import { SearchClientError, SearchParseError } from "./exceptions.ts";
import { getSearchLogger } from "./logging.ts";
import {
  applyClientSideFilters,
  buildTfs,
  fetchPayload,
  pageUrl,
  unsupportedFilters,
} from "./tfs.ts";

const MAX_DAYS_PER_SEARCH = 61;
const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * Same wording the flight path uses for the same condition, so a caller
 * who sees it on either path gets the same hint about what to check.
 *
 * Exported (mirroring the Python module's `_NO_PAYLOAD`, importable despite
 * the underscore) so tests can build `DateOutcome`s that exercise the
 * no-payload branch of {@link SearchDates._collect} exactly.
 */
export const NO_PAYLOAD =
  "the search page carried no ds:1 payload — Google may have changed the " +
  "page shape, or served a consent/blocked page instead";

/**
 * Most dates a single {@link SearchDates.search} call will price.
 *
 * The public search page carries no calendar grid, so every date in the
 * range costs its own full page fetch (~2 MB). Ninety-three days is a
 * whole quarter — comfortably wider than the 61-day chunk size — and caps
 * one search at roughly 190 MB of transfer rather than letting a
 * "2026-01-01 to 2026-12-31" request quietly issue 365 requests.
 */
export const MAX_DATES_PER_SEARCH = 93;

/**
 * Payload-less pages, before any success, that abandon a sweep.
 *
 * Retries multiply. The client retries a request three times, and
 * `fetchPayload` fetches a page up to three times, so one date can cost
 * nine HTTP requests before it gives up — and a client that is being
 * blocked (an EU/EEA IP with the consent cookie disabled, say) fails that
 * way on *every* date. Paying it 93 times to learn one fact is the wrong
 * trade.
 *
 * Only the payload-less page counts. That failure is deterministic: a
 * consent or block page is served to every request alike, so the dates
 * not yet tried will fail the same way. A connection error or timeout
 * says nothing about them, so counting those would abandon a healthy
 * sweep over a transient wobble.
 *
 * The breaker also only looks at the start of a sweep: it arms while no
 * date has produced a usable page, and disarms permanently the moment one
 * does. A working sweep therefore keeps the full retry budget for every
 * transient miss in it.
 */
export const SWEEP_FAILURE_THRESHOLD = 5;

/**
 * Tracks whether a sweep is failing the one way that is worth quitting
 * over.
 *
 * One instance per sweep, never module-global: two concurrent sweeps must
 * not be able to trip each other's breaker. JavaScript runs the date
 * workers on one thread, so unlike the Python original this needs no
 * lock — but the counter is still shared by every in-flight promise in
 * the sweep, which is the point.
 */
class SweepHealth {
  private blocked = 0;
  private anySuccess = false;
  private skippedCount = 0;

  constructor(private readonly threshold: number) {}

  /** Note a date whose page arrived; disarms the breaker for good. */
  recordSuccess(): void {
    this.anySuccess = true;
  }

  /**
   * Note a date whose page arrived without a `ds:1` payload.
   *
   * Only this failure mode counts towards the threshold — see
   * {@link SWEEP_FAILURE_THRESHOLD} for why a network error deliberately
   * does not.
   */
  recordBlocked(): void {
    this.blocked++;
  }

  /** Note a date abandoned because the breaker had already tripped. */
  recordSkip(): void {
    this.skippedCount++;
  }

  /** How many dates were abandoned without being requested. */
  get skipped(): number {
    return this.skippedCount;
  }

  /** Has the sweep only ever been blocked, and enough times? */
  shouldStop(): boolean {
    return !this.anySuccess && this.blocked >= this.threshold;
  }
}

export interface DatePrice {
  /** Single date for one-way searches, or `[outbound, return]` for round trip. */
  date: [Date] | [Date, Date];
  price: number;
  currency: string | null;
}

export interface DateSearchOptions {
  currency?: string | null;
  language?: string | null;
  country?: string | null;
  /**
   * Cancels the sweep. A 93-date range is up to 93 page fetches with
   * backoffs between their retries; this reaches every one of them,
   * sleeps included.
   */
  signal?: AbortSignal;
}

/**
 * What pricing one date produced.
 *
 * Richer than a bare `DatePrice | null` so the caller can tell "this date
 * had no flights" apart from "this date never loaded". Exported for
 * {@link SearchDates._collect}, which tests drive directly because the
 * interesting states (a tripped breaker alongside real prices) depend on
 * how the sweep's concurrent fetches happen to interleave.
 */
export interface DateOutcome {
  /** The cheapest itinerary for the date, or null when skipped/failed/empty. */
  price: DatePrice | null;
  /** Human-readable reason the date could not be priced, or null. */
  failure: string | null;
  /** The error behind `failure`, kept for chaining. */
  error: unknown;
  /** False for dates skipped before any request, so they don't count as failures. */
  attempted: boolean;
}

function outcome(over: Partial<DateOutcome> = {}): DateOutcome {
  return { price: null, failure: null, error: null, attempted: true, ...over };
}

/** Midnight UTC today. */
function todayUtc(): Date {
  const now = new Date();
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
}

/**
 * The earliest date that is still "today" somewhere on Earth.
 *
 * Real UTC offsets span UTC-12 to UTC+14, so any traveller's local date
 * is within one day of the UTC date. Anchoring to `utcToday - 1` never
 * skips a date that is still today-or-future for the actual traveller;
 * the cost is that a genuinely past date may reach Google, which simply
 * returns no flights. Mirrors `earliest_searchable_date()` in the Python
 * models.
 */
function earliestSearchableDate(): Date {
  return new Date(todayUtc().getTime() - DAY_MS);
}

/**
 * Decode every flight row in a `ds:1` payload.
 *
 * Total by construction: a payload whose `[2]` / `[3]` slots are absent,
 * empty, or not the nested list we expect yields no flights instead of an
 * error that would abort the whole sweep. Individual unparseable rows are
 * skipped the same way the flight search skips them.
 */
function flightsIn(payload: unknown): FlightResult[] {
  const flights: FlightResult[] = [];
  if (!Array.isArray(payload)) return flights;
  for (const index of [2, 3]) {
    const block = index < payload.length ? payload[index] : null;
    if (!Array.isArray(block) || block.length === 0) continue;
    const rows = block[0];
    if (!Array.isArray(rows)) continue;
    for (const row of rows) {
      if (!Array.isArray(row)) continue;
      try {
        flights.push(parseFlightRow(row));
      } catch {
        // One bad row must not cost the whole date.
      }
    }
  }
  return flights;
}

/**
 * Up to 3 distinct failure messages, in the order they were first seen.
 *
 * Shared by every `_collect` branch that raises or warns about failed
 * dates, so the same range always gets the same short list however it is
 * reported.
 */
function reasonsFor(failed: DateOutcome[]): string[] {
  const reasons: string[] = [];
  for (const o of failed) {
    if (o.failure != null && !reasons.includes(o.failure) && reasons.length < 3) {
      reasons.push(o.failure);
    }
  }
  return reasons;
}

export class SearchDates {
  /**
   * @deprecated Kept only so the exported surface does not move. The
   * sweep no longer POSTs here: `GetCalendarGraph` requires a
   * browser-signed `x-goog-batchexecute-bgr` header and answers every
   * other client with error 13. Each date is priced from its own
   * `/travel/flights` page instead.
   */
  static readonly BASE_URL =
    "https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/GetCalendarGraph";

  /** Range size at which the sweep splits into independent chunk filters. */
  static readonly MAX_DAYS_PER_SEARCH = MAX_DAYS_PER_SEARCH;

  /** Most dates one `search` call will price. See {@link MAX_DATES_PER_SEARCH}. */
  static readonly MAX_DATES_PER_SEARCH = MAX_DATES_PER_SEARCH;

  private readonly client: Client;

  constructor(client?: Client) {
    this.client = client ?? getClient();
  }

  /**
   * Price every date in the filters' range.
   *
   * Every date costs its own search-page fetch — the page serves no
   * calendar grid — so the range is capped at
   * {@link MAX_DATES_PER_SEARCH} dates. Internally it is still split into
   * {@link MAX_DAYS_PER_SEARCH}-day chunk filters, but all dates are
   * priced by a single flat parallel map.
   *
   * @returns One entry per date that could be priced, or `null` when no
   *   date in the range had flights.
   * @throws {RangeError} The range covers more than
   *   {@link MAX_DATES_PER_SEARCH} dates.
   * @throws {SearchParseError} Every date came back without a payload —
   *   a consent or block page, not an empty route.
   * @throws {SearchClientError} Every date failed for some other reason,
   *   or nothing priced because at least half the attempted dates never
   *   loaded — see {@link SearchDates._collect}.
   */
  async search(
    filters: DateSearchFilters,
    options: DateSearchOptions = {},
  ): Promise<DatePrice[] | null> {
    throwIfAborted(options.signal);

    const dropped = unsupportedFilters(filters);
    if (dropped.length > 0) {
      getSearchLogger().warn(
        `Filters not supported by the search-page transport, ignored: ${dropped.join(", ")}`,
      );
    }

    const fromDate = parseIsoDate(filters.from_date);
    const toDate = parseIsoDate(filters.to_date);

    // Build every chunk descriptor up front so the per-date requests
    // share no mutable state.
    const tasks: Array<[DateSearchFilters, Date]> = [];
    for (const chunk of this._buildChunkFilters(filters, fromDate, toDate)) {
      for (const day of SearchDates._daysIn(chunk)) tasks.push([chunk, day]);
    }

    if (tasks.length > MAX_DATES_PER_SEARCH) {
      throw new RangeError(
        `This date search covers ${tasks.length} dates, above the ` +
          `${MAX_DATES_PER_SEARCH}-date limit. Google's search page serves no ` +
          "calendar grid, so every date costs its own full page fetch. " +
          "Narrow the range (or run several smaller searches).",
      );
    }

    // One flat map over every date. `health` is the sweep's circuit
    // breaker: a client that is being blocked fails identically on every
    // date, and each failed date costs up to nine HTTP requests once the
    // client's retries and the page retry multiply. Queued dates check it
    // before spending anything.
    const health = new SweepHealth(SWEEP_FAILURE_THRESHOLD);
    const outcomes = await parallelMap(
      ([chunk, day]: [DateSearchFilters, Date]) => this._priceOneDate(chunk, day, options, health),
      tasks,
    );

    // A cancelled sweep rejects; it never hands back the dates it happened
    // to finish first. A truncated list of prices is indistinguishable
    // from a complete one at the call site, so returning it would turn a
    // cancellation into a wrong answer — and `_collect` would otherwise
    // describe the cancelled dates as a blocked or failed sweep, which is
    // not what happened.
    throwIfAborted(options.signal);

    return SearchDates._collect(outcomes, tasks.length, health.skipped);
  }

  /** List every date in one chunk's `from_date`..`to_date` range. */
  private static _daysIn(filters: DateSearchFilters): Date[] {
    const from = filters.parsed_from_date;
    const to = filters.parsed_to_date;
    const days: Date[] = [];
    for (let t = from.getTime(); t <= to.getTime(); t += DAY_MS) days.push(new Date(t));
    return days;
  }

  /**
   * Assemble priced dates, raising when nothing could be fetched at all.
   *
   * A date with no flights is a legitimate answer; a date whose page
   * never arrived is not. When *every* attempted date failed, returning
   * an empty list would report a dead transport as "this route has no
   * flights" — exactly the silent failure this client exists to avoid.
   *
   * A sweep that tripped the circuit breaker must never end quietly
   * either. With prices to show, the answer is real but incomplete, so it
   * comes with one warning naming the count.
   *
   * The breaker is not the only way a sweep can go quietly wrong, though:
   * it disarms for good the instant any page loads, empty or not, so "1
   * loaded, 29 timeouts" sails straight past it — one date out of thirty
   * is not enough evidence that a route has no flights. When nothing
   * priced and at least half the attempted dates never loaded (`failed
   * >= loaded`), that is raised too. A page did load in that case, which
   * rules out an EU/EEA consent wall — those block every request alike —
   * so this path never adds the `FLI_SOCS_COOKIE` hint the branch above
   * does.
   *
   * Short of either throw, a sweep that lost some dates but not enough to
   * doubt the rest still owes the caller exactly one line saying so,
   * whether or not it ends up with anything to return.
   *
   * Internal — underscore-prefixed rather than `private` so tests can
   * drive it with a fixed set of outcomes instead of racing the sweep's
   * concurrent fetches into the state they want to assert.
   *
   * @param outcomes One entry per date in the range, in date order.
   * @param total Dates the sweep set out to price.
   * @param skipped Dates the breaker abandoned without requesting them.
   *   Non-zero exactly when the breaker tripped.
   */
  static _collect(outcomes: DateOutcome[], total: number, skipped: number): DatePrice[] | null {
    const results = outcomes.flatMap((o) => (o.price != null ? [o.price] : []));
    const attempted = outcomes.filter((o) => o.attempted);
    const failed = attempted.filter((o) => o.failure != null);
    // "loaded" counts every attempted date whose page actually arrived,
    // priced or not — it does not distinguish the two, because when
    // `results` is empty (the only time this number matters below) every
    // loaded date is by definition one with no flights.
    const loaded = attempted.length - failed.length;
    // The breaker only ever trips on payload-less pages, so a non-zero
    // skip count *is* the blocked-page diagnosis, whatever else failed
    // alongside.
    const tripped = skipped > 0;
    const everythingFailed = attempted.length > 0 && failed.length === attempted.length;

    if (results.length === 0 && (everythingFailed || tripped)) {
      const reasons = reasonsFor(failed);
      const cause = failed.find((o) => o.error != null)?.error;
      const blocked =
        tripped || (failed.length > 0 && failed.every((o) => o.failure === NO_PAYLOAD));

      let message: string;
      if (everythingFailed) {
        message =
          `Priced 0 of ${total} dates — every date in the range failed. ` +
          `Reasons: ${reasons.join("; ")}`;
      } else {
        // Some attempted date loaded and simply had no flights, which is
        // not a failure on its own — but with nothing priced anywhere and
        // the breaker tripped, the sweep still has no usable answer.
        message =
          `Priced 0 of ${total} dates — no date in the range could be priced. ` +
          `Reasons: ${reasons.join("; ") || "no flights on the dates that loaded"}`;
      }
      if (tripped) {
        message +=
          `. Gave up after ${attempted.length} of ${total} dates (${skipped} skipped): ` +
          "a sweep that has not loaded a single page is failing for the same " +
          "reason on every date, and each one costs several requests";
      }
      if (blocked) {
        message +=
          ". If you are on an EU/EEA IP, Google's consent interstitial serves no " +
          "results — the client sends a pre-accepted SOCS cookie by default, so " +
          "check FLI_SOCS_COOKIE has not been set to an empty value";
      }
      const ErrorType = blocked ? SearchParseError : SearchClientError;
      throw new ErrorType(message, cause != null ? { cause } : undefined);
    }

    if (results.length === 0 && failed.length > 0 && failed.length >= loaded) {
      // The breaker never saw this coming: one loaded page (even an empty
      // one) disarms it for good, so a sweep that is mostly timeouts
      // around a single lucky date never trips it. Half the attempted
      // dates never loading is its own signal that "no flights" cannot be
      // concluded from the handful that did.
      const reasons = reasonsFor(failed);
      const cause = failed.find((o) => o.error != null)?.error;
      const blocked = failed.length > 0 && failed.every((o) => o.failure === NO_PAYLOAD);
      const ErrorType = blocked ? SearchParseError : SearchClientError;
      const message =
        `Priced 0 of ${total} dates — ${failed.length} of the ${attempted.length} dates ` +
        `tried failed to load, so "no flights" cannot be concluded from the ${loaded} ` +
        `that did. Reasons: ${reasons.join("; ")}`;
      // Unlike the branch above, a page did load here — that rules out a
      // consent wall, which blocks every request identically. Adding the
      // FLI_SOCS_COOKIE hint would point at a diagnosis this sweep just
      // disproved, so it is deliberately left off.
      throw new ErrorType(message, cause != null ? { cause } : undefined);
    }

    if (tripped) {
      // Exactly one line, whatever the sweep's size: the caller is about
      // to act on a partial answer and has no other way to know it.
      getSearchLogger().warn(
        `Date sweep returned ${results.length} of ${total} dates: ${skipped} were skipped ` +
          `after ${SWEEP_FAILURE_THRESHOLD} pages came back without a ds:1 payload and none ` +
          "had loaded yet. The prices below are real but incomplete — retry, or check " +
          "FLI_SOCS_COOKIE if you are in the EU/EEA.",
      );
    } else if (failed.length > 0 && results.length > 0) {
      // Neither throw fired — most dates loaded fine — but the caller
      // still can't tell a complete sweep from this one just by looking
      // at the list, so it gets the same "exactly one line" treatment.
      getSearchLogger().warn(
        `Date sweep priced ${results.length} of ${total} dates: ${failed.length} failed ` +
          "to load. The prices below are real but incomplete.",
      );
    } else if (failed.length > 0) {
      // No results, but too few dates failed to throw: most of the sweep
      // loaded fine and simply found nothing. Still worth a line —
      // otherwise a caller sees only `null`, indistinguishable from a
      // sweep where every date loaded and truly had no flights.
      const reasons = reasonsFor(failed);
      getSearchLogger().warn(
        `Date sweep found no flights on the ${loaded} dates that loaded; ${failed.length} ` +
          `of ${attempted.length} dates failed to load, so treat this as provisional ` +
          `rather than a confirmed empty range. Reasons: ${reasons.join("; ")}`,
      );
    }
    return results.length > 0 ? results : null;
  }

  /**
   * Split the filters' date range into independent per-chunk copies.
   *
   * The flight segments are cloned per chunk and their `travel_date`
   * advanced by the chunk offset so each chunk represents a distinct,
   * self-contained search — which keeps the outbound/return gap a
   * round-trip sweep reads its duration from.
   */
  private _buildChunkFilters(
    filters: DateSearchFilters,
    fromDate: Date,
    toDate: Date,
  ): DateSearchFilters[] {
    const chunks: DateSearchFilters[] = [];
    let currentFrom = fromDate;
    let chunkIndex = 0;
    while (currentFrom.getTime() <= toDate.getTime()) {
      const endMs = currentFrom.getTime() + (MAX_DAYS_PER_SEARCH - 1) * DAY_MS;
      const currentTo = new Date(Math.min(endMs, toDate.getTime()));
      const cloned = cloneFilters(filters);
      if (chunkIndex > 0) {
        const shiftDays = MAX_DAYS_PER_SEARCH * chunkIndex;
        for (const segment of cloned.flight_segments) {
          const segDate = parseIsoDate(segment.travel_date);
          segment.travel_date = formatIsoDate(new Date(segDate.getTime() + shiftDays * DAY_MS));
        }
      }
      cloned.from_date = formatIsoDate(currentFrom);
      cloned.to_date = formatIsoDate(currentTo);
      chunks.push(cloned);
      currentFrom = new Date(currentTo.getTime() + DAY_MS);
      chunkIndex++;
    }
    return chunks;
  }

  /**
   * Price one departure date through its own search-page fetch.
   *
   * Total by construction — one bad date must never sink the sweep, so
   * every failure comes back as a `DateOutcome` rather than a rejection.
   *
   * `health` is the sweep's circuit breaker. It is consulted before any
   * request, so a date still queued when the sweep is already known to be
   * failing deterministically costs nothing at all.
   */
  private async _priceOneDate(
    filters: DateSearchFilters,
    day: Date,
    options: DateSearchOptions,
    health: SweepHealth,
  ): Promise<DateOutcome> {
    const dates: Date[] = [day];
    if (filters.trip_type === TripType.ROUND_TRIP) {
      // `duration` is optional, so fall back to the gap between the two
      // segments — which the filter model keeps consistent with it.
      let tripDays = filters.duration;
      if (tripDays == null) {
        const segments = filters.flight_segments;
        const a = segments[0]?.parsed_travel_date.getTime() ?? 0;
        const b = segments[1]?.parsed_travel_date.getTime() ?? 0;
        tripDays = Math.round((b - a) / DAY_MS);
      }
      dates.push(new Date(day.getTime() + tripDays * DAY_MS));
    }
    const travelDates = dates.map(formatIsoDate);

    // The caller has cancelled: start no further date. `attempted: false`
    // keeps it out of every tally — `search` rejects with the abort reason
    // before `_collect` ever runs, and a cancelled date is not evidence of
    // a blocked client.
    if (options.signal?.aborted) {
      return outcome({ attempted: false });
    }

    // A date sweep can straddle today, and past dates are simply not
    // bookable — skip them rather than spend a request on them.
    if (day.getTime() < earliestSearchableDate().getTime()) {
      return outcome({ attempted: false });
    }

    // Nothing in this sweep has loaded and enough dates have failed, so
    // this one will fail too. Skip it rather than spend its retry budget;
    // `attempted: false` keeps it out of the "everything failed" tally,
    // which the already-failed dates satisfy on their own.
    if (health.shouldStop()) {
      health.recordSkip();
      return outcome({ attempted: false });
    }

    const url = pageUrl(
      buildTfs(filters, { travelDates }),
      options.currency ?? null,
      options.language ?? null,
      options.country ?? null,
    );

    let flights: FlightResult[];
    try {
      const payload = await fetchPayload(this.client, url, { signal: options.signal });
      if (payload == null) {
        // Logged here rather than thrown: one bad date is a warning, and
        // `_collect` decides whether *every* date failing is fatal.
        getSearchLogger().warn(
          `Pricing ${travelDates[0]} failed: the search page carried no ds:1 payload`,
        );
        health.recordBlocked();
        return outcome({ failure: NO_PAYLOAD });
      }

      // The page arrived and decoded; from here on the sweep is healthy
      // and later misses get their full retry budget.
      health.recordSuccess();

      // The filters Google has no `tfs` field for (airlines, price cap,
      // duration, departure window) are applied to the decoded rows,
      // exactly as the flight search applies them — otherwise the
      // cheapest price for a date is taken over itineraries the caller
      // asked to exclude.
      //
      // Decoding and filtering sit inside the `try` on purpose: they walk
      // attacker-shaped data from the wire, and letting one odd row throw
      // out of here would sink the whole sweep.
      flights = applyClientSideFilters(flightsIn(payload), filters);
    } catch (err) {
      // An in-flight date that was cancelled is not a failed date. Warning
      // about it, counting it towards "every date failed", or feeding it
      // to the circuit breaker would all report a problem that is not
      // there — the caller knows perfectly well why the sweep stopped.
      if (options.signal?.aborted) {
        return outcome({ attempted: false });
      }
      // One concise line per bad date; the stack trace stays at debug.
      const name = err instanceof Error ? err.name : "Error";
      const detail = err instanceof Error ? err.message : String(err);
      getSearchLogger().warn(`Pricing ${travelDates[0]} failed: ${name}: ${detail}`);
      getSearchLogger().debug(`Pricing ${travelDates[0]} failed`, err);
      // Deliberately not fed to the breaker: an error here (a timeout, a
      // reset connection) tells us nothing about the dates that have not
      // been tried, unlike a page served without its payload.
      return outcome({ failure: `${name}: ${detail}`, error: err });
    }

    // `!flight.price` and not `== null`: a zero price is Google's way of
    // saying it has no fare for the row, the same reading the Python sweep
    // takes with `if flight.price`.
    let cheapest: FlightResult | null = null;
    let cheapestPrice = Number.POSITIVE_INFINITY;
    for (const flight of flights) {
      if (!flight.price) continue;
      if (flight.price < cheapestPrice) {
        cheapest = flight;
        cheapestPrice = flight.price;
      }
    }
    if (cheapest == null) return outcome();

    return outcome({
      price: {
        date: dates as [Date] | [Date, Date],
        price: cheapestPrice,
        // Python reports the requested currency here and nothing when
        // none was asked for; the row's own currency is a strictly better
        // fallback than null, and matches what this field meant before
        // the transport moved.
        currency: options.currency ?? cheapest.currency ?? null,
      },
    });
  }
}
