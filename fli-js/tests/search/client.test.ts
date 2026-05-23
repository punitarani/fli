/**
 * HTTP client tests — focused on rate-limiting, retry, error wrapping,
 * timeout, and proxy plumbing. Network calls are stubbed via a fake fetch.
 */

import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { Client } from "../../src/search/client.ts";
import {
  SearchClientError,
  SearchConnectionError,
  SearchHTTPError,
  SearchTimeoutError,
} from "../../src/search/exceptions.ts";

function okResponse(text = "ok"): Response {
  return new Response(text, { status: 200, headers: { "content-type": "text/plain" } });
}

function errorResponse(status: number): Response {
  return new Response(`error ${status}`, { status });
}

/** Cast `() => Promise<Response>` style stubs to the wide `typeof fetch`. */
function asFetch(fn: (input: unknown, init?: RequestInit) => Promise<Response>): typeof fetch {
  return fn as unknown as typeof fetch;
}

describe("Client", () => {
  let originalEnv: typeof process.env.FLI_TIMEOUT;

  beforeEach(() => {
    originalEnv = process.env.FLI_TIMEOUT;
  });
  afterEach(() => {
    process.env.FLI_TIMEOUT = originalEnv;
  });

  test("POST with body sends the expected request", async () => {
    const captured: { url?: string; init?: RequestInit } = {};
    const fake = async (input: unknown, init?: RequestInit): Promise<Response> => {
      captured.url = String(input);
      captured.init = init ?? {};
      return okResponse("hello");
    };
    const c = new Client({ fetchImpl: asFetch(fake) });
    const res = await c.post("https://example.com/api", { body: "x=1" });
    expect(res.text).toBe("hello");
    expect(captured.url).toBe("https://example.com/api");
    expect(captured.init?.method).toBe("POST");
    expect(captured.init?.body).toBe("x=1");
  });

  test("GET sends an empty-body request", async () => {
    const captured: { init?: RequestInit } = {};
    const fake = async (_u: unknown, i?: RequestInit): Promise<Response> => {
      captured.init = i;
      return okResponse();
    };
    const c = new Client({ fetchImpl: asFetch(fake) });
    await c.get("https://example.com");
    expect(captured.init?.method).toBe("GET");
    expect(captured.init?.body).toBeUndefined();
  });

  test("default Chrome-like headers are applied", async () => {
    const captured: { headers?: Record<string, string> } = {};
    const fake = async (_u: unknown, init?: RequestInit): Promise<Response> => {
      captured.headers = init?.headers as Record<string, string>;
      return okResponse();
    };
    const c = new Client({ fetchImpl: asFetch(fake) });
    await c.post("https://example.com", { body: "" });
    expect(captured.headers?.["user-agent"]).toMatch(/Chrome/);
    expect(captured.headers?.["content-type"]).toBe(
      "application/x-www-form-urlencoded;charset=UTF-8",
    );
  });

  test("4xx wraps to SearchHTTPError with status_code", async () => {
    const fake = async (): Promise<Response> => errorResponse(429);
    const c = new Client({ fetchImpl: asFetch(fake), retries: 1 });
    try {
      await c.post("https://example.com", { body: "" });
      expect.unreachable();
    } catch (e) {
      expect(e).toBeInstanceOf(SearchHTTPError);
      expect((e as SearchHTTPError).status_code).toBe(429);
    }
  });

  test("connection error wraps to SearchConnectionError", async () => {
    const fake = async (): Promise<Response> => {
      throw new TypeError("fetch failed");
    };
    const c = new Client({ fetchImpl: asFetch(fake), retries: 1 });
    try {
      await c.post("https://example.com", { body: "" });
      expect.unreachable();
    } catch (e) {
      expect(e).toBeInstanceOf(SearchConnectionError);
    }
  });

  test("AbortError wraps to SearchTimeoutError", async () => {
    const fake = async (_u: unknown, init?: RequestInit): Promise<Response> => {
      return new Promise<Response>((_, reject) => {
        const signal = init?.signal;
        if (signal?.aborted) {
          reject(new DOMException("Aborted", "AbortError"));
          return;
        }
        signal?.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      });
    };
    const c = new Client({ fetchImpl: asFetch(fake), retries: 1, timeoutMs: 50 });
    try {
      await c.post("https://example.com", { body: "" });
      expect.unreachable();
    } catch (e) {
      expect(e).toBeInstanceOf(SearchTimeoutError);
    }
  });

  test("external AbortSignal propagates without retry and is NOT a SearchTimeoutError", async () => {
    let calls = 0;
    const fake = async (_u: unknown, init?: RequestInit): Promise<Response> => {
      calls++;
      return new Promise<Response>((_, reject) => {
        const signal = init?.signal;
        if (signal?.aborted) {
          reject(new DOMException("Aborted", "AbortError"));
          return;
        }
        signal?.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      });
    };
    const c = new Client({
      fetchImpl: asFetch(fake),
      retries: 3,
      timeoutMs: 60_000,
      backoffMs: 1,
    });
    const controller = new AbortController();
    const cancelled = new Error("caller aborted");
    setTimeout(() => controller.abort(cancelled), 20);
    try {
      await c.post("https://example.com", { body: "", signal: controller.signal });
      expect.unreachable();
    } catch (e) {
      // Caller's reason propagates as-is — NOT wrapped as a timeout.
      expect(e).toBe(cancelled);
      expect(e).not.toBeInstanceOf(SearchTimeoutError);
    }
    // No retry — the request stops the moment the caller cancels.
    expect(calls).toBe(1);
  });

  test("pre-aborted external signal short-circuits before any fetch retry", async () => {
    let calls = 0;
    // Real `fetch` rejects synchronously on a pre-aborted signal — model that.
    const fake = async (_u: unknown, init?: RequestInit): Promise<Response> => {
      calls++;
      if (init?.signal?.aborted) {
        throw new DOMException("Aborted", "AbortError");
      }
      return okResponse();
    };
    const c = new Client({ fetchImpl: asFetch(fake), retries: 3, backoffMs: 1 });
    const reason = new Error("already cancelled");
    const controller = new AbortController();
    controller.abort(reason);
    try {
      await c.post("https://example.com", { body: "", signal: controller.signal });
      expect.unreachable();
    } catch (e) {
      expect(e).toBe(reason);
      expect(e).not.toBeInstanceOf(SearchTimeoutError);
    }
    expect(calls).toBe(1);
  });

  test("retries on transient network failure then succeeds", async () => {
    let calls = 0;
    const fake = async (): Promise<Response> => {
      calls++;
      if (calls < 3) throw new TypeError("fetch failed");
      return okResponse("recovered");
    };
    const c = new Client({ fetchImpl: asFetch(fake), retries: 3, backoffMs: 1 });
    const res = await c.post("https://example.com", { body: "" });
    expect(res.text).toBe("recovered");
    expect(calls).toBe(3);
  });

  test("rate limiter slows down bursts", async () => {
    const fake = async (): Promise<Response> => okResponse();
    const c = new Client({
      fetchImpl: asFetch(fake),
      callsPerSecond: 2,
      retries: 1,
    });
    const start = performance.now();
    await Promise.all([
      c.post("https://x", { body: "" }),
      c.post("https://x", { body: "" }),
      c.post("https://x", { body: "" }),
      c.post("https://x", { body: "" }),
    ]);
    const elapsed = performance.now() - start;
    expect(elapsed).toBeGreaterThan(500);
  });

  test("HTTPS_PROXY env var picked up on construction", async () => {
    const previous = process.env.HTTPS_PROXY;
    process.env.HTTPS_PROXY = "http://proxy.example.com:8080";
    try {
      const captured: { init?: RequestInit & { proxy?: string } } = {};
      const fake = async (_u: unknown, i?: RequestInit): Promise<Response> => {
        captured.init = i as RequestInit & { proxy?: string };
        return okResponse();
      };
      const c = new Client({ fetchImpl: asFetch(fake) });
      await c.post("https://example.com", { body: "" });
      expect(captured.init?.proxy).toBe("http://proxy.example.com:8080");
    } finally {
      if (previous == null) process.env.HTTPS_PROXY = undefined;
      else process.env.HTTPS_PROXY = previous;
    }
  });

  test("explicit proxy option overrides env", async () => {
    process.env.HTTPS_PROXY = "http://wrong.example.com";
    try {
      const captured: { init?: RequestInit & { proxy?: string } } = {};
      const fake = async (_u: unknown, i?: RequestInit): Promise<Response> => {
        captured.init = i as RequestInit & { proxy?: string };
        return okResponse();
      };
      const c = new Client({
        fetchImpl: asFetch(fake),
        proxy: "http://right.example.com",
      });
      await c.post("https://example.com", { body: "" });
      expect(captured.init?.proxy).toBe("http://right.example.com");
    } finally {
      process.env.HTTPS_PROXY = undefined;
    }
  });

  test("invalid FLI_TIMEOUT throws on construction", () => {
    process.env.FLI_TIMEOUT = "garbage";
    expect(() => new Client()).toThrow(/FLI_TIMEOUT/);
  });

  test("negative FLI_TIMEOUT throws on construction", () => {
    process.env.FLI_TIMEOUT = "-5";
    expect(() => new Client()).toThrow(/FLI_TIMEOUT/);
  });

  test("retries exhausted re-raises the last error", async () => {
    const fake = async (): Promise<Response> => {
      throw new TypeError("fetch failed");
    };
    const c = new Client({ fetchImpl: asFetch(fake), retries: 2, backoffMs: 1 });
    await expect(c.post("https://x", { body: "" })).rejects.toBeInstanceOf(SearchClientError);
  });
});
