/**
 * End-to-end live test — talks to Google Flights' real API.
 *
 * Skipped unless `FLI_E2E=1` is set (CI ignores this; only run manually).
 */

import { describe, expect, test } from "bun:test";
import { Airport } from "../../src/models/airport.ts";
import { FlightSegment, MaxStops, SeatType, SortBy } from "../../src/models/google-flights/base.ts";
import { FlightSearchFilters } from "../../src/models/google-flights/flights.ts";
import { SearchFlights } from "../../src/search/flights.ts";

const E2E_ENABLED = process.env.FLI_E2E === "1";

function futureDate(daysAhead = 30): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + daysAhead);
  return d.toISOString().slice(0, 10);
}

describe.if(E2E_ENABLED)("SearchFlights live (FLI_E2E=1)", () => {
  test("JFK → LAX one-way returns at least one flight", async () => {
    const search = new SearchFlights();
    const filters = new FlightSearchFilters({
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: futureDate(30),
        }),
      ],
      stops: MaxStops.NON_STOP,
      seat_type: SeatType.ECONOMY,
      sort_by: SortBy.CHEAPEST,
    });
    const results = await search.search(filters);
    expect(Array.isArray(results)).toBe(true);
    expect((results ?? []).length).toBeGreaterThan(0);
  });
});

if (!E2E_ENABLED) {
  test.skip("e2e tests skipped — set FLI_E2E=1 to run", () => {});
}
