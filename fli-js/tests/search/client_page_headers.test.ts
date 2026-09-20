/**
 * Request-shaping tests for the search-page GET.
 *
 * Google's `/travel/flights` page decides whether to inline its `ds:1`
 * payload from the request headers — with no `user-agent` it serves a
 * 1.2 MB shell with no flight rows at all, and every search silently
 * returns nothing. That, plus the EU/EEA consent cookie, is what this
 * covers.
 */

import { afterEach, describe, expect, test } from "bun:test";
import { Client, DEFAULT_SOCS_COOKIE, resolveSocsCookie } from "../../src/search/client.ts";

function asFetch(fn: (input: unknown, init?: RequestInit) => Promise<Response>): typeof fetch {
  return fn as unknown as typeof fetch;
}

async function captureHeaders(
  method: "get" | "post",
  options: ConstructorParameters<typeof Client>[0] = {},
): Promise<Record<string, string>> {
  let headers: Record<string, string> = {};
  const client = new Client({
    ...options,
    retries: 1,
    fetchImpl: asFetch(async (_u, init) => {
      headers = (init?.headers ?? {}) as Record<string, string>;
      return new Response("ok", { status: 200 });
    }),
  });
  if (method === "get") await client.get("https://www.google.com/travel/flights?tfs=x");
  else await client.post("https://www.google.com/x", { body: "" });
  return headers;
}

const originalSocs = process.env.FLI_SOCS_COOKIE;

afterEach(() => {
  if (originalSocs === undefined) delete process.env.FLI_SOCS_COOKIE;
  else process.env.FLI_SOCS_COOKIE = originalSocs;
});

describe("search-page GET headers", () => {
  test("a GET carries a Chrome user-agent — without it the page has no ds:1", async () => {
    const headers = await captureHeaders("get");
    expect(headers["user-agent"]).toMatch(/Chrome/);
  });

  test("a GET asks for a document, not an XHR", async () => {
    const headers = await captureHeaders("get");
    expect(headers.accept).toContain("text/html");
    expect(headers["sec-fetch-dest"]).toBe("document");
    expect(headers["sec-fetch-mode"]).toBe("navigate");
    // A form-encoded content-type on a body-less GET is nonsense.
    expect(headers["content-type"]).toBeUndefined();
  });

  test("the RPC POST keeps the headers it always sent", async () => {
    const headers = await captureHeaders("post");
    expect(headers["content-type"]).toBe("application/x-www-form-urlencoded;charset=UTF-8");
    expect(headers.accept).toBe("*/*");
    expect(headers["sec-fetch-mode"]).toBe("cors");
  });
});

describe("SOCS consent cookie", () => {
  test("sent by default on both verbs", async () => {
    expect(DEFAULT_SOCS_COOKIE.length).toBeGreaterThan(40);
    for (const method of ["get", "post"] as const) {
      const headers = await captureHeaders(method);
      expect(headers.cookie).toBe(`SOCS=${DEFAULT_SOCS_COOKIE}`);
    }
  });

  test("FLI_SOCS_COOKIE overrides the value", async () => {
    process.env.FLI_SOCS_COOKIE = "custom-value";
    const headers = await captureHeaders("get");
    expect(headers.cookie).toBe("SOCS=custom-value");
  });

  test("an empty FLI_SOCS_COOKIE disables the cookie entirely", async () => {
    process.env.FLI_SOCS_COOKIE = "";
    const headers = await captureHeaders("get");
    expect(headers.cookie).toBeUndefined();
  });

  test("resolveSocsCookie reads the env at call time", () => {
    process.env.FLI_SOCS_COOKIE = "abc";
    expect(resolveSocsCookie()).toBe("abc");
    process.env.FLI_SOCS_COOKIE = "";
    expect(resolveSocsCookie()).toBe("");
    delete process.env.FLI_SOCS_COOKIE;
    expect(resolveSocsCookie()).toBe(DEFAULT_SOCS_COOKIE);
  });

  test("a caller-supplied cookie header wins", async () => {
    let headers: Record<string, string> = {};
    const client = new Client({
      retries: 1,
      fetchImpl: asFetch(async (_u, init) => {
        headers = (init?.headers ?? {}) as Record<string, string>;
        return new Response("ok", { status: 200 });
      }),
    });
    await client.get("https://x", { headers: { cookie: "SOCS=mine" } });
    expect(headers.cookie).toBe("SOCS=mine");
  });
});
