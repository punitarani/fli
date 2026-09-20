/**
 * FlightSearchFilters — produces the nested-list payload Google's
 * FlightsFrontendService.GetShoppingResults endpoint expects.
 *
 * 1:1 port of fli/models/google_flights/flights.py — the formatted output
 * must remain byte-identical to the Python implementation (see
 * tests/integration/test_filter_format_snapshots.test.ts).
 */

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
  SortBy,
  TripType,
} from "./base.ts";

function airlineSortKey(a: Airline): string {
  // Match Python's `sorted(airlines, key=lambda x: x.value)` — Python's
  // Airline.X.value is the human-readable name. In TS the const value is
  // the code; look up the name via AIRLINE_NAMES so encoding stays
  // byte-identical to the Python upstream.
  const code = serializeCode(a);
  return AIRLINE_NAMES[code] ?? code;
}

export interface FlightSearchFiltersInput {
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
  sort_by?: SortBy;
  exclude_basic_economy?: boolean;
  emissions?: EmissionsFilter;
  bags?: BagsFilter | null;
  show_all_results?: boolean;
}

function serializeCode(code: string): string {
  // Strip the leading "_" used to make digit-prefixed IATA codes valid
  // identifiers in the Airline / Airport const objects.
  return code.startsWith("_") ? code.slice(1) : code;
}

export class FlightSearchFilters {
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
  sort_by: SortBy;
  exclude_basic_economy: boolean;
  emissions: EmissionsFilter;
  bags: BagsFilter | null;
  show_all_results: boolean;

  constructor(input: FlightSearchFiltersInput) {
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
    this.sort_by = input.sort_by ?? SortBy.BEST;
    this.exclude_basic_economy = input.exclude_basic_economy ?? false;
    this.emissions = input.emissions ?? EmissionsFilter.ALL;
    this.bags = input.bags ?? null;
    this.show_all_results = input.show_all_results ?? true;
  }

  /**
   * Render the nested-list payload Google's GetShoppingResults RPC accepts.
   * See the position map in the upstream Python flights.py.
   */
  format(): unknown[] {
    const formattedSegments: unknown[] = [];
    for (let segIdx = 0; segIdx < this.flight_segments.length; segIdx++) {
      const segment = this.flight_segments[segIdx];
      if (!segment) continue;

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

      // Include list — airline codes (sorted) then alliance strings (sorted).
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

      // selected_flight encoding (for round-trip / multi-city expansion calls).
      let selectedFlights: unknown[] | null = null;
      const isMultiLeg =
        this.trip_type === TripType.ROUND_TRIP || this.trip_type === TripType.MULTI_CITY;
      if (isMultiLeg && segment.selected_flight != null) {
        selectedFlights = segment.selected_flight.legs.map((leg) => [
          serializeCode(leg.departure_airport),
          formatDateOnly(leg.departure_datetime),
          serializeCode(leg.arrival_airport),
          null,
          serializeCode(leg.airline),
          leg.flight_number,
        ]);
      }

      const emissionsFilter: number[] | null =
        this.emissions !== EmissionsFilter.ALL ? [this.emissions] : null;

      // 3 = outbound (or only leg), 1 = return (second leg of round-trip).
      const isReturn = this.trip_type === TripType.ROUND_TRIP && segIdx > 0;
      const classifier = isReturn ? 1 : 3;

      formattedSegments.push([
        departureBlock[0], // 0: departure airports
        arrivalBlock[0], // 1: arrival airports
        timeFilters, // 2: [edep, ldep, earr, larr]
        this.stops, // 3: stops int
        airlinesFilters, // 4: include list
        excludeFilters, // 5: exclude list
        segment.travel_date, // 6: travel date
        this.max_duration != null ? [this.max_duration] : null, // 7
        selectedFlights, // 8: selected flight (next-leg fetch)
        layoverAirports, // 9
        null, // 10
        layoverMin, // 11
        layoverMax, // 12
        emissionsFilter, // 13
        classifier, // 14
      ]);
    }

    const bagsFilter: [number, number] | null = this.bags
      ? [this.bags.checked_bags, this.bags.carry_on ? 1 : 0]
      : null;

    return [
      [], // outer[0]
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
        formattedSegments, // [13]
        null, // [14]
        null, // [15]
        null, // [16]
        1, // [17]
        null, // [18]
        null, // [19]
        null, // [20]
        null, // [21]
        null, // [22]
        null, // [23]
        null, // [24]
        null, // [25]
        null, // [26]
        null, // [27]
        this.exclude_basic_economy ? 1 : 0, // [28]
      ],
      this.sort_by, // outer[2]
      this.show_all_results ? 1 : 0, // outer[3]
      0, // outer[4]
      1, // outer[5]
    ];
  }

  /** URL-encode the formatted filters into the `f.req` body. */
  encode(): string {
    const formatted = this.format();
    const formattedJson = JSON.stringify(formatted);
    const wrapped: unknown[] = [null, formattedJson];
    return encodeURIComponent(JSON.stringify(wrapped));
  }
}

function formatDateOnly(d: Date): string {
  // Use local-time getters: `parseDateTime` in decoders.ts constructs
  // `Date` via the local-time `new Date(y, m-1, d, h, min)` form, so the
  // local components are what represent the flight's actual departure
  // date. Reading back with `getUTC*` would shift the date by ±1 day for
  // any caller not in UTC, sending the wrong day to Google's return-leg
  // lookup.
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
