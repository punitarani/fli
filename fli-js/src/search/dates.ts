/**
 * Date-based flight search. Finds the cheapest prices across a date range
 * using Google Flights' GetCalendarGraph RPC.
 *
 * 1:1 port of fli/search/dates.py.
 */

import { extractCurrencyFromPriceToken } from "../core/currency.ts";
import { formatIsoDate, parseIsoDate } from "../core/dates.ts";
import { TripType } from "../models/google-flights/base.ts";
import { DateSearchFilters } from "../models/google-flights/dates.ts";
import { type Client, getClient } from "./client.ts";
import { parallelMap } from "./concurrency.ts";
import { withLocaleParams } from "./urls.ts";
import { parseFirstWrbPayload } from "./wire.ts";

const MAX_DAYS_PER_SEARCH = 61;
const BASE_URL =
  "https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/GetCalendarGraph";

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
}

function cloneSegments(filters: DateSearchFilters) {
  return filters.flight_segments.map((s) => {
    const clone = Object.create(Object.getPrototypeOf(s)) as typeof s;
    Object.assign(clone, {
      departure_airport: s.departure_airport,
      arrival_airport: s.arrival_airport,
      travel_date: s.travel_date,
      time_restrictions: s.time_restrictions,
      selected_flight: s.selected_flight,
    });
    return clone;
  });
}

function cloneFilters(filters: DateSearchFilters): DateSearchFilters {
  const out = Object.create(DateSearchFilters.prototype) as DateSearchFilters;
  Object.assign(out, {
    trip_type: filters.trip_type,
    passenger_info: { ...filters.passenger_info },
    flight_segments: cloneSegments(filters),
    stops: filters.stops,
    seat_type: filters.seat_type,
    price_limit: filters.price_limit ? { ...filters.price_limit } : null,
    airlines: filters.airlines ? [...filters.airlines] : null,
    airlines_exclude: filters.airlines_exclude ? [...filters.airlines_exclude] : null,
    alliances: filters.alliances ? [...filters.alliances] : null,
    alliances_exclude: filters.alliances_exclude ? [...filters.alliances_exclude] : null,
    max_duration: filters.max_duration,
    layover_restrictions: filters.layover_restrictions ? { ...filters.layover_restrictions } : null,
    emissions: filters.emissions,
    bags: filters.bags ? { ...filters.bags } : null,
    from_date: filters.from_date,
    to_date: filters.to_date,
    duration: filters.duration,
  });
  return out;
}

export class SearchDates {
  static readonly BASE_URL = BASE_URL;
  static readonly MAX_DAYS_PER_SEARCH = MAX_DAYS_PER_SEARCH;

  private readonly client: Client;

  constructor(client?: Client) {
    this.client = client ?? getClient();
  }

  async search(
    filters: DateSearchFilters,
    options: DateSearchOptions = {},
  ): Promise<DatePrice[] | null> {
    const fromDate = parseIsoDate(filters.from_date);
    const toDate = parseIsoDate(filters.to_date);
    const dayMs = 24 * 60 * 60 * 1000;
    const dateRange = Math.floor((toDate.getTime() - fromDate.getTime()) / dayMs) + 1;

    if (dateRange <= MAX_DAYS_PER_SEARCH) {
      return this._searchChunk(filters, options);
    }

    const chunkFilters = this._buildChunkFilters(filters, fromDate, toDate);
    const chunkResults = await parallelMap((cf) => this._searchChunk(cf, options), chunkFilters);

    const allResults: DatePrice[] = [];
    for (const r of chunkResults) {
      if (r) allResults.push(...r);
    }
    return allResults.length > 0 ? allResults : null;
  }

  private _buildChunkFilters(
    filters: DateSearchFilters,
    fromDate: Date,
    toDate: Date,
  ): DateSearchFilters[] {
    const chunks: DateSearchFilters[] = [];
    let currentFrom = fromDate;
    let chunkIndex = 0;
    const dayMs = 24 * 60 * 60 * 1000;
    while (currentFrom <= toDate) {
      const endMs = currentFrom.getTime() + (MAX_DAYS_PER_SEARCH - 1) * dayMs;
      const currentTo = new Date(Math.min(endMs, toDate.getTime()));
      const cloned = cloneFilters(filters);
      const shiftDays = MAX_DAYS_PER_SEARCH * chunkIndex;
      if (chunkIndex > 0) {
        for (const segment of cloned.flight_segments) {
          const segDate = parseIsoDate(segment.travel_date);
          segment.travel_date = formatIsoDate(new Date(segDate.getTime() + shiftDays * dayMs));
        }
      }
      cloned.from_date = formatIsoDate(currentFrom);
      cloned.to_date = formatIsoDate(currentTo);
      chunks.push(cloned);
      currentFrom = new Date(currentTo.getTime() + dayMs);
      chunkIndex++;
    }
    return chunks;
  }

  private async _searchChunk(
    filters: DateSearchFilters,
    options: DateSearchOptions,
  ): Promise<DatePrice[] | null> {
    const encoded = filters.encode();
    const url = withLocaleParams(
      BASE_URL,
      options.currency ?? null,
      options.language ?? null,
      options.country ?? null,
    );
    const response = await this.client.post(url, { body: `f.req=${encoded}` });
    const data = parseFirstWrbPayload(response.text);
    if (data == null || !Array.isArray(data)) return null;

    const items = data[data.length - 1];
    if (!Array.isArray(items)) return null;

    const out: DatePrice[] = [];
    for (const item of items) {
      const price = SearchDates._parsePrice(item);
      if (price == null) continue;
      out.push({
        date: SearchDates._parseDate(item, filters.trip_type),
        price,
        currency: SearchDates._parseCurrency(item),
      });
    }
    return out;
  }

  static _parseDate(item: unknown, tripType: TripType): [Date] | [Date, Date] {
    if (!Array.isArray(item)) throw new Error("date item is not an array");
    if (tripType === TripType.ONE_WAY) {
      return [parseIsoDate(item[0] as string)];
    }
    return [parseIsoDate(item[0] as string), parseIsoDate(item[1] as string)];
  }

  static _parsePrice(item: unknown): number | null {
    if (!Array.isArray(item) || item.length <= 2) return null;
    const middle = item[2];
    if (!Array.isArray(middle) || middle.length === 0) return null;
    const inner = middle[0];
    if (!Array.isArray(inner) || inner.length <= 1) return null;
    const raw = inner[1];
    const n = typeof raw === "number" ? raw : Number.parseFloat(raw as string);
    return Number.isFinite(n) ? n : null;
  }

  static _parseCurrency(item: unknown): string | null {
    if (!Array.isArray(item) || item.length <= 2) return null;
    const middle = item[2];
    if (!Array.isArray(middle) || middle.length <= 1) return null;
    try {
      return extractCurrencyFromPriceToken(middle[1] as string);
    } catch {
      return null;
    }
  }
}
