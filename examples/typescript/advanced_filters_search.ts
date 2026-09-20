/**
 * Advanced filtering: alliances, exclusions, layovers, and locale.
 *
 * Mirrors examples/python/advanced_filters_search.py. Currency, language,
 * and country are passed to search() (Google's curr / hl / gl params), not
 * to the filter object. Run with:
 *   bun run advanced_filters_search.ts
 */
import {
  Airline,
  Airport,
  Alliance,
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
        arrival_airport: [[[Airport.NRT, 0]]],
        travel_date: inDays(45),
      }),
    ],
    seat_type: SeatType.BUSINESS,
    stops: MaxStops.ONE_STOP_OR_FEWER,
    alliances: [Alliance.ONEWORLD], // only Oneworld carriers...
    airlines_exclude: [Airline.AA], // ...but skip American
    layover_restrictions: { airports: null, min_duration: 60, max_duration: 240 },
    max_duration: 1200, // 20 hours, in minutes
    sort_by: SortBy.DURATION,
  });

  const flights = (await new SearchFlights().search(filters, {
    currency: "EUR",
    language: "en-GB",
    country: "GB",
  })) as FlightResult[] | null;

  if (!flights?.length) {
    console.log("No flights matched the filters.");
    return;
  }

  console.log(`Found ${flights.length} flights (prices in EUR):`);
  for (const flight of flights.slice(0, 10)) {
    const carriers = [...new Set(flight.legs.map((l) => l.airline))].sort().join(" / ");
    console.log(
      `  EUR ${flight.price ?? "N/A"}  ${flight.duration} min  ${flight.stops} stop(s)  via ${carriers}`,
    );
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
