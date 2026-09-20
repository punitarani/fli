/**
 * Round-trip flight search.
 *
 * Mirrors examples/python/round_trip_search.py. Round-trip and multi-city
 * searches return an array of itineraries, each itinerary being an array of
 * FlightResult — one per leg, in order. Run with:
 *   bun run round_trip_search.ts
 */
import {
  Airport,
  type FlightResult,
  FlightSearchFilters,
  FlightSegment,
  SearchFlights,
  TripType,
} from "fli-js";

function inDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

async function main(): Promise<void> {
  const filters = new FlightSearchFilters({
    trip_type: TripType.ROUND_TRIP,
    passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
    flight_segments: [
      new FlightSegment({
        departure_airport: [[[Airport.JFK, 0]]],
        arrival_airport: [[[Airport.LAX, 0]]],
        travel_date: inDays(30),
      }),
      new FlightSegment({
        departure_airport: [[[Airport.LAX, 0]]],
        arrival_airport: [[[Airport.JFK, 0]]],
        travel_date: inDays(37),
      }),
    ],
  });

  const itineraries = (await new SearchFlights().search(filters, { topN: 5 })) as
    | FlightResult[][]
    | null;

  if (!itineraries?.length) {
    console.log("No itineraries found.");
    return;
  }

  for (const [outbound, ret] of itineraries) {
    console.log(`Total: $${outbound.price ?? "N/A"}`);
    for (const [label, flight] of [
      ["Outbound", outbound],
      ["Return", ret],
    ] as const) {
      console.log(`  ${label}:`);
      for (const leg of flight.legs) {
        console.log(
          `    ${leg.airline} ${leg.flight_number}  ` +
            `${leg.departure_datetime.toISOString()} -> ${leg.arrival_datetime.toISOString()}`,
        );
      }
    }
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
