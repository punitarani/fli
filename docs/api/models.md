# Models Reference

## Core Models

### FlightSearchFilters

The main model for configuring flight searches.

```python
from fli.models import FlightSearchFilters, SeatType, MaxStops, SortBy

filters = FlightSearchFilters(
    trip_type=TripType.ONE_WAY,
    passenger_info=PassengerInfo(adults=1),
    flight_segments=[...],
    stops=MaxStops.NON_STOP,
    seat_type=SeatType.ECONOMY,
    sort_by=SortBy.CHEAPEST
)
```

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