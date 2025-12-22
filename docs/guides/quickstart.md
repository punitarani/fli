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

1. Search for one-way flights:

```bash
fli flights JFK LHR 2025-06-01
```

2. Search for round trip flights:

```bash
fli flights JFK LHR 2025-06-01 --return 2025-06-15
```

3. Search with filters:

```bash
fli flights JFK LHR 2025-06-01 \
    --time 6-20 \             # Departure window (6 AM - 8 PM)
    --airlines BA KL \        # Airlines (British Airways, KLM)
    --class BUSINESS \        # Cabin class
    --stops NON_STOP          # Non-stop flights only
```

4. Find cheapest dates:

```bash
fli dates JFK LHR --from 2025-06-01 --to 2025-06-30
```

### MCP Server (for AI Assistants)

Run the MCP server for use with Claude Desktop or other MCP clients:

```bash
# Run on STDIO (for Claude Desktop)
fli-mcp

# Run over HTTP (for web integrations)
fli-mcp-http
```

See the [MCP Guide](mcp.md) for detailed configuration.

### Python API

1. Basic One-Way Flight Search:

```python
from fli.search import SearchFlights
from fli.models import (
    FlightSearchFilters, FlightSegment,
    Airport, SeatType, TripType, PassengerInfo
)

# Create flight segment
flight_segments = [
    FlightSegment(
        departure_airport=[[Airport.JFK, 0]],
        arrival_airport=[[Airport.LAX, 0]],
        travel_date="2025-06-01"
    )
]

# Create filters
filters = FlightSearchFilters(
    trip_type=TripType.ONE_WAY,
    passenger_info=PassengerInfo(adults=1),
    flight_segments=flight_segments,
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

2. Round Trip Flight Search:

```python
from fli.search import SearchFlights
from fli.models import (
    FlightSearchFilters, FlightSegment,
    Airport, TripType, PassengerInfo
)

# Create flight segments for round trip
flight_segments = [
    FlightSegment(
        departure_airport=[[Airport.JFK, 0]],
        arrival_airport=[[Airport.LAX, 0]],
        travel_date="2025-06-01"
    ),
    FlightSegment(
        departure_airport=[[Airport.LAX, 0]],
        arrival_airport=[[Airport.JFK, 0]],
        travel_date="2025-06-15"
    )
]

# Create filters
filters = FlightSearchFilters(
    trip_type=TripType.ROUND_TRIP,
    passenger_info=PassengerInfo(adults=1),
    flight_segments=flight_segments
)

# Search flights
search = SearchFlights()
results = search.search(filters)

# Process results - round trips return tuples of (outbound, return)
for outbound, return_flight in results:
    print(f"\nOutbound Flight:")
    for leg in outbound.legs:
        print(f"  {leg.airline.value} {leg.flight_number}")
        print(f"  {leg.departure_datetime} -> {leg.arrival_datetime}")
    
    print(f"\nReturn Flight:")
    for leg in return_flight.legs:
        print(f"  {leg.airline.value} {leg.flight_number}")
        print(f"  {leg.departure_datetime} -> {leg.arrival_datetime}")
    
    print(f"\nTotal Price: ${outbound.price + return_flight.price}")
```

3. Date Range Search:

```python
from fli.search import SearchDates
from fli.models import DateSearchFilters, Airport, FlightSegment, PassengerInfo

# Create filters
filters = DateSearchFilters(
    passenger_info=PassengerInfo(adults=1),
    flight_segments=[
        FlightSegment(
            departure_airport=[[Airport.JFK, 0]],
            arrival_airport=[[Airport.LAX, 0]],
            travel_date="2025-06-01",
        )
    ],
    from_date="2025-06-01",
    to_date="2025-06-30"
)

# Search dates
search = SearchDates()
results = search.search(filters)

# Process results
for date_price in results:
    print(f"Date: {date_price.date[0]}, Price: ${date_price.price}")
```

### Running Complete Examples

All the above code snippets are available as complete, runnable examples in the `examples/` directory:

```bash
# Run examples with uv (recommended)
uv run python examples/basic_one_way_search.py
uv run python examples/round_trip_search.py
uv run python examples/date_range_search.py

# Or install dependencies first
pip install pydantic curl_cffi httpx
python examples/basic_one_way_search.py
```

**Available Example Files:**

* `basic_one_way_search.py` - One-way flight search example
* `round_trip_search.py` - Round-trip flight search example
* `date_range_search.py` - Date range search example
* `complex_flight_search.py` - Advanced filtering example
* `error_handling_with_retries.py` - Robust error handling example

> 💡 **Tip**: Examples include automatic dependency checking and will guide you through installation if dependencies are missing.

## Next Steps

* Check out the [API Reference](../api/models.md) for detailed documentation
* See [Advanced Examples](../examples/advanced.md) for more complex use cases
* Read the [MCP Guide](mcp.md) for AI assistant integration
* Read about [Rate Limiting and Error Handling](../api/search.md#http-client)
