/**
 * HTTP client with rate limiting, retries, and proxy support.
 *
 * Replaces the Python `curl_cffi` impersonation with a `fetch`-based
 * client that:
 *
 *   - sends realistic Chrome-like headers
 *   - honours HTTPS_PROXY / HTTP_PROXY env vars (Bun's fetch supports this
 *     via the `proxy` option)
 *   - rate-limits at 10 req/sec via {@link TokenBucketRateLimiter}
 *   - retries network errors with exponential backoff
 *   - wraps low-level errors into the typed {@link SearchClientError} family
 */

import { sleep, TokenBucketRateLimiter } from "./concurrency.ts";
import {
  SearchClientError,
  SearchConnectionError,
  SearchHTTPError,
  SearchTimeoutError,
} from "./exceptions.ts";

const DEFAULT_CALLS_PER_SECOND = 10;
const DEFAULT_TIMEOUT_MS = 60_000;
const DEFAULT_RETRIES = 3;
const DEFAULT_BACKOFF_MS = 1_000;

function parseEnvTimeoutMs(): number {
  const raw = typeof process !== "undefined" ? process.env?.FLI_TIMEOUT : undefined;
  if (raw == null) return DEFAULT_TIMEOUT_MS;
  const n = Number.parseFloat(raw);
  if (!Number.isFinite(n)) {
    throw new Error(`FLI_TIMEOUT must be a number of seconds, got: ${JSON.stringify(raw)}`);
  }
  if (n <= 0) {
    throw new Error(`FLI_TIMEOUT must be a positive number, got: ${JSON.stringify(raw)}`);
  }
  return Math.round(n * 1000);
}

function resolveProxy(): string | undefined {
  if (typeof process === "undefined" || !process.env) return undefined;
  const env = process.env;
  return env.HTTPS_PROXY ?? env.https_proxy ?? env.HTTP_PROXY ?? env.http_proxy ?? undefined;
}

/**
 * Headers every request carries.
 *
 * The `user-agent` is the load-bearing one, and not cosmetically: the
 * `/travel/flights` page inlines its `ds:1` flight payload only for a
 * request that looks like a browser. Probed 2026-09-20 under Bun 1.3 and
 * Node 24 — with a Chrome UA the page is ~2.5 MB and carries the rows;
 * with no UA at all it is ~1.2 MB and carries none, on HTTP 200 either
 * way. The rest of the headers are not required by that probe, and are
 * sent because a browser sends them.
 */
const BASE_HEADERS: Record<string, string> = {
  // A realistic recent-Chrome UA. Google's frontend is tolerant of mismatch
  // between the UA and the actual TLS fingerprint (which we can't fake from
  // a Node/Bun fetch) but a credible UA makes a difference vs the default
  // "node-fetch" / "undici" strings.
  "user-agent":
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
  "accept-language": "en-US,en;q=0.9",
  "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24", "Google Chrome";v="131"',
  "sec-ch-ua-mobile": "?0",
  "sec-ch-ua-platform": '"macOS"',
};

/**
 * Headers for the `f.req` RPC POSTs (`GetBookingResults`).
 *
 * Unchanged from before the search-page transport landed, so the one
 * remaining RPC call goes out exactly as it always did.
 */
const DEFAULT_HEADERS: Record<string, string> = {
  ...BASE_HEADERS,
  accept: "*/*",
  "sec-fetch-dest": "empty",
  "sec-fetch-mode": "cors",
  "sec-fetch-site": "same-origin",
  "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
};

/**
 * Headers for the search-page GET.
 *
 * A top-level document navigation, which is what this request actually
 * is — the POST set describes a same-origin XHR, and carries a
 * form-encoded `content-type` on a request with no body.
 */
const DEFAULT_GET_HEADERS: Record<string, string> = {
  ...BASE_HEADERS,
  accept:
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
  "sec-fetch-dest": "document",
  "sec-fetch-mode": "navigate",
  "sec-fetch-site": "none",
  "sec-fetch-user": "?1",
  "upgrade-insecure-requests": "1",
};

/**
 * Pre-accepted consent cookie, sent so EU/EEA IPs are not redirected to
 * Google's consent interstitial — which serves a page with no `ds:1`
 * payload, so every search there fails to parse. The legacy `CONSENT`
 * cookie no longer works, and a truncated `SOCS` value is ignored.
 *
 * Override with `FLI_SOCS_COOKIE` if Google rotates the value; set it to
 * the empty string to send no cookie at all.
 */
export const DEFAULT_SOCS_COOKIE =
  "CAISNQgQEitib3FfaWRlbnRpdHlmcm9udGVuZHVpc2VydmVyXzIwMjQwMzE3LjA5X3AwGgJlbiADGgYIgLC_rwY";

