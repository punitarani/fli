/**
 * Flight search orchestrator — `GetShoppingResults` + `GetBookingResults`.
 *
 * 1:1 port of fli/search/flights.py.
 */

import type { GoogleFlightsUrlOptions } from "../core/links.ts";
import type { BookingOption, FlightResult } from "../models/google-flights/base.ts";
import { SeatType, TripType } from "../models/google-flights/base.ts";
import { FlightSearchFilters } from "../models/google-flights/flights.ts";
import { type Client, getClient } from "./client.ts";
import { parallelMap } from "./concurrency.ts";
import { parseBookingChunk, parseFlightRow } from "./decoders.ts";
import { SearchParseError } from "./exceptions.ts";
import { buildBookingToken, buildTfsToken, type LegSpec } from "./proto.ts";
import { withLocaleParams } from "./urls.ts";
import { iterWrbChunks, parseFirstWrbPayload } from "./wire.ts";

export interface SearchOptions {
  topN?: number;
  currency?: string | null;
  language?: string | null;
  country?: string | null;
}

export interface BookingOptions {
  currency?: string | null;
  language?: string | null;
  country?: string | null;
  bookingToken?: string | null;
  sessionId?: string | null;
}

/** Locale knobs plus cabin class for {@link SearchFlights.buildFlightBookingUrl}. */
export interface BookingUrlOptions extends GoogleFlightsUrlOptions {
  /** Cabin class encoded into the `tfs` token (field 9). Defaults to economy. */
  seatType?: SeatType;
}

export class SearchFlights {
  static readonly BASE_URL =
    "https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/GetShoppingResults";
  static readonly BOOKING_URL =
    "https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/GetBookingResults";

  private readonly client: Client;
  private _lastSessionId: string | null = null;

  constructor(client?: Client) {
    this.client = client ?? getClient();
  }

  /** Search for flights using the given filters. */
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
    });
    if (flights == null) return null;
    if (filters.trip_type === TripType.ONE_WAY) return flights;
    return this._expandMultiLeg(flights, filters, {
      topN,
      currency: options.currency ?? null,
      language: options.language ?? null,
      country: options.country ?? null,
    });
  }

  private async _fetchFlights(
    filters: FlightSearchFilters,
    opts: {
      currency: string | null;
      language: string | null;
      country: string | null;
      captureSession: boolean;
    },
  ): Promise<FlightResult[] | null> {
    const encoded = filters.encode();
    const url = withLocaleParams(
      SearchFlights.BASE_URL,
      opts.currency,
      opts.language,
      opts.country,
    );
    const response = await this.client.post(url, { body: `f.req=${encoded}` });
    const inner = parseFirstWrbPayload(response.text);
    if (inner == null) return null;

    if (opts.captureSession) this._captureSessionId(inner);

    if (!Array.isArray(inner)) {
      throw new SearchParseError("Shopping response shape changed — top-level is not an array");
    }

    const flightsRaw: unknown[] = [];
    for (const i of [2, 3]) {
      const block = inner[i];
      if (Array.isArray(block) && Array.isArray(block[0])) {
        for (const item of block[0]) flightsRaw.push(item);
      }
    }

    const flights: FlightResult[] = [];
    const failureSamples: string[] = [];
    let anyFailure = false;
    for (const row of flightsRaw) {
      if (!Array.isArray(row)) continue;
      try {
        flights.push(parseFlightRow(row));
      } catch (err) {
        anyFailure = true;
        const reason = `${err instanceof Error ? err.name : "Error"}: ${err instanceof Error ? err.message : String(err)}`;
        if (!failureSamples.includes(reason) && failureSamples.length < 3) {
          failureSamples.push(reason);
        }
      }
    }

    if (flightsRaw.length > 0 && anyFailure && flights.length === 0) {
      const sample = failureSamples.join("; ");
      throw new SearchParseError(
        `Parsed 0/${flightsRaw.length} flight rows — Google response shape may have changed (sample reasons: ${sample})`,
      );
    }

    return flights.length > 0 ? flights : null;
  }

  /** Fetch bookable fare options for a selected itinerary. */
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
    const response = await this.client.post(url, { body: `f.req=${encoded}` });

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

  private _captureSessionId(inner: unknown): void {
    if (!Array.isArray(inner)) return;
    const first = inner[0];
    if (!Array.isArray(first)) return;
    const session = first[4];
    if (typeof session === "string" && session.length > 0) {
      this._lastSessionId = session;
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

function cloneFilters(filters: FlightSearchFilters): FlightSearchFilters {
  // The constructor's date validator would re-reject past travel dates if
  // we ran it on a clone — bypass by writing fields directly.
  const out = Object.create(FlightSearchFilters.prototype) as FlightSearchFilters;
  Object.assign(out, {
    trip_type: filters.trip_type,
    passenger_info: { ...filters.passenger_info },
    flight_segments: filters.flight_segments.map((s) => {
      const clone = Object.create(Object.getPrototypeOf(s)) as typeof s;
      Object.assign(clone, {
        departure_airport: s.departure_airport,
        arrival_airport: s.arrival_airport,
        travel_date: s.travel_date,
        time_restrictions: s.time_restrictions,
        selected_flight: s.selected_flight,
      });
      return clone;
    }),
    stops: filters.stops,
    seat_type: filters.seat_type,
    price_limit: filters.price_limit ? { ...filters.price_limit } : null,
    airlines: filters.airlines ? [...filters.airlines] : null,
    airlines_exclude: filters.airlines_exclude ? [...filters.airlines_exclude] : null,
    alliances: filters.alliances ? [...filters.alliances] : null,
    alliances_exclude: filters.alliances_exclude ? [...filters.alliances_exclude] : null,
    max_duration: filters.max_duration,
    layover_restrictions: filters.layover_restrictions ? { ...filters.layover_restrictions } : null,
    sort_by: filters.sort_by,
    exclude_basic_economy: filters.exclude_basic_economy,
    emissions: filters.emissions,
    bags: filters.bags ? { ...filters.bags } : null,
    show_all_results: filters.show_all_results,
  });
  return out;
}
