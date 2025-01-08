# Quick Start Guide

This guide will help you get started with Fli quickly.

## Installation

### For Python Usage

```bash
pip install flights
```

### For CLI Usage

```bash
pipx install flights
```

## Basic Usage

### Command Line Interface

1. Search for flights on a specific date:

```bash
fli search JFK LHR 2024-06-01
```

2. Search with filters:

```bash
fli search JFK LHR 2024-06-01 \
    -t 6-20 \              # Time range (6 AM - 8 PM)
    -a BA KL \             # Airlines (British Airways, KLM)
    -s BUSINESS \          # Seat type
    -x NON_STOP           # Non-stop flights only
```

3. Find cheapest dates:

```bash
fli cheap JFK LHR --from 2024-06-01 --to 2024-06-30
```

### Python API

1. Basic Flight Search:

```python
from fli.search import SearchFlights, SearchFlightsFilters
from fli.models import Airport, SeatType

# Create filters
filters = SearchFlightsFilters(
    departure_airport=Airport.JFK,
    arrival_airport=Airport.LAX,
    departure_date="2024-06-01",
    seat_type=SeatType.ECONOMY
)

# Search flights
search = SearchFlights()
results = search.search(filters)

# Process results
for flight in results:
    print(f"Price: ${flight.price}")
    print(f"Duration: {flight.duration} minutes")
    for leg in flight.legs:
        print(f"Flight: {leg.airline.value} {leg.flight_number}")
```

2. Date Range Search:

```python
from fli.search import SearchDates
from fli.models import DateSearchFilters, Airport

# Create filters
filters = DateSearchFilters(
    departure_airport=Airport.JFK,
    arrival_airport=Airport.LAX,
    from_date="2024-06-01",
    to_date="2024-06-30"
)

# Search dates
search = SearchDates()
results = search.search(filters)

# Process results
for date_price in results:
    print(f"Date: {date_price.date}, Price: ${date_price.price}")
```

## Next Steps

- Check out the [API Reference](../api/models.md) for detailed documentation
- See [Advanced Examples](../examples/advanced.md) for more complex use cases
- Read about [Rate Limiting and Error Handling](../api/search.md#http-client) 