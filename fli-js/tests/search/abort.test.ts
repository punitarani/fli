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
import { FlightSegment, TripType } from "../../src/models/google-flights/base.ts";
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

/** A rendered search page carrying exactly one parseable flight row. */
function pageWithOneFlight(): string {
  const leg: unknown[] = [
    "AA",
    null,
    null,
    "JFK",
    null,
    null,
    "LAX",
    null,
    [12, 30],
    null,
    [16, 45],
    375,
    null,
    null,
    null,
    null,
    null,
    "Boeing 737",
    null,
    false,
    [2026, 12, 25],
    [2026, 12, 25],
    ["AA", "100"],
  ];
  while (leg.length < 32) leg.push(null);
  const detail: unknown[] = Array.from({ length: 25 }, () => null);
  detail[0] = "AA";
  detail[1] = ["American Airlines"];
  detail[2] = [leg];
  detail[9] = 375;
  const row: unknown[] = Array.from({ length: 11 }, () => null);
  row[0] = detail;
  row[1] = [[null, 199.99], null];
  const payload: unknown[] = [[null, null, null, null, "sid"], null, [[row]], [[]]];
  return `<script>AF_initDataCallback({key: 'ds:1', hash: '1', data:${JSON.stringify(payload)}, sideChannel: {}});</script>`;
}

