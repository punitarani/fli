# Search API Reference

## Flight Search

The main search functionality for finding specific flights.

### SearchFlights

::: fli.search.flights.SearchFlights

### SearchFlightsFilters

A simplified interface for flight search parameters.

::: fli.search.flights.SearchFlightsFilters

## Date Search

Search functionality for finding the cheapest dates to fly.

### SearchDates

::: fli.search.dates.SearchDates

### DatePrice

::: fli.search.dates.DatePrice

## Examples

### Basic Flight Search

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
```

### Date Range Search

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
```

## HTTP Client

The underlying HTTP client used for API requests.

### Client

::: fli.search.client.Client 