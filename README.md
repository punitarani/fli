# Fli - Google Flights API Library

A Python library that provides programmatic access to Google Flights data through direct API interaction.

> **What makes `fli` special?**
> Unlike other flight search libraries that rely on web scraping, Fli directly interacts with Google Flights' API
> through reverse engineering.
> This means:
>
> * **Fast**: Direct API access means faster, more reliable results
> * **Zero Scraping**: No HTML parsing, no browser automation, just pure API interaction
> * **Reliable**: Less prone to breaking from UI changes
> * **Modular**: Clean library API for easy integration into your projects

## Installation

```bash
pip install flights
```

## Quick Start

```python
from datetime import datetime, timedelta
from fli.models import (
    Airport,
    PassengerInfo,
    SeatType,
    MaxStops,
    SortBy,
    FlightSearchFilters,
    FlightSegment,
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
    print(f"Price: ${flight.price}")
    print(f"Duration: {flight.duration} minutes")
    print(f"Stops: {flight.stops}")

    for leg in flight.legs:
        print(f"  Flight: {leg.airline.value} {leg.flight_number}")
        print(f"  From: {leg.departure_airport.value} at {leg.departure_datetime}")
        print(f"  To: {leg.arrival_airport.value} at {leg.arrival_datetime}")
```

## Features

* **Flight Search** - Search for flights on specific dates with detailed filters
* **Date Search** - Find the cheapest travel dates across flexible date ranges
* **Cabin Classes** - Economy, Premium Economy, Business, First
* **Smart Sorting** - Price, Duration, Departure Time, Arrival Time
* **Built-in Protection** - Rate limiting, automatic retries, input validation

## API Reference

### SearchFlights

Search for flights on a specific date.

```python
from fli.search import SearchFlights

search = SearchFlights()
results = search.search(filters)  # Returns list[FlightResult]
```

### SearchDates

Find cheapest travel dates within a date range.

```python
from fli.search import SearchDates

search = SearchDates()
results = search.search(filters)  # Returns list[DatePrice]
```

### Core Utilities

The `fli.core` module provides helper functions for building search filters:

```python
from fli.core import (
    resolve_airport,       # Convert IATA code to Airport enum
    parse_airlines,        # Convert airline codes to Airline list
    parse_cabin_class,     # Parse cabin class string to SeatType
    parse_max_stops,       # Parse stops preference
    parse_sort_by,         # Parse sort option
    parse_time_range,      # Parse "HH-HH" time range
    build_flight_segments, # Build FlightSegment list
    build_time_restrictions, # Build TimeRestrictions from time ranges
)
```

### Models

All data models are available from `fli.models`:

```python
from fli.models import (
    Airport,              # Airport IATA codes enum
    Airline,              # Airline IATA codes enum
    FlightSearchFilters,  # Flight search configuration
    DateSearchFilters,    # Date range search configuration
    FlightResult,         # Flight search result
    FlightLeg,            # Individual flight leg
    FlightSegment,        # Flight segment definition
    PassengerInfo,        # Passenger configuration
    SeatType,             # Cabin class enum
    MaxStops,             # Stop preference enum
    SortBy,               # Sort option enum
    TripType,             # Round-trip or one-way
    TimeRestrictions,     # Departure/arrival time windows
)
```

## Examples

See the [`examples/`](examples/) directory for comprehensive usage examples:

```bash
uv run python examples/basic_one_way_search.py
uv run python examples/round_trip_search.py
uv run python examples/date_range_search.py
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

## Development

```bash
# Clone the repository
git clone https://github.com/punitarani/fli.git
cd fli

# Install dependencies with uv
uv sync --extra dev

# Run tests
make test

# Run linting
make lint

# Format code
make format
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License -- see the LICENSE file for details.
