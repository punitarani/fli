/**
 * Basic one-way flight search.
 *
 * Mirrors examples/python/basic_one_way_search.py. Run with:
 *   bun run basic_one_way_search.ts
 */
import {
  Airport,
  type FlightResult,
  FlightSearchFilters,
  FlightSegment,
  MaxStops,
  SearchFlights,
  SeatType,
  SortBy,
} from "fli-js";

function inDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

async function main(): Promise<void> {
  const filters = new FlightSearchFilters({
    passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
    flight_segments: [
      new FlightSegment({
        departure_airport: [[[Airport.JFK, 0]]],
        arrival_airport: [[[Airport.LAX, 0]]],
        travel_date: inDays(30),
      }),
    ],
    seat_type: SeatType.ECONOMY,
    stops: MaxStops.NON_STOP,
    sort_by: SortBy.CHEAPEST,
  });

  const results = (await new SearchFlights().search(filters, { currency: "USD" })) as
    | FlightResult[]
    | null;

  if (!results?.length) {
    console.log("No flights found.");
    return;
  }

  for (const flight of results) {
    console.log(
      `Price: $${flight.price ?? "N/A"}  Duration: ${flight.duration} min  Stops: ${flight.stops}`,
    );
    for (const leg of flight.legs) {
      console.log(
        `  ${leg.airline} ${leg.flight_number}: ` +
          `${leg.departure_airport} ${leg.departure_datetime.toISOString()} -> ` +
          `${leg.arrival_airport} ${leg.arrival_datetime.toISOString()}`,
      );
    }
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