/** Date filters covering `days` dates starting 10 days out. */
function sweepFilters(days: number): DateSearchFilters {
  const fromD = futureDate(10);
  return new DateSearchFilters({
    passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
    flight_segments: [
      new FlightSegment({
        departure_airport: [[[Airport.JFK, 0]]],
        arrival_airport: [[[Airport.LAX, 0]]],
        travel_date: fromD,
      }),
    ],
    from_date: fromD,
    to_date: futureDate(10 + days - 1),
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
  test("SearchFlights.search puts its signal on the wire", async () => {
    // Aborted once the first fetch is under way, so the signal must have
    // reached `fetchImpl` for the request to notice at all.
    let seen: AbortSignal | null | undefined;
    const controller = new AbortController();
    const reason = new Error("cancelled mid-flight");
    const client = new Client({
      retries: 1,
      fetchImpl: asFetch(async (_u, init) => {
        seen = init?.signal;
        controller.abort(reason);
        throw new DOMException("Aborted", "AbortError");
      }),
    });

    await expect(
      new SearchFlights(client).search(oneWayFilters(), { signal: controller.signal }),
    ).rejects.toBe(reason);
    expect(seen).toBeDefined();
    expect(seen?.aborted).toBe(true);
  });

  test("SearchDates.search puts its signal on the wire", async () => {
    let seen: AbortSignal | null | undefined;
    const controller = new AbortController();
    const reason = new Error("cancelled mid-sweep");
    const client = new Client({
      retries: 1,
      callsPerSecond: 10_000,
      fetchImpl: asFetch(async (_u, init) => {
        seen = init?.signal;
        controller.abort(reason);
        throw new DOMException("Aborted", "AbortError");
      }),
    });

    setSearchLogger({ warn: () => {}, debug: () => {} });
    try {
      await expect(
        new SearchDates(client).search(sweepFilters(3), { signal: controller.signal }),
      ).rejects.toBe(reason);
    } finally {
      setSearchLogger(null);
    }
    expect(seen).toBeDefined();
    expect(seen?.aborted).toBe(true);
  });
});

describe("a pre-aborted signal costs nothing at all", () => {
  // Real `fetch` rejects a pre-aborted signal without touching the
  // network, but a custom `fetchImpl` is under no such obligation — and
  // taking a rate-limiter token for a request that will never be made
  // delays the next real one.
  function countingClient(): { client: Client; calls: () => number } {
    let calls = 0;
    const client = new Client({
      retries: 3,
      backoffMs: 1,
      fetchImpl: asFetch(async () => {
        calls++;
        return new Response("<html>no payload</html>", { status: 200 });
      }),
    });
    return { client, calls: () => calls };
  }

  function preAborted(): { signal: AbortSignal; reason: Error } {
    const controller = new AbortController();
    const reason = new Error("cancelled before we started");
    controller.abort(reason);
    return { signal: controller.signal, reason };
  }

  test("Client.get makes no call", async () => {
    const { client, calls } = countingClient();
    const { signal, reason } = preAborted();
    await expect(client.get("https://www.google.com/x", { signal })).rejects.toBe(reason);
    expect(calls()).toBe(0);
  });

  test("Client.post makes no call", async () => {
    const { client, calls } = countingClient();
    const { signal, reason } = preAborted();
    await expect(client.post("https://www.google.com/x", { body: "", signal })).rejects.toBe(
      reason,
    );
    expect(calls()).toBe(0);
  });

  test("fetchPayload makes no call", async () => {
    const { client, calls } = countingClient();
    const { signal, reason } = preAborted();
    await expect(
      fetchPayload(client, "https://www.google.com/travel/flights", { signal }),
    ).rejects.toBe(reason);
    expect(calls()).toBe(0);
  });

  test("SearchFlights.search makes no call", async () => {
    const { client, calls } = countingClient();
    const { signal, reason } = preAborted();
    await expect(new SearchFlights(client).search(oneWayFilters(), { signal })).rejects.toBe(
      reason,
    );
    expect(calls()).toBe(0);
  });

  test("SearchDates.search makes no call", async () => {
    const { client, calls } = countingClient();
    const { signal, reason } = preAborted();
    await expect(new SearchDates(client).search(sweepFilters(40), { signal })).rejects.toBe(reason);
    expect(calls()).toBe(0);
  });
});

describe("aborting a date sweep stops it and rejects", () => {
  test("a 93-date sweep aborted early rejects with the caller's reason", async () => {
    // Measured before this was fixed: all 93 slots ran, the sweep took
    // 8.3s, and it RESOLVED with 10 partial dates — a silently truncated
    // answer, which is the failure class this transport exists to remove.
    let calls = 0;
    let inFlight = 0;
    const client = new Client({
      retries: 1,
      backoffMs: 1,
      callsPerSecond: 10_000,
      fetchImpl: asFetch(async () => {
        calls++;
        inFlight++;
        try {
          await new Promise((r) => setTimeout(r, 30));
          return new Response(pageWithOneFlight(), { status: 200 });
        } finally {
          inFlight--;
        }
      }),
    });

    const controller = new AbortController();
    const reason = new Error("caller aborted the sweep");
    setTimeout(() => controller.abort(reason), 20);

    setSearchLogger({ warn: () => {}, debug: () => {} });
    const started = performance.now();
    try {
      await expect(
        new SearchDates(client).search(sweepFilters(93), { signal: controller.signal }),
      ).rejects.toBe(reason);
    } finally {
      setSearchLogger(null);
    }
    const elapsed = performance.now() - started;

    // No further date is started once the signal fires: only the batch
    // already in flight (≤ 10 workers) ever reached the network.
    expect(calls).toBeLessThanOrEqual(20);
    expect(elapsed).toBeLessThan(1_000);
    expect(inFlight).toBe(0);
  });

  test("an aborted sweep never returns partial results", async () => {
    // Let a few dates succeed before aborting: the sweep now has real
    // prices in hand and must still reject rather than hand back a
    // truncated answer the caller has no way to recognise as truncated.
    let calls = 0;
    const controller = new AbortController();
    const reason = new Error("aborted after some dates priced");
    const client = new Client({
      retries: 1,
      backoffMs: 1,
      callsPerSecond: 10_000,
      fetchImpl: asFetch(async () => {
        calls++;
        if (calls === 12) controller.abort(reason);
        return new Response(pageWithOneFlight(), { status: 200 });
      }),
    });

    setSearchLogger({ warn: () => {}, debug: () => {} });
    try {
      await expect(
        new SearchDates(client).search(sweepFilters(93), { signal: controller.signal }),
      ).rejects.toBe(reason);
    } finally {
      setSearchLogger(null);
    }
    expect(calls).toBeLessThan(93);
  });

  test("an abort is not reported as a blocked sweep or a failed date", async () => {
    // The abort must not feed the circuit breaker or the "every date
    // failed" error — neither message is true, and both would send the
    // caller looking for a problem that is not there.
    const warnings: string[] = [];
    const controller = new AbortController();
    const reason = new Error("aborted");
    const client = new Client({
      retries: 1,
      backoffMs: 1,
      callsPerSecond: 10_000,
      fetchImpl: asFetch(async () => {
        controller.abort(reason);
        // Model a real fetch noticing the abort mid-flight.
        throw new DOMException("Aborted", "AbortError");
      }),
    });

    setSearchLogger({ warn: (m) => warnings.push(m), debug: () => {} });
    try {
      await expect(
        new SearchDates(client).search(sweepFilters(20), { signal: controller.signal }),
      ).rejects.toBe(reason);
    } finally {
      setSearchLogger(null);
    }
    expect(warnings.filter((w) => w.includes("FLI_SOCS_COOKIE"))).toHaveLength(0);
    expect(warnings.filter((w) => w.includes("real but incomplete"))).toHaveLength(0);
  });

  test("a sweep with no signal is unaffected", async () => {
    let calls = 0;
    const client = new Client({
      retries: 1,
      backoffMs: 1,
      callsPerSecond: 10_000,
      fetchImpl: asFetch(async () => {
        calls++;
        return new Response(pageWithOneFlight(), { status: 200 });
      }),
    });
    const results = await new SearchDates(client).search(sweepFilters(5));
    expect(results).toHaveLength(5);
    expect(calls).toBe(5);
  });
});

describe("aborting a round trip stops the expansion", () => {
  test("rejects with the caller's reason and stops fetching", async () => {
    let calls = 0;
    const controller = new AbortController();
    const reason = new Error("aborted mid round trip");
    const client = new Client({
      retries: 1,
      backoffMs: 1,
      callsPerSecond: 10_000,
      fetchImpl: asFetch(async () => {
        calls++;
        // Abort once the outbound board has come back, i.e. just as the
        // per-outbound return fetches are about to be issued.
        if (calls === 1) controller.abort(reason);
        return new Response(pageWithOneFlight(), { status: 200 });
      }),
    });
    const filters = new FlightSearchFilters({
      trip_type: TripType.ROUND_TRIP,
      passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
      flight_segments: [
        new FlightSegment({
          departure_airport: [[[Airport.JFK, 0]]],
          arrival_airport: [[[Airport.LAX, 0]]],
          travel_date: futureDate(20),
        }),
        new FlightSegment({
          departure_airport: [[[Airport.LAX, 0]]],
          arrival_airport: [[[Airport.JFK, 0]]],
          travel_date: futureDate(27),
        }),
      ],
    });
    await expect(
      new SearchFlights(client).search(filters, { topN: 5, signal: controller.signal }),
    ).rejects.toBe(reason);
    expect(calls).toBe(1);
  });
});
