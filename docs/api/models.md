# Models Reference

## Core Models

### FlightSearchFilters

The main model for configuring flight searches.

```python
from fli.models import (
    FlightSearchFilters, FlightSegment, Airport,
    SeatType, MaxStops, SortBy, TripType, PassengerInfo
)

# Create flight segments for round trip
flight_segments = [
    FlightSegment(
        departure_airport=[[Airport.JFK, 0]],
        arrival_airport=[[Airport.LAX, 0]],
        travel_date="2024-06-01",
    ),
    FlightSegment(
        departure_airport=[[Airport.LAX, 0]],
        arrival_airport=[[Airport.JFK, 0]],
        travel_date="2024-06-15",
    )
]

filters = FlightSearchFilters(
    trip_type=TripType.ROUND_TRIP,
    passenger_info=PassengerInfo(adults=1),
    flight_segments=flight_segments,
    stops=MaxStops.NON_STOP,
    seat_type=SeatType.ECONOMY,
    sort_by=SortBy.CHEAPEST
)
```

**Validation Rules:**
- Flight segments must have different departure and arrival airports
- Travel dates cannot be in the past
- For round trips, exactly two flight segments are required
- Passenger counts must be valid (at least one adult)

::: fli.models.google_flights.FlightSearchFilters

### FlightResult

Represents a flight search result with complete details.

::: fli.models.google_flights.FlightResult

### FlightLeg

Represents a single flight segment with airline and timing details.

::: fli.models.google_flights.FlightLeg

## Enums

### SeatType

Available cabin classes for flights.

::: fli.models.google_flights.SeatType

### MaxStops

Maximum number of stops allowed in flight search.

::: fli.models.google_flights.MaxStops

### SortBy

Available sorting options for flight results.

::: fli.models.google_flights.SortBy

### TripType

Type of trip for flight search.

::: fli.models.google_flights.TripType

## Support Models

### PassengerInfo

Configuration for passenger counts.

::: fli.models.google_flights.PassengerInfo

### TimeRestrictions

Time constraints for flight departure and arrival.

::: fli.models.google_flights.TimeRestrictions

### PriceLimit

Price constraints for flight search.

::: fli.models.google_flights.PriceLimit 
