/**
 * URL helpers for the FlightsFrontendService RPCs.
 *
 * The implementation lives in `core/links.ts` so the same helper can build the
 * public-facing Google Flights deep links. Re-exported here to keep
 * `search/urls.ts` stable for existing importers.
 */

export { withLocaleParams } from "../core/links.ts";
