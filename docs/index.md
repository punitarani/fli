# Welcome to Fli Documentation

Fli is a powerful Python library that provides direct access to Google Flights' API through reverse engineering. Unlike
other flight search libraries that rely on web scraping, Fli offers a clean, fast, and reliable way to search for
flights and analyze pricing data.

## Key Features

### 🚀 Direct API Access

* No web scraping or browser automation
* Fast and reliable results
* Less prone to breaking from UI changes
* Clean, modular architecture

### 🔍 Search Capabilities

* One-way and round-trip flight searches
* Flexible departure times
* Multi-airline support
* Various cabin classes
* Stop preferences
* Custom result sorting

### 💰 Price Analysis

* Search across date ranges
* Find cheapest dates to fly
* Price tracking and analysis
* Flexible date options

## Quick Start

### Installation

```bash
# Install using pip
pip install flights

# Or install using pipx (recommended for CLI usage)
pipx install flights
```

### Basic Usage

```python
from datetime import datetime, timedelta
from fli.models import (
    Airport, PassengerInfo, SeatType, MaxStops, SortBy,
    FlightSearchFilters, FlightSegment
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
```

### Running Examples

Complete, runnable examples are available in the `examples/` directory:

```bash
# Run with uv (recommended - handles dependencies)
uv run python examples/basic_one_way_search.py

# Or install dependencies first, then run
pip install pydantic curl_cffi httpx
python examples/basic_one_way_search.py
```

**Available Examples:**

* Basic one-way and round-trip searches
* Date range analysis and cheapest date finding
* Advanced filtering with time restrictions
* Error handling and retry logic
* Data analysis with pandas integration

> 💡 All examples include automatic dependency checking and helpful error messages.

## Project Structure

The library is organized into several key modules:

* `models/`: Data models and enums
  * `google_flights`: Core data models specific to Google Flights
  * `airline.py`: Airline enums and data
  * `airport.py`: Airport enums and data

* `search/`: Search functionality
  * `flights.py`: Flight search implementation
  * `dates.py`: Date-based price search
  * `client.py`: HTTP client with rate limiting

## Contributing

We welcome contributions! Here's how you can help:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests: `poetry run pytest`
5. Submit a pull request

## License

This project is licensed under the MIT License. See the LICENSE file for details.
