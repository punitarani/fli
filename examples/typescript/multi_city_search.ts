/**
 * Multi-city itinerary search (three legs on different dates).
 *
 * Mirrors examples/python/multi_city_search.py. Results come back as an
 * array of itineraries, each itinerary an array of FlightResult — one per
 * leg, in order. Run with:
 *   bun run multi_city_search.ts
 */
import {
  Airport,
  type FlightResult,
  FlightSearchFilters,
  FlightSegment,
  SeatType,
  SearchFlights,
  TripType,
} from "fli-js";

function inDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function leg(from: Airport, to: Airport, dayOffset: number): FlightSegment {
  return new FlightSegment({
    departure_airport: [[[from, 0]]],
    arrival_airport: [[[to, 0]]],
    travel_date: inDays(30 + dayOffset),
  });
}

async function main(): Promise<void> {
  const filters = new FlightSearchFilters({
    trip_type: TripType.MULTI_CITY,
    passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
    flight_segments: [
      leg(Airport.JFK, Airport.LHR, 0),
      leg(Airport.LHR, Airport.CDG, 4),
      leg(Airport.CDG, Airport.JFK, 7),
    ],
    seat_type: SeatType.ECONOMY,
  });

  const itineraries = (await new SearchFlights().search(filters, { topN: 3 })) as
    | FlightResult[][]
    | null;

  if (!itineraries?.length) {
    console.log("No itineraries found.");
    return;
  }

  itineraries.forEach((legs, i) => {
    const total = legs.reduce((sum, l) => sum + (l.price ?? 0), 0);
    console.log(`Itinerary ${i + 1} — total $${total.toFixed(0)}`);
    for (const segment of legs) {
      const first = segment.legs[0];
      const last = segment.legs[segment.legs.length - 1];
      console.log(
        `  ${first.departure_airport} -> ${last.arrival_airport}  ` +
          `$${segment.price ?? "N/A"}  ${segment.duration} min  ${segment.stops} stop(s)`,
      );
    }
  });
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
