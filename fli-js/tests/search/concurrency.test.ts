/**
 * Tests for the async concurrency primitives.
 * Mirrors tests/search/test_concurrency.py — adapted for promises.
 */

import { describe, expect, test } from "bun:test";
import {
  configureConcurrency,
  parallelMap,
  TokenBucketRateLimiter,
} from "../../src/search/concurrency.ts";

describe("TokenBucketRateLimiter basics", () => {
  test("capacity is exposed", () => {
    expect(new TokenBucketRateLimiter(10, 1.0).capacity).toBe(10);
  });

  test("starts full — N acquires complete immediately", async () => {
    const limiter = new TokenBucketRateLimiter(5, 1.0);
    const start = performance.now();
    for (let i = 0; i < 5; i++) {
      expect(await limiter.acquire()).toBe(true);
    }
    expect(performance.now() - start).toBeLessThan(50);
  });

  test("blocks when empty and refills", async () => {
    const limiter = new TokenBucketRateLimiter(2, 0.2); // 10/sec refill
    await limiter.acquire();
    await limiter.acquire();
    const start = performance.now();
    await limiter.acquire(); // ~100ms wait expected
    const elapsed = performance.now() - start;
    expect(elapsed).toBeGreaterThan(50);
    expect(elapsed).toBeLessThan(300);
  });

  test("timeout returns false", async () => {
    const limiter = new TokenBucketRateLimiter(1, 5.0);
    await limiter.acquire();
    expect(await limiter.acquire(1, 50)).toBe(false);
  });

  test("zero tokens is a noop", async () => {
    const limiter = new TokenBucketRateLimiter(1, 1.0);
    expect(await limiter.acquire(0)).toBe(true);
  });

  test("invalid construction rejected", () => {
    expect(() => new TokenBucketRateLimiter(0, 1.0)).toThrow();
    expect(() => new TokenBucketRateLimiter(1, 0)).toThrow();
  });

  test("request more than capacity raises", async () => {
    const limiter = new TokenBucketRateLimiter(3, 1.0);
    await expect(limiter.acquire(4)).rejects.toThrow();
  });
});

describe("parallelMap", () => {
  test("preserves order", async () => {
    const result = await parallelMap(async (x: number) => x * 2, [1, 2, 3, 4, 5]);
    expect(result).toEqual([2, 4, 6, 8, 10]);
  });

  test("empty input", async () => {
    expect(await parallelMap(async (x: number) => x, [])).toEqual([]);
  });

  test("single item bypasses worker pool", async () => {
    const result = await parallelMap(async (x: number) => x + 1, [42]);
    expect(result).toEqual([43]);
  });

  test("maxWorkers=1 runs sequentially", async () => {
    const order: number[] = [];
    await parallelMap(
      async (x: number) => {
        order.push(x);
        return x;
      },
      [1, 2, 3],
      { maxWorkers: 1 },
    );
    expect(order).toEqual([1, 2, 3]);
  });

  test("first rejection propagates", async () => {
    await expect(
      parallelMap(
        async (x: number) => {
          if (x === 2) throw new Error("boom");
          return x;
        },
        [1, 2, 3],
      ),
    ).rejects.toThrow("boom");
  });

  test("actually parallel — total time ~= longest single call", async () => {
    const sleepMs = 100;
    const start = performance.now();
    await parallelMap(
      async (x: number) => {
        await new Promise((r) => setTimeout(r, sleepMs));
        return x;
      },
      [0, 1, 2, 3, 4],
      { maxWorkers: 5 },
    );
    const elapsed = performance.now() - start;
    // Sequential would be 500ms; parallel should be ~100-300ms.
    expect(elapsed).toBeLessThan(sleepMs * 3.5);
  });

  test("maxWorkers cap respected", async () => {
    let inFlight = 0;
    let peak = 0;
    await parallelMap(
      async (x: number) => {
        inFlight++;
        peak = Math.max(peak, inFlight);
        await new Promise((r) => setTimeout(r, 20));
        inFlight--;
        return x;
      },
      [1, 2, 3, 4, 5, 6],
      { maxWorkers: 2 },
    );
    expect(peak).toBeLessThanOrEqual(2);
    expect(peak).toBeGreaterThanOrEqual(1);
  });

  test("iterable input", async () => {
    const gen = function* () {
      yield 0;
      yield 1;
      yield 2;
    };
    expect(await parallelMap(async (x: number) => x * 3, gen())).toEqual([0, 3, 6]);
  });
});

describe("configureConcurrency", () => {
  test("rejects invalid values", () => {
    expect(() => configureConcurrency(0)).toThrow();
    expect(() => configureConcurrency(-1)).toThrow();
  });
});