/**
 * The `SOCS` cookie value in effect: `FLI_SOCS_COOKIE` if set (including
 * to the empty string, which disables the cookie), else
 * {@link DEFAULT_SOCS_COOKIE}.
 *
 * Read at `Client` construction rather than at module load — Python
 * reads its process environment once at import, but a JS consumer that
 * sets `process.env` before building a client would find that surprising,
 * and it makes the behaviour testable without module cache games.
 */
export function resolveSocsCookie(): string {
  const raw = typeof process !== "undefined" ? process.env?.FLI_SOCS_COOKIE : undefined;
  return raw ?? DEFAULT_SOCS_COOKIE;
}

export interface ClientOptions {
  /** Calls per second budget. Defaults to 10. */
  callsPerSecond?: number;
  /** Per-request timeout in ms. Defaults to 60_000 (or `FLI_TIMEOUT` env var * 1000). */
  timeoutMs?: number;
  /** Total request attempts including the first try. Defaults to 3. */
  retries?: number;
  /** Initial backoff between attempts in ms. Defaults to 1_000. */
  backoffMs?: number;
  /** Proxy URL (e.g. `http://user:pass@host:port`). Defaults to HTTPS_PROXY/HTTP_PROXY env. */
  proxy?: string | null;
  /** Custom fetch implementation (test seam). */
  fetchImpl?: typeof fetch;
  /**
   * `SOCS` consent cookie value. Defaults to `FLI_SOCS_COOKIE` if set,
   * else {@link DEFAULT_SOCS_COOKIE}. An empty string sends no cookie.
   */
  socsCookie?: string;
}

export interface RequestOptions {
  headers?: Record<string, string>;
  body?: string | Uint8Array;
  signal?: AbortSignal;
}

export interface ClientResponse {
  status: number;
  statusText: string;
  text: string;
  headers: Headers;
  ok: boolean;
}

/**
 * Is this URL served by Google?
 *
 * The `SOCS` consent cookie must not ride along to whatever other host a
 * caller points the client at — Python keeps it in a cookie jar scoped to
 * `.google.com`, and a header has no such scope of its own. `.google.com`
 * covers `www.google.com` and `consent.google.com`, which are the two
 * hosts a search actually touches, and deliberately not `google.co.uk`
 * (Python's jar does not match it either).
 */
function isGoogleHost(url: string): boolean {
  let hostname: string;
  try {
    hostname = new URL(url).hostname.toLowerCase();
  } catch {
    return false;
  }
  return hostname === "google.com" || hostname.endsWith(".google.com");
}

function hostFromUrl(url: string): string {
  try {
    return new URL(url).host || url;
  } catch {
    return url;
  }
}

function isAbortError(err: unknown): boolean {
  if (err instanceof DOMException && err.name === "AbortError") return true;
  if (typeof err === "object" && err != null && "name" in err) {
    return (err as { name?: unknown }).name === "AbortError";
  }
  return false;
}

function wrapRequestError(method: string, url: string, err: unknown): SearchClientError {
  if (err instanceof SearchClientError) return err;
  const host = hostFromUrl(url);
  if (isAbortError(err)) {
    return new SearchTimeoutError(
      `Timed out talking to Google Flights (${host}). The service may be slow or unreachable from your network — check your connection and try again.`,
    );
  }
  const message = err instanceof Error ? err.message : String(err);
  // Network-y messages from undici/bun-internals get bucketed into Connection.
  if (/(ECONNRESET|ENOTFOUND|ECONNREFUSED|EAI_AGAIN|fetch failed)/i.test(message)) {
    return new SearchConnectionError(
      `Could not reach Google Flights (${host}). Check your internet connection or DNS and try again.`,
    );
  }
  return new SearchClientError(
    `${method} request to Google Flights (${host}) failed: ${err instanceof Error ? err.name : "Error"}`,
  );
}

export class Client {
  private readonly rateLimiter: TokenBucketRateLimiter;
  private readonly timeoutMs: number;
  private readonly retries: number;
  private readonly backoffMs: number;
  private readonly proxy: string | undefined;
  private readonly fetchImpl: typeof fetch;
  private readonly cookieHeader: Record<string, string>;

  constructor(options: ClientOptions = {}) {
    this.rateLimiter = new TokenBucketRateLimiter(
      options.callsPerSecond ?? DEFAULT_CALLS_PER_SECOND,
      1.0,
    );
    this.timeoutMs = options.timeoutMs ?? parseEnvTimeoutMs();
    this.retries = options.retries ?? DEFAULT_RETRIES;
    this.backoffMs = options.backoffMs ?? DEFAULT_BACKOFF_MS;
    this.proxy = options.proxy === null ? undefined : (options.proxy ?? resolveProxy());
    this.fetchImpl = options.fetchImpl ?? fetch;
    const socs = options.socsCookie ?? resolveSocsCookie();
    this.cookieHeader = socs ? { cookie: `SOCS=${socs}` } : {};
  }

