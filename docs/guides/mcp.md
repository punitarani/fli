# MCP Server Guide

This project exposes flight search tools via a FastMCP server. You can run it over STDIO (default) or the streamable HTTP transport.

## Installation

```bash
# Install with pipx (recommended)
pipx install flights

# Or with pip
pip install flights
```

## Running the Server

### Run over STDIO

Use the console script for Claude Desktop and other MCP clients:

```bash
fli-mcp
```

### Run over HTTP (streamable)

Use the HTTP entrypoint for web-based integrations. By default it binds to `127.0.0.1:8000`.

```bash
fli-mcp-http
```

You can override host/port by calling the function directly in Python:

```python
from fli.mcp import run_http

run_http(host="0.0.0.0", port=8000)
```

Once running, the MCP endpoint is served at `/mcp/`, for example: `http://127.0.0.1:8000/mcp/`.

A liveness probe is available at `/health` (returns `{"status": "ok"}`). It is what the
`docker-compose.yml` healthcheck calls, and it does not contact Google Flights, so an upstream
outage will not cause a healthy container to be restarted.

## Claude Desktop Configuration

Add this configuration to your `claude_desktop_config.json`:

**Location**: `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)

```json
{
  "mcpServers": {
    "fli": {
      "command": "fli-mcp"
    }
  }
}
```

> **Tip**: Run `which fli-mcp` to find the full path if needed.

## Available Tools

### `search_flights`

Search for flights between two airports on a specific date.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `origin` | string | Yes | - | Departure airport IATA code (e.g., 'JFK') |
| `destination` | string | Yes | - | Arrival airport IATA code (e.g., 'LHR') |
| `departure_date` | string | Yes | - | Travel date in YYYY-MM-DD format |
| `return_date` | string | No | null | Return date for round trips |
| `cabin_class` | string | No | ECONOMY | ECONOMY, PREMIUM_ECONOMY, BUSINESS, or FIRST |
| `max_stops` | string | No | ANY | ANY, NON_STOP, ONE_STOP, or TWO_PLUS_STOPS |
| `departure_window` | string | No | null | Time window in 'HH-HH' format (e.g., '6-20') |
| `airlines` | list | No | null | Filter by airline codes (e.g., ['BA', 'AA']) |
| `exclude_airlines` | list | No | null | Airline IATA codes to **exclude** from results |
| `alliance` | list | No | null | Restrict to ONEWORLD / SKYTEAM / STAR_ALLIANCE |
| `exclude_alliance` | list | No | null | Alliance(s) to **exclude** from results |
| `min_layover` | int | No | null | Minimum layover duration (minutes) |
| `max_layover` | int | No | null | Maximum layover duration (minutes) |
| `top_n` | int | No | 5 | Round-trip only: outbound options expanded into return-flight combinations (1-10) |
| `currency` | string | No | null | ISO 4217 code (`curr=`) — e.g. 'EUR', 'JPY' |
| `language` | string | No | null | BCP-47 language code (`hl=`) — e.g. 'en-GB' |
| `country` | string | No | null | ISO 3166-1 alpha-2 code (`gl=`) — e.g. 'GB' |
| `sort_by` | string | No | CHEAPEST | CHEAPEST, DURATION, DEPARTURE_TIME, or ARRIVAL_TIME |
| `passengers` | int | No | 1 | Number of adult passengers |
| `children` | int | No | 0 | Number of children (ages 2-11) |
| `infants_in_seat` | int | No | 0 | Number of infants (under 2) occupying their own seat |
| `infants_on_lap` | int | No | 0 | Number of lap infants (under 2, no seat) |

> **Passenger limits:** total travelers (`passengers + children + infants_in_seat +
> infants_on_lap`) must be between 1 and 9, and `infants_on_lap` cannot exceed
> `passengers` — Google Flights' own booking limits. An invalid mix returns
> `success: false` with the specific problem (e.g. `"Total passengers must be
> between 1 and 9 (got 10: ...)"`), not a generic error.
>
> **`top_n` cost model:** a round trip costs `1 + top_n` page fetches (one outbound
> search, plus one per outbound candidate expanded into return flights) — `top_n` is
> capped at 10 for that reason. Round-trip results all from one airline? Raise `top_n`,
> or `sort_by` differently: the default sort only ever expands the cheapest `top_n`
> outbounds, which are often the same carrier. `top_n` is ignored for one-way searches.

