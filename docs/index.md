# Welcome to Fli Documentation

Fli is a powerful Python library that provides direct access to Google Flights' API through reverse engineering. Unlike
other flight search libraries that rely on web scraping, Fli offers a clean, fast, and reliable way to search for
flights and analyze pricing data.

## Key Features

### 🚀 Direct API Access

- No web scraping or browser automation
- Fast and reliable results
- Less prone to breaking from UI changes
- Clean, modular architecture

### 🔍 Search Capabilities

- One-way flight searches
- Flexible departure times
- Multi-airline support
- Various cabin classes
- Stop preferences
- Custom result sorting

### 💰 Price Analysis

- Search across date ranges
- Find cheapest dates to fly
- Price tracking and analysis
- Flexible date options

## Quick Start

### Installation

```bash
# Install using pip
pip install git+https://github.com/punitarani/fli.git

# Or install using pipx (recommended for CLI usage)
pipx install git+https://github.com/punitarani/fli.git
```

### Basic Usage

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
```

## Project Structure

The library is organized into several key modules:

- `models/`: Data models and enums
    - `google_flights.py`: Core data models
    - `airline.py`: Airline enums and data
    - `airport.py`: Airport enums and data

- `search/`: Search functionality
    - `flights.py`: Flight search implementation
    - `dates.py`: Date-based price search
    - `client.py`: HTTP client with rate limiting

## Contributing

We welcome contributions! Here's how you can help:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests: `poetry run pytest`
5. Submit a pull request

## License

This project is licensed under the MIT License. See the LICENSE file for details. 