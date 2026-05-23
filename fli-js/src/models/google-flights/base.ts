/**
 * Core data models and enums for the Google Flights API.
 *
 * 1:1 port of fli/models/google_flights/base.py — keeps the same enum
 * integer values (the API uses them on the wire) and the same model field
 * names.
 */

import { z } from "zod";
import { parseIsoDate } from "../../core/dates.ts";
import type { Airline } from "../airline.ts";
import type { Airport } from "../airport.ts";

// ---------------------------------------------------------------------------
// Enums (numeric values must match the Google Flights wire format)
// ---------------------------------------------------------------------------

export const SeatType = {
  ECONOMY: 1,
  PREMIUM_ECONOMY: 2,
  BUSINESS: 3,
  FIRST: 4,
} as const;
export type SeatType = (typeof SeatType)[keyof typeof SeatType];

export const SortBy = {
  TOP_FLIGHTS: 0,
  BEST: 1,
  CHEAPEST: 2,
  DEPARTURE_TIME: 3,
  ARRIVAL_TIME: 4,
  DURATION: 5,
  EMISSIONS: 6,
} as const;
export type SortBy = (typeof SortBy)[keyof typeof SortBy];

export const TripType = {
  ROUND_TRIP: 1,
  ONE_WAY: 2,
  MULTI_CITY: 3,
} as const;
export type TripType = (typeof TripType)[keyof typeof TripType];

export const MaxStops = {
  ANY: 0,
  NON_STOP: 1,
  ONE_STOP_OR_FEWER: 2,
  TWO_OR_FEWER_STOPS: 3,
} as const;
export type MaxStops = (typeof MaxStops)[keyof typeof MaxStops];

export const EmissionsFilter = {
  ALL: 0,
  LESS: 1,
} as const;
export type EmissionsFilter = (typeof EmissionsFilter)[keyof typeof EmissionsFilter];

export const Alliance = {
  ONEWORLD: "ONEWORLD",
  SKYTEAM: "SKYTEAM",
  STAR_ALLIANCE: "STAR_ALLIANCE",
} as const;
export type Alliance = (typeof Alliance)[keyof typeof Alliance];

/**
 * ISO 4217 currency codes supported by Google Flights' `curr=` URL param.
 * Pass any 3-letter ISO 4217 code as a plain string for codes not listed.
 */
export const Currency = {
  AED: "AED",
  ARS: "ARS",
  AUD: "AUD",
  BGN: "BGN",
  BRL: "BRL",
  CAD: "CAD",
  CHF: "CHF",
  CLP: "CLP",
  CNY: "CNY",
  COP: "COP",
  CZK: "CZK",
  DKK: "DKK",
  EGP: "EGP",
  EUR: "EUR",
  GBP: "GBP",
  HKD: "HKD",
  HUF: "HUF",
  IDR: "IDR",
  ILS: "ILS",
  INR: "INR",
  JPY: "JPY",
  KRW: "KRW",
  MXN: "MXN",
  MYR: "MYR",
  NOK: "NOK",
  NZD: "NZD",
  PEN: "PEN",
  PHP: "PHP",
  PLN: "PLN",
  QAR: "QAR",
  RON: "RON",
  SAR: "SAR",
  SEK: "SEK",
  SGD: "SGD",
  THB: "THB",
  TRY: "TRY",
  TWD: "TWD",
  UAH: "UAH",
  USD: "USD",
  VND: "VND",
  ZAR: "ZAR",
} as const;
export type Currency = (typeof Currency)[keyof typeof Currency];

// ---------------------------------------------------------------------------
// Simple value-type models (validated via Zod)
// ---------------------------------------------------------------------------

export const BagsFilterSchema = z.object({
  checked_bags: z.number().int().nonnegative().default(0),
  carry_on: z.boolean().default(false),
});
export type BagsFilter = z.infer<typeof BagsFilterSchema>;

export const TimeRestrictionsSchema = z
  .object({
    earliest_departure: z.number().int().nonnegative().nullable().optional(),
    latest_departure: z.number().int().positive().nullable().optional(),
    earliest_arrival: z.number().int().nonnegative().nullable().optional(),
    latest_arrival: z.number().int().positive().nullable().optional(),
  })
  .transform((v) => {
    // Mirror the Python validator: if earliest > latest, swap.
    const out = { ...v };
    if (
      out.earliest_departure != null &&
      out.latest_departure != null &&
      out.earliest_departure > out.latest_departure
    ) {
      [out.earliest_departure, out.latest_departure] = [
        out.latest_departure,
        out.earliest_departure,
      ];
    }
    if (
      out.earliest_arrival != null &&
      out.latest_arrival != null &&
      out.earliest_arrival > out.latest_arrival
    ) {
      [out.earliest_arrival, out.latest_arrival] = [out.latest_arrival, out.earliest_arrival];
    }
    return out;
  });
export type TimeRestrictions = z.infer<typeof TimeRestrictionsSchema>;

