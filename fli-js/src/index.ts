/**
 * fli — TypeScript port of the Python fli library.
 *
 * Programmatic access to Google Flights data through direct
 * (reverse-engineered) API interaction. No HTML scraping.
 *
 * @example
 * ```ts
 * import { SearchFlights, FlightSearchFilters, PassengerInfo, FlightSegment, Airport, SeatType } from "fli";
 *
 * const filters = new FlightSearchFilters({
 *   passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
 *   flight_segments: [
 *     new FlightSegment({
 *       departure_airport: [[[Airport.JFK, 0]]],
 *       arrival_airport: [[[Airport.LAX, 0]]],
 *       travel_date: "2026-12-25",
 *     }),
 *   ],
 *   seat_type: SeatType.ECONOMY,
 * });
 *
 * const search = new SearchFlights();
 * const results = await search.search(filters, { currency: "USD" });
 * ```
 */

export * from "./core/index.ts";
export * from "./models/index.ts";
export * from "./search/index.ts";
