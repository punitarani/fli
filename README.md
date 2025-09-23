# 🛫 Fli - Flight Search MCP Server and Library

A powerful Python library that provides programmatic access to Google Flights data with an elegant CLI interface. Search
flights, find the best deals, and filter results with ease.

> 🚀 **What makes `fli` special?**
> Unlike other flight search libraries that rely on web scraping, Fli directly interacts with Google Flights' API
> through reverse engineering.
> This means:
>
> * **Fast**: Direct API access means faster, more reliable results
> * **Zero Scraping**: No HTML parsing, no browser automation, just pure API interaction
> * **Reliable**: Less prone to breaking from UI changes
> * **Modular**: Extensible architecture for easy customization and integration

## MCP Server

```bash
pipx install flights

# Run the MCP server on STDIO
fli-mcp

# Run the MCP server over HTTP (streamable)
fli-mcp-http  # serves at http://127.0.0.1:8000/mcp/
```

![MCP Demo](https://github.com/punitarani/fli/blob/main/data/mcp-demo.gif)

### Connecting to Claude Desktop

```json
{
  "mcpServers": {
    "fli": {
      "command": "/Users/<user>/.local/bin/fli-mcp"
    }
  }
}
```

> **Note**: Replace `<user>` with your actual username.
> You can also find the path to the MCP server by running `which fli-mcp` in your terminal.

## Quick Start

```bash
pip install flights
```

```bash
# Install using pipx (recommended for CLI)
pipx install flights

# Get started with CLI
fli --help
```

![CLI Demo](https://github.com/punitarani/fli/blob/main/data/cli-demo.png)

## Features

* 🔍 **Powerful Search**
  * One-way flight searches
  * Flexible departure times
  * Multi-airline support
  * Cabin class selection
  * Stop preferences
  * Custom result sorting

* 💺 **Cabin Classes**
  * Economy
  * Premium Economy
  * Business
  * First

* 🎯 **Smart Sorting**
  * Price
  * Duration
  * Departure Time
  * Arrival Time

* 🛡️ **Built-in Protection**
  * Rate limiting
  * Automatic retries
  * Comprehensive error handling
  * Input validation

## CLI Usage

### Search for Specific Flights

```bash
# Basic search
fli search JFK LHR 2025-10-25

# Advanced search with filters
fli search JFK LHR 2025-10-25 \
    -t 6-20 \              # Time range (6 AM - 8 PM)
    -a BA KL \             # Airlines (British Airways, KLM)
    -s BUSINESS \          # Seat type
    -x NON_STOP \          # Non-stop flights only
    -o DURATION            # Sort by duration
```

### Find Cheapest Dates

```bash
# Basic search for cheapest dates
fli cheap JFK LHR

# Advanced search with date range
fli cheap JFK LHR \
    --from 2025-01-01 \
    --to 2025-02-01 \
    --monday --friday      # Only Mondays and Fridays
```

### CLI Options

#### Search Command (`fli search`)

| Option           | Description             | Example                |
|------------------|-------------------------|------------------------|
| `-t, --time`     | Time range (24h format) | `6-20`                 |
| `-a, --airlines` | Airline codes           | `BA KL`                |
| `-s, --seat`     | Cabin class             | `ECONOMY`, `BUSINESS`  |
| `-x, --stops`    | Maximum stops           | `NON_STOP`, `ONE_STOP` |
| `-o, --sort`     | Sort results by         | `CHEAPEST`, `DURATION` |

#### Cheap Command (`fli cheap`)

| Option        | Description   | Example                |
|---------------|---------------|------------------------|
| `--from`      | Start date    | `2025-01-01`           |
| `--to`        | End date      | `2025-02-01`           |
| `-s, --seat`  | Cabin class   | `ECONOMY`, `BUSINESS`  |
| `-x, --stops` | Maximum stops | `NON_STOP`, `ONE_STOP` |
| `--[day]`     | Day filters   | `--monday`, `--friday` |

## MCP Server Integration

Fli includes a Model Context Protocol (MCP) server that allows AI assistants like Claude to search for flights directly. This enables natural language flight search through conversation.

### Running the MCP Server

```bash
# Run the MCP server on STDIO
fli-mcp

# Or with uv (for development)
uv run fli-mcp

# Or with make (for development)
make mcp

# Run the MCP server over HTTP (streamable)
fli-mcp-http  # serves at http://127.0.0.1:8000/mcp/
```

### Claude Desktop Configuration

To use the flight search capabilities in Claude Desktop, add this configuration to your `claude_desktop_config.json`:

**Location**: `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)

```json
{
  "mcpServers": {
    "flight-search": {
      "command": "fli-mcp",
      "args": []
    }
  }
}
```

After adding this configuration:

1. Restart Claude Desktop
2. You can now ask Claude to search for flights naturally:
   * "Find flights from JFK to LAX on December 25th"
   * "What are the cheapest dates to fly from NYC to London in January?"
   * "Search for business class flights from SFO to NRT with no stops"

### MCP Tools Available

The MCP server provides two main tools:

* **`search_flights`**: Search for specific flights with detailed filters
* **`search_cheap_flights`**: Find the cheapest dates across a flexible date range

## Python API Usage

### Basic Search Example

```python
from datetime import datetime, timedelta
from fli.models import (
    Airport,
    PassengerInfo,
    SeatType,
    MaxStops,
    SortBy,
    FlightSearchFilters,
    FlightSegment
)
from fli.search import SearchFlights

# Create search filters
filters = FlightSearchFilters(
    passenger_info=PassengerInfo(adults=1),
    flight_segments=[
        FlightSegment(
            departure_airport=[[Airport.JFK, 0]],
            arrival_airport=[[Airport.LAX, 0]],
            travel_date=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
        )
    ],
    seat_type=SeatType.ECONOMY,
    stops=MaxStops.NON_STOP,
    sort_by=SortBy.CHEAPEST,
)

# Search flights
search = SearchFlights()
flights = search.search(filters)

# Process results
for flight in flights:
    print(f"💰 Price: ${flight.price}")
    print(f"⏱️ Duration: {flight.duration} minutes")
    print(f"✈️ Stops: {flight.stops}")

    for leg in flight.legs:
        print(f"\n🛫 Flight: {leg.airline.value} {leg.flight_number}")
        print(f"📍 From: {leg.departure_airport.value} at {leg.departure_datetime}")
        print(f"📍 To: {leg.arrival_airport.value} at {leg.arrival_datetime}")
```

### Running Examples

We provide 11 comprehensive examples in the `examples/` directory that demonstrate various use cases:

```bash
# Run examples with uv (recommended)
uv run python examples/basic_one_way_search.py
uv run python examples/round_trip_search.py
uv run python examples/date_range_search.py

# Or install dependencies first, then run directly
pip install pydantic curl_cffi httpx
python examples/basic_one_way_search.py
```

**Available Examples:**

* `basic_one_way_search.py` - Simple one-way flight search
* `round_trip_search.py` - Round-trip flight booking
* `date_range_search.py` - Find cheapest dates
* `complex_flight_search.py` - Advanced filtering and multi-passenger
* `time_restrictions_search.py` - Time-based filtering
* `date_search_with_preferences.py` - Weekend filtering
* `price_tracking.py` - Price monitoring over time
* `error_handling_with_retries.py` - Robust error handling
* `result_processing.py` - Data analysis with pandas
* `complex_round_trip_validation.py` - Advanced round-trip with validation
* `advanced_date_search_validation.py` - Complex date search with filtering

> 💡 **Tip**: Examples include automatic dependency checking and will show helpful installation instructions if dependencies are missing.

## Examples

For comprehensive examples demonstrating all features, see the [`examples/`](examples/) directory:

```bash
# Quick test - run a simple example
uv run python examples/basic_one_way_search.py

# Run all examples to explore different features
uv run python examples/round_trip_search.py
uv run python examples/complex_flight_search.py
uv run python examples/price_tracking.py
```

**Example Categories:**

* **Basic Usage**: One-way, round-trip, date searches
* **Advanced Filtering**: Time restrictions, airlines, seat classes
* **Data Analysis**: Price tracking, result processing with pandas
* **Error Handling**: Retry logic, robust error management
* **Complex Scenarios**: Multi-passenger, validation, business rules

Each example is self-contained and includes automatic dependency checking with helpful installation instructions.

## Development

```bash
# Clone the repository
git clone https://github.com/punitarani/fli.git
cd fli

# Install dependencies with uv
uv sync --all-extras

# Run tests
uv run pytest

# Run linting
uv run ruff check .
uv run ruff format .

# Build documentation
uv run mkdocs serve

# Or use the Makefile for common tasks
make install-all  # Install all dependencies
make test         # Run tests
make lint         # Check code style
make format       # Format code
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License — see the LICENSE file for details.
