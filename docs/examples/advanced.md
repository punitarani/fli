# Advanced Examples

## Complex Flight Search

### Search with Multiple Filters

```python
from fli.models import (
    Airport, Airline, SeatType, MaxStops,
    PassengerInfo, TimeRestrictions, LayoverRestrictions
)
from fli.search import SearchFlights, SearchFlightsFilters

# Create detailed filters
filters = SearchFlightsFilters(
    departure_airport=Airport.JFK,
    arrival_airport=Airport.LHR,
    departure_date="2024-06-01",
    passenger_info=PassengerInfo(
        adults=2,
        children=1,
        infants_on_lap=1
    ),
    seat_type=SeatType.BUSINESS,
    stops=MaxStops.ONE_STOP_OR_FEWER,
    airlines=[Airline.BA, Airline.VS],  # British Airways and Virgin Atlantic
    max_duration=720,  # 12 hours in minutes
    layover_restrictions=LayoverRestrictions(
        airports=[Airport.BOS, Airport.ORD],  # Prefer these layover airports
        max_duration=180  # Maximum 3-hour layover
    )
)

search = SearchFlights()
results = search.search(filters)
```

### Search with Time Restrictions

```python
from fli.models import TimeRestrictions
from fli.search import SearchFlights, SearchFlightsFilters

# Create filters with time restrictions
filters = SearchFlightsFilters(
    departure_airport=Airport.JFK,
    arrival_airport=Airport.LAX,
    departure_date="2024-06-01",
    flight_segments=[
        FlightSegment(
            departure_airport=[[Airport.JFK, 0]],
            arrival_airport=[[Airport.LAX, 0]],
            travel_date="2024-06-01",
            time_restrictions=TimeRestrictions(
                earliest_departure=6,  # 6 AM
                latest_departure=10,  # 10 AM
                earliest_arrival=12,  # 12 PM
                latest_arrival=18  # 6 PM
            )
        )
    ]
)

search = SearchFlights()
results = search.search(filters)
```

## Advanced Date Search

### Search with Day Preferences

```python
from datetime import datetime, timedelta
from fli.models import DateSearchFilters, Airport, SeatType

# Create filters for weekends only
filters = DateSearchFilters(
    departure_airport=Airport.JFK,
    arrival_airport=Airport.LAX,
    from_date="2024-06-01",
    to_date="2024-06-30",
    seat_type=SeatType.PREMIUM_ECONOMY
)

search = SearchDates()
results = search.search(filters)

# Filter for weekends only
weekend_results = [
    r for r in results
    if r.date.weekday() >= 5  # Saturday = 5, Sunday = 6
]
```

### Price Tracking Over Time

```python
import time
from fli.models import DateSearchFilters, Airport
from fli.search import SearchDates


def track_prices(days=7):
    filters = DateSearchFilters(
        departure_airport=Airport.JFK,
        arrival_airport=Airport.LAX,
        from_date="2024-06-01",
        to_date="2024-06-07"
    )

    search = SearchDates()
    price_history = {}

    for _ in range(days):
        results = search.search(filters)

        # Store prices
        for result in results:
            date_str = result.date.strftime("%Y-%m-%d")
            if date_str not in price_history:
                price_history[date_str] = []
            price_history[date_str].append(result.price)

        # Wait for next check
        time.sleep(86400)  # Wait 24 hours

    return price_history
```

## Error Handling

### Handling Rate Limits and Retries

```python
from fli.search import SearchFlights, SearchFlightsFilters
from tenacity import retry, stop_after_attempt, wait_exponential


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=4, max=60))
def search_with_retry(filters: SearchFlightsFilters):
    search = SearchFlights()
    try:
        results = search.search(filters)
        if not results:
            raise ValueError("No results found")
        return results
    except Exception as e:
        print(f"Search failed: {str(e)}")
        raise  # Retry will handle this
```

## Working with Results

### Custom Result Processing

```python
from fli.models import FlightResult
from typing import List
import pandas as pd


def analyze_results(results: List[FlightResult]) -> pd.DataFrame:
    """Convert results to pandas DataFrame for analysis."""
    flights_data = []

    for flight in results:
        for leg in flight.legs:
            flights_data.append({
                'price': flight.price,
                'total_duration': flight.duration,
                'stops': flight.stops,
                'airline': leg.airline.value,
                'flight_number': leg.flight_number,
                'departure_airport': leg.departure_airport.value,
                'arrival_airport': leg.arrival_airport.value,
                'departure_time': leg.departure_datetime,
                'arrival_time': leg.arrival_datetime,
                'leg_duration': leg.duration
            })

    return pd.DataFrame(flights_data)
``` 