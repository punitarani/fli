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
| `currency` | string | No | null | ISO 4217 code (`curr=`) — e.g. 'EUR', 'JPY' |
| `language` | string | No | null | BCP-47 language code (`hl=`) — e.g. 'en-GB' |
| `country` | string | No | null | ISO 3166-1 alpha-2 code (`gl=`) — e.g. 'GB' |
| `sort_by` | string | No | CHEAPEST | CHEAPEST, DURATION, DEPARTURE_TIME, or ARRIVAL_TIME |
| `passengers` | int | No | 1 | Number of adult passengers |

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
search step required). The top-level `booking_url` is a broader search-page
link (route + date pre-filled) and is a reliable fallback. To retrieve
per-vendor prices and airline-direct booking links, pass the flight's
`flight_number` (e.g. `BA178`) to [`get_booking_options`](#get_booking_options).

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
| `airlines` | list | No | null | Filter by airline codes (e.g., ['BA', 'AA']) |
| `exclude_basic_economy` | bool | No | false | Exclude basic economy fares |
| `departure_window` | string | No | null | Time window in 'HH-HH' format (e.g., '6-20') |
| `sort_by` | string | No | CHEAPEST | Sort order — matters when `flight_numbers` is omitted |
| `exclude_airlines` | list | No | null | Airline IATA codes to **exclude** |
| `alliance` / `exclude_alliance` | list | No | null | Restrict / exclude ONEWORLD, SKYTEAM, STAR_ALLIANCE |
| `min_layover` / `max_layover` | int | No | null | Layover duration bounds (minutes) |
| `emissions` | string | No | ALL | ALL or LESS |
| `checked_bags` | int | No | 0 | Checked bags included in price (0–2) |
| `carry_on` | bool | No | false | Include carry-on bag fee in price |
| `currency` | string | No | null | ISO 4217 currency code (`curr=`) |
| `language` | string | No | null | BCP-47 language code (`hl=`) |
| `country` | string | No | null | ISO 3166-1 alpha-2 country (`gl=`) |

> **Tip:** Pass the **same filters you used for `search_flights`** so the re-run
> search reproduces the same result set. Otherwise — especially when
> `flight_numbers` is omitted — the priced "top result" may differ from the one
> the user saw.

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
