# fli

A Python package for searching flights using Google Flights data. Provides a clean interface for flight searches with
comprehensive filtering options.

## Installation

```bash
pip install git+https://github.com/punitarani/fli.git
```

## Quick Example

```python
from datetime import datetime, timedelta
from fli.models import (
    Airport,
    FlightSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
    TripType,
)
from fli.search import Search

# Create search filters
filters = FlightSearchFilters(
    trip_type=TripType.ONE_WAY,
    passenger_info=PassengerInfo(
        adults=1,
        children=0,
        infants_in_seat=0,
        infants_on_lap=0,
    ),
    flight_segments=[
        FlightSegment(
            departure_airport=[[Airport.JFK, 0]],
            arrival_airport=[[Airport.LAX, 0]],
            travel_date=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
        ),
    ],
    stops=MaxStops.NON_STOP,
    seat_type=SeatType.ECONOMY,
    sort_by=SortBy.CHEAPEST,
)

# Search flights
search = Search()
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

## Key Features

- Search flights with flexible filters
- Support for one-way trips
- Filter by stops, airlines, seat types
- Sort by price, duration, departure/arrival times
- Built-in rate limiting and retry mechanisms

## Search Options

- **Trip Types**: One-way trips
- **Passengers**: Adults, children, infants (lap/seat)
- **Cabin Classes**: Economy, Premium Economy, Business, First
- **Stops**: Non-stop, 1 stop, 2+ stops
- **Sort Options**: Price, Duration, Departure/Arrival time
- **Additional Filters**: Airlines, layover airports, price limits

## Models

The package provides several data models for structuring flight searches:

### Core Models

- `FlightSearchFilters`: Main search parameters
- `FlightSegment`: Individual flight segment details
- `PassengerInfo`: Passenger counts and types
- `FlightResult`: Search result containing flight details

### Enums

- `Airport`: Available airports
- `Airline`: Supported airlines
- `SeatType`: Cabin classes
- `MaxStops`: Stop restrictions
- `SortBy`: Result sorting options

## Error Handling

The search engine includes:

- Automatic retries for failed requests
- Rate limiting to prevent API throttling
