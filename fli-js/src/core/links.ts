/**
 * Shared URL helpers for Google Flights deep links.
 *
 * Consumers can surface a clickable Google Flights link alongside search
 * results so a user can open the route (and complete a booking) in a
 * browser. The natural-language `q` form used here is the same one Google's
 * own frontend accepts.
 *
 * `withLocaleParams` lives here (rather than in `search/`) so the core layer
 * stays free of any dependency on the search package; `search/urls.ts`
 * re-exports it for backwards compatibility.
 *
 * 1:1 port of fli/core/links.py.
 */

const GOOGLE_FLIGHTS_URL = "https://www.google.com/travel/flights";

/**
 * Append optional `curr`/`hl`/`gl` parameters to a URL.
 *
 * - `currency` is uppercased ("usd" → "USD") because Google rejects lowercase
 *   codes silently.
 * - `language` is passed through verbatim (BCP-47).
 * - `country` is uppercased (ISO 3166-1 alpha-2).
 *
 * All values are percent-encoded; returns `url` unchanged when all three are null.
 */
export function withLocaleParams(
  url: string,
  currency: string | null | undefined,
  language: string | null | undefined,
  country: string | null | undefined,
): string {
  const params: string[] = [];
  if (currency) params.push(`curr=${encodeURIComponent(currency.toUpperCase())}`);
  if (language) params.push(`hl=${encodeURIComponent(language)}`);
  if (country) params.push(`gl=${encodeURIComponent(country.toUpperCase())}`);
  if (params.length === 0) return url;
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}${params.join("&")}`;
}

export interface GoogleFlightsUrlOptions {
  currency?: string | null;
  language?: string | null;
  country?: string | null;
}

/**
 * Build a shareable Google Flights deep link for a route and dates.
 *
 * `origin` and `destination` are bare IATA codes (e.g. `"JFK"`). The returned
 * URL pre-fills the route and outbound date (plus the return date for round
 * trips); locale knobs (`curr`/`hl`/`gl`) are appended when supplied.
 */
export function googleFlightsUrl(
  origin: string,
  destination: string,
  departureDate: string,
  returnDate?: string | null,
  options: GoogleFlightsUrlOptions = {},
): string {
  let query = `Flights from ${origin} to ${destination} on ${departureDate}`;
  if (returnDate) query += ` through ${returnDate}`;
  const url = `${GOOGLE_FLIGHTS_URL}?q=${encodeURIComponent(query)}`;
  return withLocaleParams(
    url,
    options.currency ?? null,
    options.language ?? null,
    options.country ?? null,
  );
}
