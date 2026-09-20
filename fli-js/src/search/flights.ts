/**
 * Flight search orchestrator.
 *
 * Results come from Google's public `/travel/flights` page — see
 * `tfs.ts` for why, and for the token that addresses it. Booking options
 * still go through the `GetBookingResults` RPC, which is gated: that call
 * now fails with {@link SearchRejectedError} rather than returning
 * anything.
 *
 * 1:1 port of fli/search/flights.py.
 */

import type { GoogleFlightsUrlOptions } from "../core/links.ts";
import type { BookingOption, FlightResult, PassengerInfo } from "../models/google-flights/base.ts";
import { SeatType, SortBy, TripType } from "../models/google-flights/base.ts";
import type { FlightSearchFilters } from "../models/google-flights/flights.ts";
import { type Client, getClient } from "./client.ts";
import { cloneFilters } from "./clone.ts";
import { parallelMap, throwIfAborted } from "./concurrency.ts";
import { parseBookingChunk, parseFlightRow } from "./decoders.ts";
import { SearchParseError } from "./exceptions.ts";
import { getSearchLogger } from "./logging.ts";
import { buildBookingToken, buildTfsToken, type LegSpec } from "./proto.ts";
import {
  applyClientSideFilters,
  buildTfs,
  fetchPayload,
  pageUrl,
  unsupportedFilters,
} from "./tfs.ts";
import { withLocaleParams } from "./urls.ts";
import { iterWrbChunks } from "./wire.ts";

/**
 * Google inlines fewer rows — in premium cabins often none — for parties
 * with children or infants, because those fares are priced client-side
 * through the gated RPC this transport cannot reach; extra adults cost
 * nothing. Measured live 2026-09-20: JFK-LHR economy held 23 rows for one
 * adult and 16 with a lap infant; SFO-NRT business held 9 for one or two
 * adults and 0 with a child.
 */
export const SPARSE_PASSENGER_MIX_WARNING =
  "No itineraries were inlined for this passenger mix. Google's search page " +
  "prices parties with children or infants client-side, so it often carries " +
  "few or no rows for them — most of all in premium cabins. This does not " +
  "mean the route has no flights: an adults-only search shows the schedule.";

/**
 * Whether the party includes anyone Google prices client-side.
 *
 * Extra adults ride the request for free; children and infants (lap or
 * seat) are the passenger types that make the search-page transport inline
 * fewer — sometimes zero — rows. See {@link SPARSE_PASSENGER_MIX_WARNING}.
 */
function hasChildrenOrInfants(passengerInfo: PassengerInfo): boolean {
  return passengerInfo.children + passengerInfo.infants_on_lap + passengerInfo.infants_in_seat > 0;
}

/**
 * Result ordering for `sortBy`.
 *
 * The search page serves Google's own default order, so the sort the
 * caller asked for is applied here instead of in the request.
 * `TOP_FLIGHTS` / `BEST` are Google's own blended rankings, which we
 * can't reproduce — those keep the page's order.
 */
function sortFlights(flights: FlightResult[], sortBy: SortBy): void {
  const rank = (f: FlightResult): [number, number] => {
    switch (sortBy) {
      case SortBy.CHEAPEST:
        return [f.price == null ? 1 : 0, f.price ?? 0];
      case SortBy.DURATION:
        return [f.duration == null ? 1 : 0, f.duration ?? 0];
      case SortBy.DEPARTURE_TIME:
        return [0, f.legs[0]?.departure_datetime.getTime() ?? 0];
      case SortBy.ARRIVAL_TIME:
        return [0, f.legs[f.legs.length - 1]?.arrival_datetime.getTime() ?? 0];
      default:
        return [0, 0];
    }
  };
  // `Array.prototype.sort` is required to be stable, so rows that tie on
  // the key keep Google's own ordering — the same guarantee Python's
  // `list.sort` gives.
  flights.sort((a, b) => {
    const ka = rank(a);
    const kb = rank(b);
    return ka[0] - kb[0] || ka[1] - kb[1];
  });
}

export interface SearchOptions {
  topN?: number;
  currency?: string | null;
  language?: string | null;
  country?: string | null;
  /**
   * Cancels the search. A round trip is several sequential page fetches
   * with backoffs between them, so this reaches every one of them —
   * including the sleeps — and rejects with the reason it was aborted with.
   */
  signal?: AbortSignal;
}