**Example Response:**

```json
{
  "success": true,
  "flights": [
    {
      "price": 450.00,
      "currency": "USD",
      "legs": [
        {
          "departure_airport": "JFK",
          "arrival_airport": "LHR",
          "departure_time": "2026-03-15T18:00:00",
          "arrival_time": "2026-03-16T06:30:00",
          "duration": 450,
          "airline": "BA",
          "flight_number": "178"
        }
      ],
      "booking_url": "https://www.google.com/travel/flights/booking?tfs=CBwQAh..."
    }
  ],
  "count": 5,
  "trip_type": "ONE_WAY",
  "booking_url": "https://www.google.com/travel/flights?q=Flights%20from%20JFK%20to%20LHR%20on%202026-03-15"
}
```

Each flight in `flights[]` carries a `booking_url` that deep-links directly to
that specific flight's booking page on Google Flights (pre-loaded itinerary, no
search step required). It carries the search's cabin class and passenger mix
too, so it opens priced for the same travelers as the search results. The
top-level `booking_url` is a broader search-page link (route + date
pre-filled) and is a reliable fallback. To retrieve per-vendor prices and
airline-direct booking links, pass the flight's `flight_number` (e.g.
`BA178`) to [`get_booking_options`](#get_booking_options).

### `search_dates`

Find the cheapest travel dates between two airports within a date range.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `origin` | string | Yes | - | Departure airport IATA code (e.g., 'JFK') |
| `destination` | string | Yes | - | Arrival airport IATA code (e.g., 'LHR') |
| `start_date` | string | Yes | - | Start of date range in YYYY-MM-DD format |
| `end_date` | string | Yes | - | End of date range in YYYY-MM-DD format |
| `trip_duration` | int | No | 3 | Trip duration in days (for round-trips) |
| `is_round_trip` | bool | No | false | Search for round-trip flights |
| `cabin_class` | string | No | ECONOMY | ECONOMY, PREMIUM_ECONOMY, BUSINESS, or FIRST |
| `max_stops` | string | No | ANY | ANY, NON_STOP, ONE_STOP, or TWO_PLUS_STOPS |
| `departure_window` | string | No | null | Time window in 'HH-HH' format (e.g., '6-20') |
| `airlines` | list | No | null | Filter by airline codes (e.g., ['BA', 'AA']) |
| `exclude_airlines` | list | No | null | Airline IATA codes to **exclude** |
| `alliance` | list | No | null | Restrict to ONEWORLD / SKYTEAM / STAR_ALLIANCE |
| `exclude_alliance` | list | No | null | Alliance(s) to **exclude** |
| `min_layover` | int | No | null | Minimum layover duration (minutes) |
| `max_layover` | int | No | null | Maximum layover duration (minutes) |
| `currency` | string | No | null | ISO 4217 currency code (`curr=`) |
| `language` | string | No | null | BCP-47 language code (`hl=`) |
| `country` | string | No | null | ISO 3166-1 alpha-2 country (`gl=`) |
| `sort_by_price` | bool | No | false | Sort results by price (lowest first) |
| `passengers` | int | No | 1 | Number of adult passengers |
| `children` | int | No | 0 | Number of children (ages 2-11) |
| `infants_in_seat` | int | No | 0 | Number of infants (under 2) occupying their own seat |
| `infants_on_lap` | int | No | 0 | Number of lap infants (under 2, no seat) |

> **Passenger limits:** same as `search_flights` — total travelers 1-9, and
> `infants_on_lap` cannot exceed `passengers`.

**Example Response:**

```json
{
  "success": true,
  "dates": [
    {
      "date": "2026-03-15",
      "price": 350.00,
      "currency": "USD",
      "return_date": null,
      "booking_url": "https://www.google.com/travel/flights?q=Flights%20from%20JFK%20to%20LHR%20on%202026-03-15"
    },
    {
      "date": "2026-03-18",
      "price": 375.00,
      "currency": "USD",
      "return_date": null,
      "booking_url": "https://www.google.com/travel/flights?q=Flights%20from%20JFK%20to%20LHR%20on%202026-03-18"
    }
  ],
  "count": 30,
  "trip_type": "ONE_WAY",
  "date_range": "2026-03-01 to 2026-03-31"
}
```

Each date result carries a `booking_url` deep-linking to Google Flights for
that specific date (and return date for round trips).

### `get_booking_options`

Get bookable fares — vendor names, prices, and **direct booking URLs** — for a
single itinerary. The tool runs a fresh search, selects the flight identified
by `flight_numbers` (or the top result when omitted), and returns the
airline-direct and online-travel-agency options Google surfaces for it.

Use `search_flights` first to discover flight numbers, then call this tool to
find out where (and at what price) a specific flight can be booked.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `origin` | string | Yes | - | Departure airport IATA code (e.g., 'JFK') |
| `destination` | string | Yes | - | Arrival airport IATA code (e.g., 'LHR') |
| `departure_date` | string | Yes | - | Travel date in YYYY-MM-DD format |
| `flight_numbers` | list | No | null | Ordered flight numbers identifying the itinerary (e.g. `['BA178']`, or `['AA100', 'AA200']` round-trip). Bare (`'178'`) or airline-prefixed (`'BA178'`). Omit to price the top result. |
| `return_date` | string | No | null | Return date for round trips |
| `cabin_class` | string | No | ECONOMY | ECONOMY, PREMIUM_ECONOMY, BUSINESS, or FIRST |
| `max_stops` | string | No | ANY | ANY, NON_STOP, ONE_STOP, or TWO_PLUS_STOPS |
| `passengers` | int | No | 1 | Number of adult passengers |
| `children` | int | No | 0 | Number of children (ages 2-11) |
| `infants_in_seat` | int | No | 0 | Number of infants (under 2) occupying their own seat |
| `infants_on_lap` | int | No | 0 | Number of lap infants (under 2, no seat) — cannot exceed `passengers` |
| `airlines` | list | No | null | Filter by airline codes (e.g., ['BA', 'AA']) |
| `exclude_basic_economy` | bool | No | false | Exclude basic economy fares. **Currently ignored by the search transport** (logged as a warning). |
| `departure_window` | string | No | null | Time window in 'HH-HH' format (e.g., '6-20') |
| `sort_by` | string | No | CHEAPEST | Sort order — matters when `flight_numbers` is omitted |
| `exclude_airlines` | list | No | null | Airline IATA codes to **exclude** |
| `alliance` / `exclude_alliance` | list | No | null | Restrict / exclude ONEWORLD, SKYTEAM, STAR_ALLIANCE |
| `min_layover` / `max_layover` | int | No | null | Layover duration bounds (minutes) |
| `top_n` | int | No | 5 | Round-trip only: outbound options the re-run search expands into return-flight combinations (1-10) |
| `emissions` | string | No | ALL | ALL or LESS. **Currently ignored by the search transport** (logged as a warning). |
| `checked_bags` | int | No | 0 | Checked bags included in price (0–2). **Currently ignored by the search transport** (logged as a warning). |
| `carry_on` | bool | No | false | Include carry-on bag fee in price. **Currently ignored by the search transport** (logged as a warning). |
| `currency` | string | No | null | ISO 4217 currency code (`curr=`) |
| `language` | string | No | null | BCP-47 language code (`hl=`) |
| `country` | string | No | null | ISO 3166-1 alpha-2 country (`gl=`) |

> **Tip:** Pass the **same filters you used for `search_flights`** — including
> `top_n` — so the re-run search reproduces the same result set. Otherwise — especially
> when `flight_numbers` is omitted — the priced "top result" may differ from the one the
> user saw, and a flight only visible at a higher `top_n` may not be found at all.

**Example Response:**

```json
{
  "success": true,
  "selected_flight": {
    "price": 450.00,
    "currency": "USD",
    "legs": [{ "airline": "BA", "flight_number": "178", "...": "..." }],
    "booking_url": "https://www.google.com/travel/flights/booking?tfs=CBwQAh..."
  },
  "options": [
    {
      "vendor_name": "British Airways",
      "vendor_code": "BA",
      "is_airline_direct": true,
      "price": 450.00,
      "currency": "USD",
      "booking_url": "https://www.britishairways.com/...",
      "google_click_url": "https://www.google.com/..."
    }
  ],
  "count": 1,
  "booking_url": "https://www.google.com/travel/flights?q=Flights%20from%20JFK%20to%20LHR%20on%202026-03-15"
}
```

`selected_flight.booking_url` is a deep link that opens the specific itinerary's
booking page directly on Google Flights (the `tfs` protobuf URL, no search step
required). The top-level `booking_url` is a broader search-page link.

When no flight matches `flight_numbers`, the response has `success: false` and
an `available_flights` list of the flight-number sequences that were found, so
you can retry with a valid identifier.

!!! note "Vendor fares may be empty"
    Google's booking endpoint often returns no per-vendor fares without a
    browser-minted session token. When that happens `options` is `[]` and the
    response carries a `note` — use `selected_flight.booking_url` to open the
    specific flight's booking page directly, or fall back to the top-level
    `booking_url` for the search page.

## Error Responses

Every tool's failure response (`success: false`) also carries `error_type` (a
stable string) and `retryable` (a bool), alongside the existing free-text
`error` message — so a caller can decide what to do next without
string-matching `error`. `http_error` responses additionally carry
`http_status` when the upstream status code is known. Classification is by
exception **type**, never by message text, so `error_type` will not change
out from under you even if wording on `error` does.

