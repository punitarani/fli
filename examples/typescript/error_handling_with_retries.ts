/**
 * Error handling and custom client configuration.
 *
 * The Client already retries transient failures (3 attempts, exponential
 * backoff) and rate-limits to 10 req/s. This shows how to tune it and how
 * to distinguish the typed search errors. Run with:
 *   bun run error_handling_with_retries.ts
 */
import {
  Airport,
  Client,
  type FlightResult,
  FlightSearchFilters,
  FlightSegment,
  SearchClientError,
  SearchConnectionError,
  SearchFlights,
  SearchHTTPError,
  SearchTimeoutError,
} from "fli-js";

function inDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

async function main(): Promise<void> {
  // Tune the client: longer timeout, more retries, optional proxy via env.
  const client = new Client({ timeoutMs: 30_000, retries: 5, backoffMs: 1_000 });

  const filters = new FlightSearchFilters({
    passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
    flight_segments: [
      new FlightSegment({
        departure_airport: [[[Airport.JFK, 0]]],
        arrival_airport: [[[Airport.LAX, 0]]],
        travel_date: inDays(30),
      }),
    ],
  });

  try {
    const results = (await new SearchFlights(client).search(filters)) as FlightResult[] | null;
    console.log(`Found ${results?.length ?? 0} flights.`);
  } catch (err) {
    if (err instanceof SearchTimeoutError) {
      console.error("Request timed out — try raising timeoutMs.");
    } else if (err instanceof SearchConnectionError) {
      console.error("Network/connection problem — check connectivity or proxy.");
    } else if (err instanceof SearchHTTPError) {
      console.error(`Google returned an HTTP error: ${err.message}`);
    } else if (err instanceof SearchClientError) {
      console.error(`Client error: ${err.message}`);
    } else {
      throw err;
    }
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