export interface BookingOptions {
  currency?: string | null;
  language?: string | null;
  country?: string | null;
  bookingToken?: string | null;
  sessionId?: string | null;
  /** Cancels the booking request. */
  signal?: AbortSignal;
}

/** Locale knobs plus cabin class for {@link SearchFlights.buildFlightBookingUrl}. */
export interface BookingUrlOptions extends GoogleFlightsUrlOptions {
  /** Cabin class encoded into the `tfs` token (field 9). Defaults to economy. */
  seatType?: SeatType;
}

export class SearchFlights {
  /**
   * @deprecated Kept only so the exported surface does not move. Searches
   * no longer POST here: `GetShoppingResults` requires a browser-signed
   * `x-goog-batchexecute-bgr` header and answers every other client with
   * error 13. Results come from `PAGE_URL` in `tfs.ts` instead.
   */
  static readonly BASE_URL =
    "https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/GetShoppingResults";
  /**
   * The `GetBookingResults` RPC. Still used by {@link SearchFlights.getBookingOptions},
   * and still gated the same way — that call currently throws
   * `SearchRejectedError`.
   */
  static readonly BOOKING_URL =
    "https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/GetBookingResults";

  private readonly client: Client;
  private _lastSessionId: string | null = null;

  constructor(client?: Client) {
    this.client = client ?? getClient();
  }

  /**
   * Search for flights using the given filters.
   *
   * One page fetch for a one-way trip; for a round trip, one more per
   * expanded outbound candidate (`topN`, default 5).
   *
   * @returns For one-way trips, `FlightResult[]`. For round trips, one
   *   array per itinerary (`[outbound, return]`). `null` when nothing
   *   survived the filters.
   * @throws {SearchUnsupportedError} Multi-city, which the page cannot serve.
   * @throws {SearchParseError} The page loaded but carried no readable rows.
   * @throws {SearchClientError} Network or HTTP failure.
   */
  async search(
    filters: FlightSearchFilters,
    options: SearchOptions = {},
  ): Promise<Array<FlightResult | FlightResult[]> | null> {
    const topN = options.topN ?? 5;
    const flights = await this._fetchFlights(filters, {
      currency: options.currency ?? null,
      language: options.language ?? null,
      country: options.country ?? null,
      captureSession: true,
      signal: options.signal,
    });
    if (flights == null) {
      this._warnIfSparsePassengerMix(filters);
      return null;
    }
    if (filters.trip_type === TripType.ONE_WAY) return flights;
    const combos = await this._expandMultiLeg(flights, filters, {
      topN,
      currency: options.currency ?? null,
      language: options.language ?? null,
      country: options.country ?? null,
      signal: options.signal,
    });
    if (combos.length === 0) this._warnIfSparsePassengerMix(filters);
    return combos;
  }

  /**
   * Warn once when an empty result may be Google's pricing gap, not a dead route.
   *
   * Called only from {@link SearchFlights.search}, after the trip's final
   * result is known to be empty — never from {@link SearchFlights._fetchFlights},
   * which the round-trip expansion calls once per candidate outbound. That
   * keeps this to exactly one warning per `search` call, one-way or
   * round-trip alike.
   */
  private _warnIfSparsePassengerMix(filters: FlightSearchFilters): void {
    if (hasChildrenOrInfants(filters.passenger_info)) {
      getSearchLogger().warn(SPARSE_PASSENGER_MIX_WARNING);
    }
  }

