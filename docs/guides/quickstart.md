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
fli search JFK LHR 2024-06-01
```

2. Search for round trip flights:

```bash
fli search JFK LHR 2024-06-01 --return 2024-06-15
```

3. Search with filters:

```bash
fli search JFK LHR 2024-06-01 \
    -t 6-20 \              # Time range (6 AM - 8 PM)
    -a BA KL \             # Airlines (British Airways, KLM)
    -c BUSINESS \          # Seat type
    -s 0                   # Non-stop flights only
```

4. Find cheapest dates:

```bash
fli cheap JFK LHR --from 2024-06-01 --to 2024-06-30
```

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
        travel_date="2024-06-01"
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
        travel_date="2024-06-01"
    ),
    FlightSegment(
        departure_airport=[[Airport.LAX, 0]],
        arrival_airport=[[Airport.JFK, 0]],
        travel_date="2024-06-15"
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

# Process results
for flight in results:
    print(f"\nOutbound Flight:")
    for leg in flight.outbound.legs:
        print(f"Flight: {leg.airline.value} {leg.flight_number}")
        print(f"Departure: {leg.departure_datetime}")
        print(f"Arrival: {leg.arrival_datetime}")
    
    print(f"\nReturn Flight:")
    for leg in flight.return_flight.legs:
        print(f"Flight: {leg.airline.value} {leg.flight_number}")
        print(f"Departure: {leg.departure_datetime}")
        print(f"Arrival: {leg.arrival_datetime}")
    
    print(f"\nTotal Price: ${flight.total_price}")
```

3. Date Range Search:

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