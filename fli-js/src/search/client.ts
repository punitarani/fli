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

import { TokenBucketRateLimiter } from "./concurrency.ts";
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

const DEFAULT_HEADERS: Record<string, string> = {
  // A realistic recent-Chrome UA. Google's frontend is tolerant of mismatch
  // between the UA and the actual TLS fingerprint (which we can't fake from
  // a Node/Bun fetch) but a credible UA makes a difference vs the default
  // "node-fetch" / "undici" strings.
  "user-agent":
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
  accept: "*/*",
  "accept-language": "en-US,en;q=0.9",
  "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24", "Google Chrome";v="131"',
  "sec-ch-ua-mobile": "?0",
  "sec-ch-ua-platform": '"macOS"',
  "sec-fetch-dest": "empty",
  "sec-fetch-mode": "cors",
  "sec-fetch-site": "same-origin",
  "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
};

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

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
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
      try {
        const init: RequestInit & { proxy?: string } = {
          method,
          headers: { ...DEFAULT_HEADERS, ...options.headers },
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
        if (attempt < this.retries - 1) {
          const wait = this.backoffMs * 2 ** attempt;
          await sleep(wait);
          continue;
        }
        break;
      } finally {
        clearTimeout(timer);
        if (abortListener && externalSignal) {
          externalSignal.removeEventListener("abort", abortListener);
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