  private async _fetchFlights(
    filters: FlightSearchFilters,
    opts: {
      currency: string | null;
      language: string | null;
      country: string | null;
      captureSession: boolean;
      signal?: AbortSignal;
    },
  ): Promise<FlightResult[] | null> {
    throwIfAborted(opts.signal);

    const dropped = unsupportedFilters(filters);
    if (dropped.length > 0) {
      getSearchLogger().warn(
        `Filters not supported by the search-page transport, ignored: ${dropped.join(", ")}`,
      );
    }

    const url = pageUrl(buildTfs(filters), opts.currency, opts.language, opts.country);
    const inner = await fetchPayload(this.client, url, { signal: opts.signal });
    if (inner == null) {
      throw new SearchParseError(
        "Search page carried no ds:1 payload — Google may have changed " +
          "the page shape, or served a consent/blocked page instead.",
      );
    }

    if (opts.captureSession) this._captureSessionId(inner);

    if (!Array.isArray(inner)) {
      throw new SearchParseError("Shopping response shape changed — top-level is not an array");
    }

    // Mirrors Python's
    //   [item for i in (2, 3) if isinstance(inner[i], list) for item in inner[i][0]]
    // wrapped in `except (IndexError, TypeError)`, condition for condition:
    //
    //   slot missing entirely      -> IndexError      -> SearchParseError
    //   slot present, not a list   -> skipped by the isinstance check
    //   slot is an empty list      -> IndexError on [0] -> SearchParseError
    //   [0] is not iterable        -> TypeError       -> SearchParseError
    //   [0] is a list (even empty) -> those are the rows
    //
    // Skipping a missing structure and returning `null` instead would
    // report the likeliest future Google change — rows moving out of
    // `[2][0]` — as "no flights on this route", which is exactly the
    // silent failure this transport exists to avoid. A block that is
    // present and simply holds no rows stays a legitimate empty answer.
    const flightsRaw: unknown[] = [];
    try {
      for (const i of [2, 3]) {
        if (i >= inner.length) {
          throw new RangeError(`payload has ${inner.length} elements, no inner[${i}]`);
        }
        const block = inner[i];
        if (!Array.isArray(block)) continue;
        if (block.length === 0) {
          throw new RangeError(`inner[${i}] is empty, no inner[${i}][0]`);
        }
        const rows = block[0];
        // Python would iterate any iterable here; the only shape Google
        // has ever served is a list, and anything else reaches
        // SearchParseError there too (every "row" fails to parse), just
        // by a longer route and with a less useful message.
        if (!Array.isArray(rows)) {
          throw new TypeError(`inner[${i}][0] is ${typeof rows}, not a list of rows`);
        }
        for (const item of rows) flightsRaw.push(item);
      }
    } catch (err) {
      throw new SearchParseError(
        "Shopping response shape changed — no flights array at inner[2]/[3]: " +
          `${err instanceof Error ? err.message : String(err)}`,
        { cause: err },
      );
    }

    const flights: FlightResult[] = [];
    const failureSamples: string[] = [];
    let anyFailure = false;
    const noteFailure = (reason: string): void => {
      anyFailure = true;
      if (!failureSamples.includes(reason) && failureSamples.length < 3) {
        failureSamples.push(reason);
      }
    };
    for (const row of flightsRaw) {
      // A row that is not a list is a *failed* row, not an absent one.
      // Python hands it to `parse_flight_row` and gets back
      // `TypeError: 'int' object is not subscriptable`, which counts
      // towards the "parsed 0 of N" tripwire below. Skipping it quietly
      // meant a block of scalars came back as "no flights on this route".
      // One bad row among good ones still costs only that row.
      if (!Array.isArray(row)) {
        noteFailure(`TypeError: '${row === null ? "null" : typeof row}' row is not subscriptable`);
        continue;
      }
      try {
        flights.push(parseFlightRow(row));
      } catch (err) {
        noteFailure(
          `${err instanceof Error ? err.name : "Error"}: ${err instanceof Error ? err.message : String(err)}`,
        );
      }
    }

    if (flightsRaw.length > 0 && anyFailure && flights.length === 0) {
      const sample = failureSamples.join("; ");
      throw new SearchParseError(
        `Parsed 0/${flightsRaw.length} flight rows — Google response shape may have changed (sample reasons: ${sample})`,
      );
    }

    const kept = applyClientSideFilters(flights, filters);
    sortFlights(kept, filters.sort_by);
    return kept.length > 0 ? kept : null;
  }

