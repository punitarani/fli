/**
 * Typed errors raised by the search client.
 * Mirrors fli/search/exceptions.py.
 *
 * These exist so consumers can react to a network failure with a clear,
 * user-facing message instead of a raw `fetch` error. They are
 * intentionally light wrappers — the original error is kept as `cause`
 * where one exists.
 */

export class SearchClientError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "SearchClientError";
  }
}

export class SearchTimeoutError extends SearchClientError {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "SearchTimeoutError";
  }
}

export class SearchConnectionError extends SearchClientError {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "SearchConnectionError";
  }
}

export class SearchHTTPError extends SearchClientError {
  status_code: number | null;
  constructor(message: string, statusCode: number | null = null, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "SearchHTTPError";
    this.status_code = statusCode;
  }
}

/**
 * Google answered HTTP 200 but declined to serve results.
 *
 * The response carries a `wrb.fr` row with no payload and an error code
 * (13 = INTERNAL). Since 2026-08 `GetShoppingResults` /
 * `GetBookingResults` require an `x-goog-batchexecute-bgr` header signed
 * by the page's own JavaScript over the exact request bytes, so a plain
 * HTTP client always lands here. Without this error the caller saw an
 * empty list and reported "no flights found", which is indistinguishable
 * from a route with no service.
 */
export class SearchRejectedError extends SearchClientError {
  code: number | null;
  constructor(code: number | null = null) {
    const suffix = code == null ? "" : ` (error ${code})`;
    super(
      `Google Flights declined the request${suffix} and returned no data. ` +
        "Its API now requires a browser-signed x-goog-batchexecute-bgr header, " +
        "which this client cannot produce. See github.com/punitarani/fli#223.",
    );
    this.name = "SearchRejectedError";
    this.code = code;
  }
}

/**
 * The requested search cannot be served by the current transport.
 *
 * Distinct from an empty result: the query is well formed and Google
 * would answer it in a browser, but the public search page carries no
 * inline payload for it, so this client has nothing to read.
 */
export class SearchUnsupportedError extends SearchClientError {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "SearchUnsupportedError";
  }
}

/**
 * A successful HTTP response could not be parsed into flights.
 *
 * Distinct from network / HTTP errors: this says "Google responded but
 * the shape changed", not "Google didn't respond". In practice it is
 * either a consent/blocked page (no `ds:1` blob at all) or a change in
 * the flight rows themselves.
 *
 * It belongs to the {@link SearchClientError} family so that callers
 * already catching search failures classify it as one instead of an
 * unexpected crash.
 */
export class SearchParseError extends SearchClientError {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "SearchParseError";
  }
}
