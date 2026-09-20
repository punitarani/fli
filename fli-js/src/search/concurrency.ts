/**
 * Async concurrency primitives. 1:1 port of fli/search/_concurrency.py,
 * adapted to JavaScript's single-threaded event loop (no need for a
 * threading.Condition — `setTimeout`/`Promise` are the equivalent).
 */

/**
 * Throw the caller's abort reason if `signal` has already fired.
 *
 * Used at every point where a cancelled call would otherwise spend
 * something on the caller's behalf — a rate-limiter token (which delays
 * the next real request), a `fetchImpl` call, a page fetch, a date.
 * Real `fetch` rejects a pre-aborted signal without touching the network,
 * but a custom `fetchImpl` is under no such obligation.
 */
export function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) {
    throw signal.reason ?? new DOMException("Aborted", "AbortError");
  }
}

/**
 * Sleep for `ms`, giving up promptly if `signal` aborts.
 *
 * Both backoffs in this package — the client's retry backoff and the
 * page-retry backoff — sit between HTTP requests on a path a caller may
 * cancel. A plain `setTimeout` promise would make the caller wait out a
 * delay that no longer has any reason to elapse, and would leave the
 * timer armed after the call had already settled.
 *
 * Rejects with the signal's own `reason`, so the caller gets back the
 * error it aborted with rather than a synthesised one.
 */
export function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal == null) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
  return new Promise<void>((resolve, reject) => {
    const abortReason = (): unknown => signal.reason ?? new DOMException("Aborted", "AbortError");
    if (signal.aborted) {
      reject(abortReason());
      return;
    }
    let timer: ReturnType<typeof setTimeout> | undefined;
    const onAbort = (): void => {
      if (timer !== undefined) clearTimeout(timer);
      reject(abortReason());
    };
    timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * Async token-bucket rate limiter.
 *
 * The bucket starts full (`capacity` tokens) and refills continuously at
 * `capacity / period` tokens per second. `acquire()` resolves once a
 * token has been taken; concurrent waiters are released in arrival order
 * via a FIFO promise chain.
 */
export class TokenBucketRateLimiter {
  private readonly capacityValue: number;
  private readonly refillPerSecond: number;
  private tokens: number;
  private lastRefill: number;
  /** Serialises waiters so they wake in arrival order. */
  private queue: Promise<void> = Promise.resolve();

  constructor(calls: number, period: number) {
    if (calls <= 0) throw new Error("calls must be positive");
    if (period <= 0) throw new Error("period must be positive");
    this.capacityValue = calls;
    this.refillPerSecond = calls / period;
    this.tokens = calls;
    this.lastRefill = performance.now() / 1000;
  }

  get capacity(): number {
    return Math.floor(this.capacityValue);
  }

  private refill(): void {
    const now = performance.now() / 1000;
    const elapsed = now - this.lastRefill;
    if (elapsed > 0) {
      this.tokens = Math.min(this.capacityValue, this.tokens + elapsed * this.refillPerSecond);
      this.lastRefill = now;
    }
  }

  /**
   * Block until `tokens` are available; returns `false` on timeout.
   *
   * @param tokens count to acquire (must be ≤ capacity)
   * @param timeoutMs optional timeout in milliseconds
   */
  async acquire(tokens = 1, timeoutMs: number | null = null): Promise<boolean> {
    if (tokens <= 0) return true;
    if (tokens > this.capacityValue) {
      throw new Error(`tokens=${tokens} exceeds bucket capacity=${this.capacity}`);
    }

    const deadline = timeoutMs == null ? null : performance.now() + timeoutMs;
    // Serialise waiters so they take tokens FIFO.
    let release: () => void = () => {};
    const slot = new Promise<void>((res) => {
      release = res;
    });
    const prev = this.queue;
    this.queue = prev.then(() => slot);
    await prev;

    try {
      // eslint-disable-next-line no-constant-condition
      while (true) {
        this.refill();
        if (this.tokens >= tokens) {
          this.tokens -= tokens;
          return true;
        }
        const deficit = tokens - this.tokens;
        const waitS = deficit / this.refillPerSecond;
        let waitMs = waitS * 1000;
        if (deadline != null) {
          const remaining = deadline - performance.now();
          if (remaining <= 0) return false;
          waitMs = Math.min(waitMs, remaining);
        }
        await new Promise<void>((res) => setTimeout(res, waitMs));
      }
    } finally {
      // Wake the next waiter so they can re-check the bucket.
      release();
    }
  }
}

// ---------------------------------------------------------------------------
// parallelMap — bounded Promise.all
// ---------------------------------------------------------------------------

let DEFAULT_MAX_WORKERS = 10;

export function configureConcurrency(maxWorkers: number): void {
  if (maxWorkers <= 0) throw new Error("maxWorkers must be positive");
  DEFAULT_MAX_WORKERS = maxWorkers;
}

export function getDefaultMaxWorkers(): number {
  return DEFAULT_MAX_WORKERS;
}

/**
 * Apply `fn` to each item with bounded concurrency; results returned in
 * input order. Fast-path for ≤1 items / maxWorkers=1 (no scheduling
 * overhead).
 *
 * The first rejection rethrows after all in-flight calls have settled,
 * matching the Python implementation's "let siblings finish" contract.
 */
export async function parallelMap<T, R>(
  fn: (item: T) => Promise<R>,
  items: Iterable<T>,
  options: { maxWorkers?: number } = {},
): Promise<R[]> {
  const materialised = Array.isArray(items) ? items : [...items];
  const n = materialised.length;
  if (n === 0) return [];

  const workers = options.maxWorkers ?? DEFAULT_MAX_WORKERS;
  if (n === 1 || workers === 1) {
    const out: R[] = Array.from({ length: n });
    for (let i = 0; i < n; i++) {
      out[i] = await fn(materialised[i] as T);
    }
    return out;
  }

  const results: R[] = Array.from({ length: n });
  let firstError: unknown = null;
  let nextIndex = 0;

  const runner = async (): Promise<void> => {
    while (true) {
      const idx = nextIndex++;
      if (idx >= n) return;
      try {
        results[idx] = await fn(materialised[idx] as T);
      } catch (err) {
        if (firstError == null) firstError = err;
      }
    }
  };

  const workerPromises: Promise<void>[] = [];
  const cap = Math.min(workers, n);
  for (let i = 0; i < cap; i++) workerPromises.push(runner());
  await Promise.all(workerPromises);

  if (firstError != null) throw firstError;
  return results;
}
