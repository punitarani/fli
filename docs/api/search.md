# Search API Reference

## Flight Search

The main search functionality for finding specific flights.

### SearchFlights

::: fli.search.flights.SearchFlights

### FlightSearchFilters

A simplified interface for flight search parameters.

::: fli.models.google\_flights.FlightSearchFilters

## Date Search

Search functionality for finding the cheapest dates to fly.

### SearchDates

::: fli.search.dates.SearchDates

### DatePrice

::: fli.search.dates.DatePrice

## Examples

### Basic Flight Search

```python
from fli.search import SearchFlights
from fli.models import Airport, SeatType, FlightSearchFilters, FlightSegment, PassengerInfo

# Create filters
filters = FlightSearchFilters(
    passenger_info=PassengerInfo(adults=1),
    flight_segments=[
        FlightSegment(
            departure_airport=[[Airport.JFK, 0]],
            arrival_airport=[[Airport.LAX, 0]],
            travel_date="2024-06-01",
        )
    ],
    seat_type=SeatType.ECONOMY
)

# Search flights
search = SearchFlights()
results = search.search(filters)
```

### Date Range Search

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
            travel_date="2024-06-01",
        )
    ],
    from_date="2024-06-01",
    to_date="2024-06-30"
)

# Search dates
search = SearchDates()
results = search.search(filters)
```

### Running These Examples

You can find complete, runnable versions of these examples in the `examples/` directory:

```bash
# Run with uv (recommended)
uv run python examples/basic_one_way_search.py
uv run python examples/date_range_search.py

# Or install dependencies and run directly
pip install pydantic curl_cffi httpx
python examples/basic_one_way_search.py
```

For more advanced examples, see:

* `examples/complex_flight_search.py` - Advanced filtering
* `examples/result_processing.py` - Data analysis
* `examples/error_handling_with_retries.py` - Robust error handling

> 💡 All examples include automatic dependency checking and helpful error messages.

## HTTP Client

The underlying HTTP client used for API requests.

### Client

::: fli.search.client.Client
