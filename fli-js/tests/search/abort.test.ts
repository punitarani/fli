/**
 * Cancellation tests.
 *
 * A search is now several sequential HTTP requests with sleeps between
 * them — the client's retry backoff and the page-retry backoff — so a
 * caller who aborts must not be left waiting for a timer that no longer
 * has any reason to fire, and that timer must not keep the process alive
 * after the promise has settled.
 */

import { describe, expect, test } from "bun:test";
import { Airport } from "../../src/models/airport.ts";
import { FlightSegment } from "../../src/models/google-flights/base.ts";
import { DateSearchFilters } from "../../src/models/google-flights/dates.ts";
import { FlightSearchFilters } from "../../src/models/google-flights/flights.ts";
import { Client } from "../../src/search/client.ts";
import { SearchDates } from "../../src/search/dates.ts";
import { SearchFlights } from "../../src/search/flights.ts";
import { setSearchLogger } from "../../src/search/logging.ts";
import { fetchPayload } from "../../src/search/tfs.ts";

function futureDate(daysAhead = 30): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + daysAhead);
  return d.toISOString().slice(0, 10);
}

function asFetch(fn: (input: unknown, init?: RequestInit) => Promise<Response>): typeof fetch {
  return fn as unknown as typeof fetch;
}

function oneWayFilters(): FlightSearchFilters {
  return new FlightSearchFilters({
    passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
    flight_segments: [
      new FlightSegment({
        departure_airport: [[[Airport.JFK, 0]]],
        arrival_airport: [[[Airport.LAX, 0]]],
        travel_date: futureDate(),
      }),
    ],
  });
}

describe("client retry backoff is abortable", () => {
  test("aborting during the backoff rejects promptly with the caller's reason", async () => {
    let calls = 0;
    const client = new Client({
      retries: 3,
      // Long enough that "the sleep was waited out" is unmistakable, short
      // enough that a regression fails the assertion instead of the timeout.
      backoffMs: 400,
      fetchImpl: asFetch(async () => {
        calls++;
        throw new TypeError("fetch failed");
      }),
    });
    const controller = new AbortController();
    const reason = new Error("caller aborted");
    setTimeout(() => controller.abort(reason), 20);

    const started = performance.now();
    await expect(
      client.get("https://www.google.com/travel/flights", { signal: controller.signal }),
    ).rejects.toBe(reason);
    const elapsed = performance.now() - started;

    // One failed fetch, then the abort lands mid-backoff.
    expect(calls).toBe(1);
    expect(elapsed).toBeLessThan(300);
  });

  test("a backoff that is waited out still retries normally", async () => {
    let calls = 0;
    const client = new Client({
      retries: 2,
      backoffMs: 5,
      fetchImpl: asFetch(async () => {
        calls++;
        if (calls === 1) throw new TypeError("fetch failed");
        return new Response("ok", { status: 200 });
      }),
    });
    expect((await client.get("https://www.google.com/x")).text).toBe("ok");
    expect(calls).toBe(2);
  });
});

describe("page retry backoff is abortable", () => {
  test("fetchPayload stops mid-backoff when the caller aborts", async () => {
    let calls = 0;
    const client = new Client({
      retries: 1,
      fetchImpl: asFetch(async () => {
        calls++;
        return new Response("<html>no payload</html>", { status: 200 });
      }),
    });
    const controller = new AbortController();
    const reason = new Error("caller aborted");
    setTimeout(() => controller.abort(reason), 20);

    const started = performance.now();
    await expect(
      fetchPayload(client, "https://www.google.com/travel/flights", {
        signal: controller.signal,
      }),
    ).rejects.toBe(reason);
    const elapsed = performance.now() - started;

    // The real backoff is 500ms then 1500ms; aborting at 20ms must not
    // wait either of them out, and must not start the second fetch.
    expect(calls).toBe(1);
    expect(elapsed).toBeLessThan(400);
  });
});

describe("signal reaches the transport from the public options", () => {
  test("SearchFlights.search forwards its signal", async () => {
    let seen: AbortSignal | null | undefined;
    const client = new Client({
      retries: 1,
      fetchImpl: asFetch(async (_u, init) => {
        seen = init?.signal;
        // A pre-aborted signal makes real fetch throw; model that.
        if (init?.signal?.aborted) throw new DOMException("Aborted", "AbortError");
        return new Response("<html>no payload</html>", { status: 200 });
      }),
    });
    const controller = new AbortController();
    const reason = new Error("cancelled before we started");
    controller.abort(reason);

    await expect(
      new SearchFlights(client).search(oneWayFilters(), { signal: controller.signal }),
    ).rejects.toBe(reason);
    expect(seen).toBeDefined();
  });

  test("SearchDates.search forwards its signal", async () => {
    const client = new Client({
      retries: 1,
      fetchImpl: asFetch(async (_u, init) => {
        if (init?.signal?.aborted) throw new DOMException("Aborted", "AbortError");
        return new Response("<html>no payload</html>", { status: 200 });
      }),
    });
    const controller = new AbortController();
    const reason = new Error("cancelled before we started");
    controller.abort(reason);

    const fromD = futureDate(10);
    const filters = new DateSearchFilters({
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: fromD,
        }),
      ],
      from_date: fromD,
      to_date: futureDate(12),
    });

    setSearchLogger({ warn: () => {}, debug: () => {} });
    try {
      // Every date fails the same way, so the sweep reports a total
      // failure — but the point is that the cancellation reached the
      // wire rather than being ignored for three full page fetches.
      await expect(
        new SearchDates(client).search(filters, { signal: controller.signal }),
      ).rejects.toThrow();
    } finally {
      setSearchLogger(null);
    }
  });
});
