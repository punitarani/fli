/**
 * DateSearchFilters — payload for Google Flights' GetCalendarGraph endpoint.
 *
 * 1:1 port of fli/models/google_flights/dates.py.
 */

import { formatIsoDate, parseIsoDate } from "../../core/dates.ts";
import { AIRLINE_NAMES, type Airline } from "../airline.ts";
import {
  type Alliance,
  type BagsFilter,
  EmissionsFilter,
  type FlightSegment,
  type LayoverRestrictions,
  MaxStops,
  type PassengerInfo,
  type PriceLimit,
  SeatType,
  TripType,
} from "./base.ts";

const MAX_PAST_FROM_DATE_DAYS = 6;

function airlineSortKey(a: Airline): string {
  const code = a.startsWith("_") ? a.slice(1) : a;
  return AIRLINE_NAMES[code] ?? code;
}

function serializeCode(code: string): string {
  return code.startsWith("_") ? code.slice(1) : code;
}

function todayUtc(): Date {
  const now = new Date();
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
}

export interface DateSearchFiltersInput {
  trip_type?: TripType;
  passenger_info: PassengerInfo;
  flight_segments: FlightSegment[];
  stops?: MaxStops;
  seat_type?: SeatType;
  price_limit?: PriceLimit | null;
  airlines?: Airline[] | null;
  airlines_exclude?: Airline[] | null;
  alliances?: Alliance[] | null;
  alliances_exclude?: Alliance[] | null;
  max_duration?: number | null;
  layover_restrictions?: LayoverRestrictions | null;
  emissions?: EmissionsFilter;
  bags?: BagsFilter | null;
  from_date: string;
  to_date: string;
  duration?: number | null;
}

export class DateSearchFilters {
  trip_type: TripType;
  passenger_info: PassengerInfo;
  flight_segments: FlightSegment[];
  stops: MaxStops;
  seat_type: SeatType;
  price_limit: PriceLimit | null;
  airlines: Airline[] | null;
  airlines_exclude: Airline[] | null;
  alliances: Alliance[] | null;
  alliances_exclude: Alliance[] | null;
  max_duration: number | null;
  layover_restrictions: LayoverRestrictions | null;
  emissions: EmissionsFilter;
  bags: BagsFilter | null;
  from_date: string;
  to_date: string;
  duration: number | null;

  constructor(input: DateSearchFiltersInput) {
    this.trip_type = input.trip_type ?? TripType.ONE_WAY;
    this.passenger_info = input.passenger_info;
    this.flight_segments = input.flight_segments;
    this.stops = input.stops ?? MaxStops.ANY;
    this.seat_type = input.seat_type ?? SeatType.ECONOMY;
    this.price_limit = input.price_limit ?? null;
    this.airlines = input.airlines ?? null;
    this.airlines_exclude = input.airlines_exclude ?? null;
    this.alliances = input.alliances ?? null;
    this.alliances_exclude = input.alliances_exclude ?? null;
    this.max_duration = input.max_duration ?? null;
    this.layover_restrictions = input.layover_restrictions ?? null;
    this.emissions = input.emissions ?? EmissionsFilter.ALL;
    this.bags = input.bags ?? null;
    this.duration = input.duration ?? null;

    // Validate / coerce the date range.
    let { from_date, to_date } = input;

    // Trip-type-specific segment-count validation.
    if (this.trip_type === TripType.ONE_WAY && this.flight_segments.length !== 1) {
      throw new Error("One-way trip must have one flight segment");
    }
    if (this.trip_type === TripType.ROUND_TRIP && this.flight_segments.length !== 2) {
      throw new Error("Round trip must have two flight segments");
    }
    if (this.trip_type === TripType.ROUND_TRIP && this.duration == null) {
      throw new Error("Duration must be set for round trip flights");
    }
    if (this.duration != null && this.flight_segments.length === 2) {
      const a = this.flight_segments[0]?.parsed_travel_date.getTime() ?? 0;
      const b = this.flight_segments[1]?.parsed_travel_date.getTime() ?? 0;
      const diffDays = Math.round((b - a) / (1000 * 60 * 60 * 24));
      if (diffDays !== this.duration) {
        throw new Error("Flight segments travel dates difference must match duration");
      }
    }

    // Swap from/to if from > to (mirrors the Python validator).
    const fromDate = parseIsoDate(from_date);
    const toDate = parseIsoDate(to_date);
    if (fromDate > toDate) {
      const swappedFrom = formatIsoDate(toDate);
      const swappedTo = formatIsoDate(fromDate);
      from_date = swappedFrom;
      to_date = swappedTo;
    }

    // to_date must be strictly in the future.
    const today = todayUtc();
    if (parseIsoDate(to_date) <= today) {
      throw new Error("To date must be in the future");
    }

    // If from_date is more than MAX_PAST_FROM_DATE_DAYS in the past, snap to today.
    const fromParsed = parseIsoDate(from_date);
    if (fromParsed < today) {
      const deltaDays = Math.round(
        (today.getTime() - fromParsed.getTime()) / (1000 * 60 * 60 * 24),
      );
      if (deltaDays > MAX_PAST_FROM_DATE_DAYS) {
        from_date = formatIsoDate(today);
      }
    }

    this.from_date = from_date;
    this.to_date = to_date;
  }