export const PassengerInfoSchema = z.object({
  adults: z.number().int().nonnegative().default(1),
  children: z.number().int().nonnegative().default(0),
  infants_in_seat: z.number().int().nonnegative().default(0),
  infants_on_lap: z.number().int().nonnegative().default(0),
});
export type PassengerInfo = z.infer<typeof PassengerInfoSchema>;

export const PriceLimitSchema = z.object({
  max_price: z.number().int().positive(),
  currency: z.string().nullable().optional(),
});
export type PriceLimit = z.infer<typeof PriceLimitSchema>;

export const LayoverRestrictionsSchema = z.object({
  airports: z.array(z.string()).nullable().optional(),
  min_duration: z.number().int().positive().nullable().optional(),
  max_duration: z.number().int().positive().nullable().optional(),
});
export type LayoverRestrictions = z.infer<typeof LayoverRestrictionsSchema>;

export const AmenitiesSchema = z.object({
  wifi: z.boolean().nullable().optional(),
  power: z.boolean().nullable().optional(),
  usb_power: z.boolean().nullable().optional(),
  in_seat_video: z.boolean().nullable().optional(),
  on_demand_video: z.boolean().nullable().optional(),
  legroom_rating: z.number().int().nonnegative().nullable().optional(),
});
export type Amenities = z.infer<typeof AmenitiesSchema>;

export interface Layover {
  airport: Airport;
  duration: number;
  overnight: boolean;
  change_of_airport: boolean;
  city?: string | null;
  airport_name?: string | null;
}

export interface FlightLeg {
  airline: Airline;
  flight_number: string;
  departure_airport: Airport;
  arrival_airport: Airport;
  departure_datetime: Date;
  arrival_datetime: Date;
  duration: number;
  departure_airport_name?: string | null;
  arrival_airport_name?: string | null;
  operating_airline?: Airline | null;
  operating_flight_number?: string | null;
  aircraft?: string | null;
  legroom?: string | null;
  legroom_short?: string | null;
  amenities?: Amenities | null;
  overnight?: boolean;
  co2_emissions_g?: number | null;
}

export interface BookingOption {
  vendor_code: string | null;
  vendor_name: string | null;
  is_airline_direct: boolean;
  price: number | null;
  currency: string | null;
  fare_name: string | null;
  booking_url: string | null;
  google_click_url: string | null;
  /** [(airline_code, flight_number), ...] */
  flights: Array<[string, string]> | null;
}

export interface FlightResult {
  legs: FlightLeg[];
  /** Price in specified currency. `null` when Google did not surface a price (see Python issue #165). */
  price: number | null;
  currency: string | null;
  /** Total duration in minutes. */
  duration: number;
  stops: number;

  layovers?: Layover[] | null;
  co2_emissions_g?: number | null;
  co2_emissions_typical_g?: number | null;
  co2_emissions_delta_pct?: number | null;
  /** "lower" | "typical" | "higher" */
  emissions_tag?: string | null;
  self_transfer?: boolean | null;
  mixed_cabin?: boolean | null;
  primary_airline?: Airline | null;
  primary_airline_name?: string | null;
  booking_token?: string | null;
}

/** `true` when Google did not surface a price for this row (premium-cabin RT). */
export function priceUnknown(f: FlightResult): boolean {
  return f.price == null;
}

// ---------------------------------------------------------------------------
// FlightSegment — input parameter, validated up front
// ---------------------------------------------------------------------------

/**
 * Airport entry inside a segment's departure/arrival list — `[Airport code, 0]`
 * is the standard shape (the trailing int is unused in current API responses
 * but Google still requires it).
 */
export type AirportEntry = [Airport, number];

export interface FlightSegmentInput {
  departure_airport: AirportEntry[][];
  arrival_airport: AirportEntry[][];
  travel_date: string;
  time_restrictions?: TimeRestrictions | null;
  selected_flight?: FlightResult | null;
}

function todayUtc(): Date {
  const now = new Date();
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
}

export class FlightSegment {
  readonly departure_airport: AirportEntry[][];
  readonly arrival_airport: AirportEntry[][];
  travel_date: string;
  readonly time_restrictions: TimeRestrictions | null;
  selected_flight: FlightResult | null;

  constructor(input: FlightSegmentInput) {
    if (!input.departure_airport?.length || !input.arrival_airport?.length) {
      throw new Error("Both departure and arrival airports must be specified");
    }

    // travel_date must be a valid ISO date and not in the past.
    const travelDate = parseIsoDate(input.travel_date);
    if (travelDate < todayUtc()) {
      throw new Error("Travel date cannot be in the past");
    }

    const depFirst = input.departure_airport[0]?.[0]?.[0];
    const arrFirst = input.arrival_airport[0]?.[0]?.[0];
    if (depFirst && arrFirst && depFirst === arrFirst) {
      throw new Error("Departure and arrival airports must be different");
    }

    this.departure_airport = input.departure_airport;
    this.arrival_airport = input.arrival_airport;
    this.travel_date = input.travel_date;
    this.time_restrictions = input.time_restrictions ?? null;
    this.selected_flight = input.selected_flight ?? null;
  }

  get parsed_travel_date(): Date {
    return parseIsoDate(this.travel_date);
  }
}