  async get(url: string, options: RequestOptions = {}): Promise<ClientResponse> {
    return this.request("GET", url, options);
  }

  async post(url: string, options: RequestOptions = {}): Promise<ClientResponse> {
    return this.request("POST", url, options);
  }

  private async request(
    method: "GET" | "POST",
    url: string,
    options: RequestOptions,
  ): Promise<ClientResponse> {
    let lastError: unknown = null;
    for (let attempt = 0; attempt < this.retries; attempt++) {
      await this.rateLimiter.acquire();
      const controller = new AbortController();
      const externalSignal = options.signal;
      let abortListener: (() => void) | undefined;
      if (externalSignal) {
        if (externalSignal.aborted) controller.abort(externalSignal.reason);
        else {
          abortListener = () => controller.abort(externalSignal.reason);
          externalSignal.addEventListener("abort", abortListener);
        }
      }
      const timer = setTimeout(() => controller.abort(), this.timeoutMs);
      let shouldRetry = false;
      try {
        const init: RequestInit & { proxy?: string } = {
          method,
          headers: {
            ...(method === "GET" ? DEFAULT_GET_HEADERS : DEFAULT_HEADERS),
            ...(isGoogleHost(url) ? this.cookieHeader : {}),
            ...options.headers,
          },
          signal: controller.signal,
        };
        if (method === "POST" && options.body != null) {
          init.body =
            options.body instanceof Uint8Array ? (options.body as BodyInit) : options.body;
        }
        if (this.proxy) init.proxy = this.proxy;
        const response = await this.fetchImpl(url, init);
        if (!response.ok) {
          // Match the Python `raise_for_status` semantics — surface non-2xx
          // as a typed error and let the retry loop decide whether to back off.
          throw new SearchHTTPError(
            `Google Flights returned an error response (HTTP ${response.status}). The request may be malformed, rate-limited, or blocked.`,
            response.status,
          );
        }
        const text = await response.text();
        return {
          status: response.status,
          statusText: response.statusText,
          text,
          headers: response.headers,
          ok: response.ok,
        };
      } catch (err) {
        // Distinguish external cancellation from internal timeout: if the
        // caller's AbortSignal triggered the abort, propagate the original
        // error without retry and without relabelling it as a timeout. A
        // consumer catching SearchTimeoutError to decide whether to retry
        // would otherwise retry on a deliberate cancellation, and the
        // "Google was slow" message would be misleading.
        if (isAbortError(err) && externalSignal?.aborted) {
          throw externalSignal.reason ?? err;
        }
        lastError = wrapRequestError(method, url, err);
        // For HTTP errors we still respect the retry budget (matches the
        // Python tenacity retry decorator behavior, which retries on any
        // exception).
        if (attempt >= this.retries - 1) break;
        shouldRetry = true;
      } finally {
        clearTimeout(timer);
        if (abortListener && externalSignal) {
          externalSignal.removeEventListener("abort", abortListener);
        }
      }

      // Outside the try/finally on purpose: the per-attempt timeout timer
      // is cleared first, so a long backoff never sits under an armed
      // request timeout. The sleep itself is abortable — waiting out a
      // 4-second backoff after the caller has cancelled, and leaving the
      // timer running afterwards, is exactly what a cancellation is for.
      if (shouldRetry) {
        try {
          await sleep(this.backoffMs * 2 ** attempt, externalSignal);
        } catch (abortErr) {
          throw externalSignal?.reason ?? abortErr;
        }
      }
    }
    throw lastError ?? new SearchClientError("Unknown request failure");
  }
}

let _sharedClient: Client | null = null;

/**
 * Return the process-wide shared client.
 *
 * Lazy on the first call. If `options` is passed on a later call, the
 * existing singleton is replaced with a new instance configured against
 * those options (and that new instance becomes the cached singleton for
 * subsequent no-arg callers). Callers that want a fully isolated client
 * — e.g. to use a different proxy in one place without affecting
 * others — should construct `new Client(options)` directly and pass it
 * to `SearchFlights` / `SearchDates`.
 */
export function getClient(options?: ClientOptions): Client {
  if (_sharedClient == null || options != null) {
    _sharedClient = new Client(options);
  }
  return _sharedClient;
}

/** Replace the shared client (test helper). */
export function _setSharedClient(client: Client | null): void {
  _sharedClient = client;
}
