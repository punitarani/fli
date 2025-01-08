# Fli 🛫

A powerful Python library that provides programmatic access to Google Flights data with an elegant CLI interface. Search
flights, find the best deals, and filter results with ease.

> 🚀 **What makes `fli` special?**  
> Unlike other flight search libraries that rely on web scraping, Fli directly interacts with Google Flights' API
> through reverse engineering.
> This means:
> - **Fast**: Direct API access means faster, more reliable results
> - **Zero Scraping**: No HTML parsing, no browser automation, just pure API interaction
> - **Reliable**: Less prone to breaking from UI changes
> - **Modular**: Extensible architecture for easy customization and integration

[![CLI Demo](data/cli-demo.png)](data/cli-demo.png)

## Quick Start

```bash
pip install git+https://github.com/punitarani/fli.git
```

```bash
# Install using pipx (recommended to use CLI)
pipx install git+https://github.com/punitarani/fli.git
```

```bash
# Get started with CLI
fli --help
```

## Features

- 🔍 **Powerful Search**
    - One-way flight searches
    - Flexible departure times
    - Multi-airline support
    - Cabin class selection
    - Stop preferences
    - Custom result sorting

- 💺 **Cabin Classes**
    - Economy
    - Premium Economy
    - Business
    - First

- 🎯 **Smart Sorting**
    - Price
    - Duration
    - Departure Time
    - Arrival Time

- 🛡️ **Built-in Protection**
    - Rate limiting
    - Automatic retries
    - Comprehensive error handling
    - Input validation

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

## Python API Usage

### Basic Search Example

```python
from datetime import datetime, timedelta
from fli.models import Airport, PassengerInfo, SeatType, MaxStops, SortBy
from fli.search import SearchFlights, SearchFlightsFilters

# Create search filters
filters = SearchFlightsFilters(
    departure_airport=Airport.JFK,
    arrival_airport=Airport.LAX,
    departure_date=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
    passenger_info=PassengerInfo(adults=1),
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

## Development

```bash
# Clone the repository
git clone https://github.com/punitarani/fli.git
cd fli

# Install dependencies with Poetry
poetry install

# Run tests
poetry run pytest

# Run linting
poetry run ruff check .
poetry run ruff format .

# Build documentation
poetry run mkdocs serve
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License — see the LICENSE file for details.
