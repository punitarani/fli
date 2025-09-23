# Advanced Examples

This document contains advanced code examples demonstrating complex flight search scenarios. All examples are available as runnable scripts in the `examples/` directory.

## Running Examples

```bash
# Run with uv (recommended - handles dependencies automatically)
uv run python examples/complex_flight_search.py
uv run python examples/time_restrictions_search.py
uv run python examples/price_tracking.py

# Or install dependencies first, then run directly
pip install pydantic curl_cffi httpx pandas tenacity
python examples/complex_flight_search.py
```

> 💡 **Tip**: All example files include automatic dependency checking and will show helpful installation instructions if dependencies are missing.

## Complex Flight Search

### Search with Multiple Filters

```python
from fli.models import (
    Airport, Airline, SeatType, MaxStops, TripType,
    PassengerInfo, TimeRestrictions, LayoverRestrictions,
    FlightSearchFilters, FlightSegment
)
from fli.search import SearchFlights

# Create detailed filters
filters = FlightSearchFilters(
    trip_type=TripType.ONE_WAY,
    passenger_info=PassengerInfo(
        adults=2,
        children=1,
        infants_on_lap=1
    ),
    flight_segments=[
        FlightSegment(
            departure_airport=[[Airport.JFK, 0]],
            arrival_airport=[[Airport.LHR, 0]],
            travel_date="2024-06-01",
        )
    ],
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
from fli.models import (
    TimeRestrictions, Airport, TripType, 
    FlightSearchFilters, FlightSegment, PassengerInfo
)
from fli.search import SearchFlights

# Create filters with time restrictions
filters = FlightSearchFilters(
    trip_type=TripType.ONE_WAY,
    passenger_info=PassengerInfo(adults=1),
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
from fli.models import (
    DateSearchFilters, Airport, SeatType, TripType,
    FlightSegment, PassengerInfo
)
from fli.search import SearchDates

# Create filters for weekends only
filters = DateSearchFilters(
    trip_type=TripType.ONE_WAY,
    passenger_info=PassengerInfo(adults=1),
    flight_segments=[
        FlightSegment(
            departure_airport=[[Airport.JFK, 0]],
            arrival_airport=[[Airport.LAX, 0]],
            travel_date="2024-06-01",
        )
    ],
    from_date="2024-06-01",
    to_date="2024-06-30",
    seat_type=SeatType.PREMIUM_ECONOMY
)

search = SearchDates()
results = search.search(filters)

# Filter for weekends only
weekend_results = [
    r for r in results
    if r.date[0].weekday() >= 5  # Saturday = 5, Sunday = 6
]
```

### Price Tracking Over Time

```python
import time
from fli.models import (
    DateSearchFilters, Airport, PassengerInfo, FlightSegment
)
from fli.search import SearchDates


def track_prices(days=7):
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
        to_date="2024-06-07"
    )

    search = SearchDates()
    price_history = {}

    for _ in range(days):
        results = search.search(filters)

        # Store prices
        for result in results:
            date_str = result.date[0].strftime("%Y-%m-%d")
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
from fli.search import SearchFlights
from fli.models import FlightSearchFilters
from tenacity import retry, stop_after_attempt, wait_exponential


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=4, max=60))
def search_with_retry(filters: FlightSearchFilters):
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

### Complex Round Trip Search with Validations

```python
from fli.models import (
    Airport, Airline, SeatType, MaxStops,
    PassengerInfo, TimeRestrictions, TripType,
    FlightSegment, FlightSearchFilters
)
from fli.search import SearchFlights
from datetime import datetime, timedelta

# Create flight segments with time restrictions
outbound = FlightSegment(
    departure_airport=[[Airport.JFK, 0]],
    arrival_airport=[[Airport.LHR, 0]],
    travel_date="2024-06-01",
    time_restrictions=TimeRestrictions(
        earliest_departure=6,  # 6 AM
        latest_departure=12,   # 12 PM
        earliest_arrival=18,   # 6 PM
        latest_arrival=23      # 11 PM
    )
)

return_flight = FlightSegment(
    departure_airport=[[Airport.LHR, 0]],
    arrival_airport=[[Airport.JFK, 0]],
    travel_date="2024-06-15",
    time_restrictions=TimeRestrictions(
        earliest_departure=14,  # 2 PM
        latest_departure=20,    # 8 PM
        earliest_arrival=17,    # 5 PM
        latest_arrival=23       # 11 PM
    )
)

# Validate dates
today = datetime.now().date()
outbound_date = datetime.strptime(outbound.travel_date, "%Y-%m-%d").date()
return_date = datetime.strptime(return_flight.travel_date, "%Y-%m-%d").date()

if outbound_date <= today:
    raise ValueError("Outbound date must be in the future")
if return_date <= outbound_date:
    raise ValueError("Return date must be after outbound date")
