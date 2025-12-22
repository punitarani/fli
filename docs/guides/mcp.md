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
          "departure_time": "2025-03-15T18:00:00",
          "arrival_time": "2025-03-16T06:30:00",
          "duration": 450,
          "airline": "BA",
          "flight_number": "BA178"
        }
      ]
    }
  ],
  "count": 5,
  "trip_type": "ONE_WAY"
}
```

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
| `sort_by_price` | bool | No | false | Sort results by price (lowest first) |
| `passengers` | int | No | 1 | Number of adult passengers |

**Example Response:**

```json
{
  "success": true,
  "dates": [
    {
      "date": "2025-03-15",
      "price": 350.00,
      "currency": "USD",
      "return_date": null
    },
    {
      "date": "2025-03-18",
      "price": 375.00,
      "currency": "USD",
      "return_date": null
    }
  ],
  "count": 30,
  "trip_type": "ONE_WAY",
  "date_range": "2025-03-01 to 2025-03-31"
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
