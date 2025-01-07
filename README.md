# fli

A Python package for searching flights using Google Flights data.
Provides a clean interface for flight searches with comprehensive filtering options.

Simply get started with the CLI by running:

```bash
pipx install git+https://github.com/punitarani/fli.git
fli --help
```

## Installation

```bash
pip install git+https://github.com/punitarani/fli.git
```

## CLI Usage

[![CLI Demo](data/cli-demo.png)](data/cli-demo.png)

The package provides a command-line interface for quick flight searches:

```bash
# Basic flight search
fli search JFK LHR 2025-10-25

# Search with time range
fli search JFK LHR 2025-10-25 -t 6-20

# Search with specific airlines
fli search JFK LHR 2025-10-25 --airlines BA KL

# Full example with all options
fli search JFK LHR 2025-10-25 -t 6-20 -a BA KL -s BUSINESS -x NON_STOP -o DURATION

# Find cheapest dates to fly
fli cheap JFK LHR

# Find cheapest dates with date range
fli cheap JFK LHR --from 2025-01-01 --to 2025-02-01

# Find cheapest dates for specific days
fli cheap JFK LHR --monday --friday  # Only Mondays and Fridays
```

### CLI Commands

#### Search Command

Search for specific flight dates with detailed options:

- `-t, --time`: Time range in 24h format (e.g., 6-20)
- `-a, --airlines`: List of airline codes (e.g., BA KL)
- `-s, --seat`: Seat type (ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST)
- `-x, --stops`: Maximum stops (ANY, NON_STOP, ONE_STOP, TWO_PLUS_STOPS)
- `-o, --sort`: Sort results by (CHEAPEST, DURATION, DEPARTURE_TIME, ARRIVAL_TIME)

#### Cheap Command

Find the cheapest dates to fly between airports:

- `--from`: Start date (YYYY-MM-DD)
- `--to`: End date (YYYY-MM-DD)
- `-s, --seat`: Seat type (ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST)
- `-x, --stops`: Maximum stops (ANY, NON_STOP, ONE_STOP, TWO_PLUS_STOPS)
- Day filters: `--monday`, `--tuesday`, `--wednesday`, `--thursday`, `--friday`, `--saturday`, `--sunday`

### Help

Get detailed help with:

```bash
fli --help
fli search --help
fli cheap --help
```

## Python API Usage

You can also use the package programmatically:

```python
from datetime import datetime, timedelta
from fli.models import (
    Airport,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
)
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
    print(f"Price: ${flight.price}")
    print(f"Duration: {flight.duration} minutes")
    print(f"Stops: {flight.stops}")

    for leg in flight.legs:
        print(f"\nFlight: {leg.airline.value} {leg.flight_number}")
        print(f"From: {leg.departure_airport.value} at {leg.departure_datetime}")
        print(f"To: {leg.arrival_airport.value} at {leg.arrival_datetime}")
```

## Features

- **Search Options**:
    - One-way flights
    - Flexible departure times
    - Multiple airlines
    - Various cabin classes
    - Stop preferences
    - Custom sorting

- **Cabin Classes**:
    - Economy
    - Premium Economy
    - Business
    - First

- **Sort Options**:
    - Price
    - Duration
    - Departure Time
    - Arrival Time

- **Built-in Features**:
    - Rate limiting
    - Automatic retries
    - Error handling
    - Beautiful CLI output

## Error Handling

The package includes comprehensive error handling:

- Input validation
- Rate limiting
- Automatic retries for failed requests
- Clear error messages

## Development

```bash
# Install development dependencies
poetry install

# Run tests
poetry run pytest

# Run linting
poetry run ruff check .
poetry run ruff format .
```