  get parsed_from_date(): Date {
    return parseIsoDate(this.from_date);
  }

  get parsed_to_date(): Date {
    return parseIsoDate(this.to_date);
  }

  format(): unknown[] {
    const formattedSegments: unknown[] = [];
    for (const segment of this.flight_segments) {
      const departureBlock = [
        segment.departure_airport.map((airports) =>
          airports.map((airport) => [serializeCode(airport[0]), airport[1]]),
        ),
      ];
      const arrivalBlock = [
        segment.arrival_airport.map((airports) =>
          airports.map((airport) => [serializeCode(airport[0]), airport[1]]),
        ),
      ];

      const tr = segment.time_restrictions;
      const timeFilters: Array<number | null | undefined> | null = tr
        ? [
            tr.earliest_departure ?? null,
            tr.latest_departure ?? null,
            tr.earliest_arrival ?? null,
            tr.latest_arrival ?? null,
          ]
        : null;

      const includeTokens: string[] = [];
      if (this.airlines?.length) {
        const sorted = [...this.airlines].sort((a, b) => {
          const ka = airlineSortKey(a);
          const kb = airlineSortKey(b);
          return ka < kb ? -1 : ka > kb ? 1 : 0;
        });
        for (const a of sorted) includeTokens.push(serializeCode(a));
      }
      if (this.alliances?.length) {
        for (const a of [...this.alliances].sort()) includeTokens.push(a);
      }
      const airlinesFilters: string[] | null = includeTokens.length ? includeTokens : null;

      const excludeTokens: string[] = [];
      if (this.airlines_exclude?.length) {
        const sorted = [...this.airlines_exclude].sort((a, b) => {
          const ka = airlineSortKey(a);
          const kb = airlineSortKey(b);
          return ka < kb ? -1 : ka > kb ? 1 : 0;
        });
        for (const a of sorted) excludeTokens.push(serializeCode(a));
      }
      if (this.alliances_exclude?.length) {
        for (const a of [...this.alliances_exclude].sort()) excludeTokens.push(a);
      }
      const excludeFilters: string[] | null = excludeTokens.length ? excludeTokens : null;

      const layoverAirports = this.layover_restrictions?.airports?.length
        ? this.layover_restrictions.airports.map(serializeCode)
        : null;
      const layoverMin = this.layover_restrictions?.min_duration ?? null;
      const layoverMax = this.layover_restrictions?.max_duration ?? null;

      const emissionsFilter: number[] | null =
        this.emissions !== EmissionsFilter.ALL ? [this.emissions] : null;

      formattedSegments.push([
        departureBlock[0],
        arrivalBlock[0],
        timeFilters,
        this.stops,
        airlinesFilters,
        excludeFilters,
        segment.travel_date,
        this.max_duration != null ? [this.max_duration] : null,
        null, // 8: selected flight (unused in date search)
        layoverAirports,
        null,
        layoverMin,
        layoverMax,
        emissionsFilter,
        3, // 14: hardcoded
      ]);
    }

    const bagsFilter: [number, number] | null = this.bags
      ? [this.bags.checked_bags, this.bags.carry_on ? 1 : 0]
      : null;

    const base: unknown[] = [
      null,
      [
        null, // [0]
        null, // [1]
        this.trip_type, // [2]
        null, // [3]
        [], // [4]
        this.seat_type, // [5]
        [
          this.passenger_info.adults,
          this.passenger_info.children,
          this.passenger_info.infants_on_lap,
          this.passenger_info.infants_in_seat,
        ], // [6]
        this.price_limit ? [null, this.price_limit.max_price] : null, // [7]
        null, // [8]
        null, // [9]
        bagsFilter, // [10]
        null, // [11]
        null, // [12]
        formattedSegments,
        null, // [14]
        null, // [15]
        null, // [16]
        1, // [17]
      ],
      [this.from_date, this.to_date],
    ];

    if (this.trip_type === TripType.ROUND_TRIP) {
      base.push(null, [this.duration, this.duration]);
    }

    return base;
  }

  encode(): string {
    const formatted = this.format();
    const formattedJson = JSON.stringify(formatted);
    const wrapped: unknown[] = [null, formattedJson];
    return encodeURIComponent(JSON.stringify(wrapped));
  }
}