  /**
   * Fetch bookable fare options for a selected itinerary.
   *
   * Currently unavailable: this is the one call still made against the
   * `GetBookingResults` RPC, which since 2026-08 requires an
   * `x-goog-batchexecute-bgr` header signed by Google's own page
   * JavaScript. Expect {@link SearchRejectedError}. Per-itinerary booking
   * links are still available — see
   * {@link SearchFlights.buildFlightBookingUrl}, which needs no network
   * call at all.
   *
   * @throws {SearchRejectedError} Google declined the RPC (the normal outcome).
   */
  async getBookingOptions(
    flight: FlightResult | FlightResult[],
    filters: FlightSearchFilters,
    options: BookingOptions = {},
  ): Promise<BookingOption[]> {
    const results: FlightResult[] = Array.isArray(flight) ? flight : [flight];
    if (results.length === 0) {
      throw new Error("flight argument must be a FlightResult or non-empty array of them");
    }

    const effectiveSession = options.sessionId ?? this._lastSessionId ?? null;

    let token = options.bookingToken ?? null;
    if (
      token == null &&
      effectiveSession &&
      (results[results.length - 1] as FlightResult).price != null
    ) {
      const last = results[results.length - 1] as FlightResult;
      const lastLeg = last.legs[last.legs.length - 1];
      if (lastLeg) {
        const airlineCode = (lastLeg.airline as string).replace(/^_/, "");
        token = buildBookingToken({
          sessionId: effectiveSession,
          airlineCode,
          flightNumber: lastLeg.flight_number,
          legIndex: 1,
          priceCents: Math.round((last.price ?? 0) * 100),
          currency: last.currency ?? options.currency ?? "USD",
        });
      }
    }

    if (token == null) {
      token =
        (results[results.length - 1] as FlightResult).booking_token ??
        (results[0] as FlightResult).booking_token ??
        null;
    }
    if (!token) {
      throw new Error(
        "Missing booking token. Call SearchFlights.search(...) before getBookingOptions(...) so the client can cache the session id, or pass `sessionId` / `bookingToken` explicitly.",
      );
    }

    // Apply the selected_flight on a CLONE of the filters so we don't mutate the caller's input.
    const prepared = cloneFilters(filters);
    const segments = prepared.flight_segments;
    if (results.length > segments.length) {
      throw new Error(`flight has ${results.length} segments but filters has ${segments.length}`);
    }
    for (let i = 0; i < results.length; i++) {
      const seg = segments[i];
      const res = results[i];
      if (seg && res) seg.selected_flight = res;
    }

    const encoded = SearchFlights._encodeBookingPayload(token, prepared);
    const url = withLocaleParams(
      SearchFlights.BOOKING_URL,
      options.currency ?? null,
      options.language ?? null,
      options.country ?? null,
    );
    const response = await this.client.post(url, {
      body: `f.req=${encoded}`,
      ...(options.signal ? { signal: options.signal } : {}),
    });

    const chunks = [...iterWrbChunks(response.text)];
    if (chunks.length === 0) return [];

    const parsed = await parallelMap((chunk) => Promise.resolve(parseBookingChunk(chunk)), chunks);
    const out: BookingOption[] = [];
    for (const chunkOptions of parsed) out.push(...chunkOptions);
    return out;
  }

  /**
   * Build a Google Flights deep-link URL for a specific itinerary.
   *
   * Constructs `https://www.google.com/travel/flights/booking?tfs=…` that opens
   * the booking page pre-loaded with the given itinerary — the airline/OTA fare
   * options and the "Continue" booking CTA included.
   *
   * The `tfs` itinerary token is fully deterministic (built from the flight's
   * airports, dates and flight numbers); no session id or network round-trip is
   * required, so the same itinerary always yields the same URL. This method
   * never throws — on malformed input it falls back to the generic Google
   * Flights URL.
   *
   * @param flight A single `FlightResult` (one-way / single segment) or an
   *   array of them (round-trip / multi-city, one element per travel direction).
   */
  buildFlightBookingUrl(
    flight: FlightResult | FlightResult[],
    options: BookingUrlOptions = {},
  ): string {
    const results: FlightResult[] = Array.isArray(flight) ? flight : [flight];
    // Round-trip is exactly 2 segments; one-way and multi-city (3+) both use
    // isOneWay=true (f19=2). Only round-trip sets f19=1.
    const isOneWay = results.length !== 2;

    const iata = (x: unknown): string => String(x).replace(/^_/, "");
    // Match the decoder, which stores datetimes with local components
    // (new Date(y, m-1, d, h, min)); read them back the same way.
    const depDate = (d: Date): string => {
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, "0");
      const day = String(d.getDate()).padStart(2, "0");
      return `${y}-${m}-${day}`;
    };