if return_date - outbound_date > timedelta(days=30):
    raise ValueError("Trip duration cannot exceed 30 days")

# Create filters with complex requirements
filters = FlightSearchFilters(
    trip_type=TripType.ROUND_TRIP,
    passenger_info=PassengerInfo(
        adults=2,
        children=1,
        infants_on_lap=1
    ),
    flight_segments=[outbound, return_flight],
    stops=MaxStops.ONE_STOP_OR_FEWER,
    seat_type=SeatType.BUSINESS,
    airlines=[Airline.BA, Airline.VS],  # British Airways and Virgin Atlantic
    max_duration=720,  # 12 hours max flight time
    layover_restrictions=LayoverRestrictions(
        airports=[Airport.DUB, Airport.AMS],  # Preferred layover airports
        max_duration=180  # Maximum 3-hour layover
    )
)

search = SearchFlights()
results = search.search(filters)

# Process results with detailed information
for flight in results:
    print(f"\nTotal Price: ${flight.total_price}")
    
    print("\nOutbound Flight:")
    for leg in flight.outbound.legs:
        print(f"Flight: {leg.airline.value} {leg.flight_number}")
        print(f"From: {leg.departure_airport.value} at {leg.departure_datetime}")
        print(f"To: {leg.arrival_airport.value} at {leg.arrival_datetime}")
        print(f"Duration: {leg.duration} minutes")
        if leg.layover_duration:
            print(f"Layover: {leg.layover_duration} minutes")
    
    print("\nReturn Flight:")
    for leg in flight.return_flight.legs:
        print(f"Flight: {leg.airline.value} {leg.flight_number}")
        print(f"From: {leg.departure_airport.value} at {leg.departure_datetime}")
        print(f"To: {leg.arrival_airport.value} at {leg.arrival_datetime}")
        print(f"Duration: {leg.duration} minutes")
        if leg.layover_duration:
            print(f"Layover: {leg.layover_duration} minutes")
```

### Advanced Date Search with Validation

```python
from fli.models import (
    DateSearchFilters, Airport, TripType,
    FlightSegment, PassengerInfo, SeatType, TimeRestrictions
)
from fli.search import SearchDates
from datetime import datetime, timedelta

def validate_dates(from_date: str, to_date: str, min_stay: int, max_stay: int):
    """Validate date ranges for round trip searches."""
    start = datetime.strptime(from_date, "%Y-%m-%d").date()
    end = datetime.strptime(to_date, "%Y-%m-%d").date()
    today = datetime.now().date()
    
    if start <= today:
        raise ValueError("Start date must be in the future")
    if end <= start:
        raise ValueError("End date must be after start date")
    if end - start > timedelta(days=180):
        raise ValueError("Date range cannot exceed 180 days")
    if min_stay < 1:
        raise ValueError("Minimum stay must be at least 1 day")
    if max_stay > 30:
        raise ValueError("Maximum stay cannot exceed 30 days")
    if min_stay > max_stay:
        raise ValueError("Minimum stay cannot be greater than maximum stay")

# Create flight segments for date search
segments = [
    FlightSegment(
        departure_airport=[[Airport.JFK, 0]],
        arrival_airport=[[Airport.LAX, 0]],
        time_restrictions=TimeRestrictions(
            earliest_departure=9,   # 9 AM
            latest_departure=18,    # 6 PM
        )
    )
]

# Validate and create filters
from_date = "2024-06-01"
to_date = "2024-06-30"
min_stay = 2
max_stay = 4

validate_dates(from_date, to_date, min_stay, max_stay)

filters = DateSearchFilters(
    trip_type=TripType.ROUND_TRIP,
    passenger_info=PassengerInfo(adults=1),
    flight_segments=segments,
    from_date=from_date,
    to_date=to_date,
    min_stay_days=min_stay,
    max_stay_days=max_stay,
    seat_type=SeatType.ECONOMY
)

search = SearchDates()
results = search.search(filters)

# Process results with weekend filtering
weekend_trips = []
for trip in results:
    outbound = datetime.strptime(trip.outbound_date, "%Y-%m-%d")
    return_date = datetime.strptime(trip.return_date, "%Y-%m-%d")
    
    # Check if outbound is on weekend (5 = Saturday, 6 = Sunday)
    if outbound.weekday() >= 5:
        stay_duration = (return_date - outbound).days
        weekend_trips.append({
            'outbound': trip.outbound_date,
            'return': trip.return_date,
            'duration': stay_duration,
            'price': trip.total_price
        })

# Sort by price
weekend_trips.sort(key=lambda x: x['price'])

# Display results
for trip in weekend_trips:
    print(f"\nWeekend Trip:")
    print(f"Outbound: {trip['outbound']} (Weekend)")
    print(f"Return: {trip['return']}")
    print(f"Duration: {trip['duration']} days")
    print(f"Total Price: ${trip['price']}") 
```