This vocabulary is **shared with the CLI**: `fli flights ... --format json`
and `fli dates ... --format json` errors use the exact same `error_type`
strings from the exact same classifier (`fli.core.errors.classify_error`),
so an agent or script that handles both surfaces only needs to learn the
vocabulary once.

| `error_type` | `retryable` | Meaning / what to do |
|---|---|---|
| `validation_error` | `false` | Bad input — unknown airport code, an invalid passenger mix, a date range over the 93-date cap, etc. Fix the request; retrying unchanged will fail again. |
| `unsupported_error` | `false` | The request is well-formed but this transport can't serve it (e.g. multi-city). Change the request. |
| `parse_error` | `false` | Google served a page fli couldn't read. Usually (not always) a regional consent/blocked interstitial. Not retryable as-is; set `FLI_SOCS_COOKIE` (EU/EEA) and retry — don't just retry the same request unchanged. |
| `rejected_error` | `false` | Google refused the RPC outright (e.g. `get_booking_options`'s `GetBookingResults` call today). Deterministic; retrying the same request will not help. |
| `timeout` | `true` | The request to Google Flights timed out. See retry guidance below. |
| `certificate_error` | `false` | TLS certificate verification failed, most often behind a TLS-intercepting corporate proxy. Deterministic; set `FLI_CA_BUNDLE` (or `CURL_CA_BUNDLE` / `REQUESTS_CA_BUNDLE`) to a CA bundle path and try again — retrying unchanged will not help. |
| `connection_error` | `true` | A network/DNS issue prevented reaching Google Flights. See retry guidance below. |
| `http_error` | `true` iff `http_status` is 429 or 5xx | Non-2xx HTTP response from Google; check `http_status`. See retry guidance below. |
| `search_error` | `false` | Any other typed search-client failure not covered above. |
| `unexpected_error` | `false` | An unclassified exception — most likely a bug, worth reporting. |

!!! warning "Retry guidance for `retryable: true`"
    The client has **already retried internally** with backoff before
    raising (see the `tenacity`-based retry in `fli/search/client.py`). A
    caller that sees `retryable: true` should retry **at most once or
    twice more**, with its own exponential backoff measured in **seconds**
    (not milliseconds) between attempts — not hammer the endpoint
    immediately. `http_status: 429` specifically is Google telling you to
    slow down — back off more, not less.

**Example error response:**

```json
{
  "success": false,
  "error": "Search failed: Timed out talking to Google Flights (www.google.com). ...",
  "flights": [],
  "error_type": "timeout",
  "retryable": true
}
```

## Available Prompts

The MCP server also provides prompt templates to help guide searches:

### `search-direct-flight`

Generates a tool call to find direct flights between two airports.

**Arguments:**
- `origin` - Departure airport IATA code (required)
- `destination` - Arrival airport IATA code (required)
- `date` - Departure date in YYYY-MM-DD format (optional)
- `prefer_non_stop` - Set to true to prefer nonstop flights (optional)

### `find-budget-window`

Suggests the cheapest travel dates for a route within a flexible window.

**Arguments:**
- `origin` - Departure airport IATA code (required)
- `destination` - Arrival airport IATA code (required)
- `start_date` - Start of the travel window (optional)
- `end_date` - End of the travel window (optional)
- `duration` - Desired trip length in days (optional)

## Configuration

The MCP server can be configured via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `FLI_MCP_DEFAULT_PASSENGERS` | Default number of adult passengers | 1 |
| `FLI_MCP_DEFAULT_CURRENCY` | Currency code for results | USD |
| `FLI_MCP_DEFAULT_CABIN_CLASS` | Default cabin class | ECONOMY |
| `FLI_MCP_DEFAULT_SORT_BY` | Default sorting strategy | CHEAPEST |
| `FLI_MCP_DEFAULT_DEPARTURE_WINDOW` | Default departure window (HH-HH) | null |
| `FLI_MCP_MAX_RESULTS` | Maximum results returned | null (no limit) |

The underlying Google Flights HTTP client (shared with the CLI, not
`FLI_MCP_`-prefixed) also honors these variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `FLI_TIMEOUT` | Request timeout in seconds | 60 |
| `FLI_SOCS_COOKIE` | Consent cookie sent to skip Google's EU/EEA interstitial; set empty to send none | a pre-accepted value |
| `FLI_CA_BUNDLE` | Path to a PEM CA bundle for networks with a custom certificate authority (e.g. a TLS-intercepting corporate proxy) | unset |
| `CURL_CA_BUNDLE` | Fallback CA bundle path, used when `FLI_CA_BUNDLE` is unset | unset |
| `REQUESTS_CA_BUNDLE` | Fallback CA bundle path, used when the two above are unset | unset |

If a search fails with `error_type: "certificate_error"`, configure one of
the CA bundle variables above instead of disabling TLS verification. These
are read once per worker thread, the first time that thread makes a
request — for a long-running MCP server process, restart it after changing
one so already-created sessions pick up the new value.

## Example Conversations

Once configured with Claude Desktop, you can have natural conversations:

> **User**: "Find me flights from New York to London next month"
> 
> **Claude**: *Uses `search_flights` with origin=JFK, destination=LHR*

> **User**: "What are the cheapest dates to fly to Tokyo from San Francisco in April?"
> 
> **Claude**: *Uses `search_dates` with origin=SFO, destination=NRT, start_date and end_date in April*

> **User**: "Search for business class, non-stop flights from LAX to Paris on March 15th"
> 
> **Claude**: *Uses `search_flights` with cabin_class=BUSINESS, max_stops=NON_STOP*