    let url: string;
    try {
      const segments: LegSpec[][] = results.map((result) =>
        result.legs.map((leg) => ({
          origin: iata(leg.departure_airport),
          depDate: depDate(leg.departure_datetime),
          dest: iata(leg.arrival_airport),
          airline: iata(leg.airline),
          flightNumber: leg.flight_number,
        })),
      );
      const tfs = buildTfsToken(segments, { isOneWay, seat: options.seatType ?? SeatType.ECONOMY });
      url = `https://www.google.com/travel/flights/booking?tfs=${tfs}`;
    } catch {
      url = "https://www.google.com/travel/flights";
    }

    return withLocaleParams(
      url,
      options.currency ?? null,
      options.language ?? null,
      options.country ?? null,
    );
  }

  /**
   * Cache the shopping session id from `inner[0][4]` of a search payload.
   *
   * A shape change here means booking calls fall back to "missing token"
   * errors, so it warns rather than silently leaving the cache untouched.
   */
  private _captureSessionId(inner: unknown): void {
    const first = Array.isArray(inner) ? inner[0] : undefined;
    if (!Array.isArray(first)) {
      getSearchLogger().warn(
        "Failed to capture the shopping session id from the search page " +
          "(payload[0] is not an array); getBookingOptions() calls without an " +
          "explicit sessionId will fail.",
      );
      return;
    }
    const session = first[4];
    if (typeof session === "string" && session.length > 0) {
      this._lastSessionId = session;
    } else {
      getSearchLogger().warn(
        `Search page payload[0][4] is ${JSON.stringify(session)}, not a non-empty ` +
          "string; the session cache is unchanged.",
      );
    }
  }

  // ------------------------------------------------------------------
  // Round-trip / multi-city expansion
  // ------------------------------------------------------------------

  private async _expandMultiLeg(
    flights: FlightResult[],
    filters: FlightSearchFilters,
    opts: {
      topN: number;
      currency: string | null;
      language: string | null;
      country: string | null;
      signal?: AbortSignal;
    },
  ): Promise<Array<FlightResult[]>> {
    const numSegments = filters.flight_segments.length;
    const selectedCount = filters.flight_segments.filter((s) => s.selected_flight != null).length;
    if (selectedCount >= numSegments - 1) {
      return flights.map((f) => [f]);
    }

    const candidates = flights.slice(0, opts.topN);

    const expand = async (
      outbound: FlightResult,
    ): Promise<[FlightResult, FlightResult[] | Array<FlightResult[]> | null]> => {
      const nextFilters = cloneFilters(filters);
      const seg = nextFilters.flight_segments[selectedCount];
      if (seg) seg.selected_flight = outbound;
      const subFlights = await this._fetchFlights(nextFilters, {
        currency: opts.currency,
        language: opts.language,
        country: opts.country,
        captureSession: false,
        signal: opts.signal,
      });
      if (subFlights == null) return [outbound, null];
      if (selectedCount + 1 < numSegments - 1) {
        const expanded = await this._expandMultiLeg(subFlights, nextFilters, opts);
        return [outbound, expanded];
      }
      return [outbound, subFlights];
    };

    const expansions = await parallelMap(expand, candidates);

    const combos: FlightResult[][] = [];
    for (const [outbound, nextResults] of expansions) {
      if (nextResults == null) continue;
      for (const nxt of nextResults) {
        if (Array.isArray(nxt)) {
          combos.push([outbound, ...nxt]);
        } else {
          combos.push([outbound, nxt as FlightResult]);
        }
      }
    }
    return combos;
  }

  // ------------------------------------------------------------------
  // Booking payload construction
  // ------------------------------------------------------------------

  static _encodeBookingPayload(token: string, filters: FlightSearchFilters): string {
    const formatted = filters.format();
    if (formatted.length < 2 || !Array.isArray(formatted[1])) {
      throw new Error(
        "filters.format() did not return a main struct at index 1; cannot construct a booking payload.",
      );
    }
    let main = formatted[1] as unknown[];
    if (main.length > 18) main = main.slice(0, 18);
    const payload: unknown[] = [[null, token], main, null, 0];
    const wrapped: unknown[] = [null, JSON.stringify(payload)];
    return encodeURIComponent(JSON.stringify(wrapped));
  }
}
