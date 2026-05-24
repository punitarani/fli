/**
 * Find the cheapest dates to fly within a range.
 *
 * Mirrors examples/python/date_range_search.py. SearchDates returns a
 * DatePrice[] where `date` is a tuple of Date objects ([outbound] for
 * one-way, [outbound, return] for round trips). Run with:
 *   bun run date_range_search.ts
 */
import { Airport, DateSearchFilters, FlightSegment, SearchDates } from "fli-js";

function inDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

async function main(): Promise<void> {
  const filters = new DateSearchFilters({
    passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
    flight_segments: [
      new FlightSegment({
        departure_airport: [[[Airport.JFK, 0]]],
        arrival_airport: [[[Airport.LAX, 0]]],
        travel_date: inDays(30),
      }),
    ],
    from_date: inDays(30),
    to_date: inDays(60),
  });

  const dates = await new SearchDates().search(filters, { currency: "USD" });

  if (!dates?.length) {
    console.log("No priced dates found.");
    return;
  }

  const cheapest = [...dates].sort((a, b) => a.price - b.price).slice(0, 10);
  console.log("Cheapest dates:");
  for (const { date, price } of cheapest) {
    console.log(`  ${date[0].toISOString().slice(0, 10)}  $${price}`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
