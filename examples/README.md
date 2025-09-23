# Fli Examples

This directory contains practical examples demonstrating various features of the Fli flight search library. Each example is a standalone Python script that you can run directly.

## Basic Examples

### [basic\_one\_way\_search.py](basic_one_way_search.py)

**Simple one-way flight search**

* Basic flight search between two airports
* Demonstrates core API usage
* Shows result processing and display

### [round\_trip\_search.py](round_trip_search.py)

**Round trip flight search**

* Search for outbound and return flights
* Process round trip results
* Handle flight combinations

### [date\_range\_search.py](date_range_search.py)

**Search across date ranges**

* Find cheapest dates to fly
* Date-based price comparison
* Flexible departure dates

## Advanced Examples

### [complex\_flight\_search.py](complex_flight_search.py)

**Multi-filter flight search**

* Multiple passengers (adults, children, infants)
* Airline preferences
* Layover restrictions
* Duration limits
* Business class search

### [time\_restrictions\_search.py](time_restrictions_search.py)

**Time-constrained searches**

* Departure time preferences
* Arrival time constraints
* Morning vs evening flights

### [date\_search\_with\_preferences.py](date_search_with_preferences.py)

**Advanced date filtering**

* Weekend-only flights
* Day-of-week filtering
* Custom date preferences

### [complex\_round\_trip\_validation.py](complex_round_trip_validation.py)

**Enterprise-level round trip search**

* Comprehensive date validation
* Complex passenger configurations
* Multi-airline preferences
* Layover optimization
* Time restrictions for both directions

### [advanced\_date\_search\_validation.py](advanced_date_search_validation.py)

**Validated date range searching**

* Date range validation
* Stay duration constraints
* Weekend trip optimization
* Round trip date searches

## Utility Examples

### [price\_tracking.py](price_tracking.py)

**Monitor price changes**

* Track prices over time
* Price history analysis
* Trend identification
* Deal alerting concepts

### [error\_handling\_with\_retries.py](error_handling_with_retries.py)

**Robust error handling**

* Retry logic implementation
* Rate limit handling
* Exponential backoff (with tenacity)
* Fallback strategies

### [result\_processing.py](result_processing.py)

**Advanced result analysis**

* Data format conversion
* Statistical analysis
* Pandas integration (optional)
* CSV export capabilities

## Running the Examples

### Prerequisites

```bash
# Install the main library
pip install flights

# For advanced examples with optional dependencies
pip install pandas tenacity
```

### Running Examples

**Recommended approach (using uv):**

```bash
# Run any example with uv (automatically handles dependencies)
uv run python examples/basic_one_way_search.py

# Or from the project root
uv run python -m examples.basic_one_way_search
```

**Alternative approaches:**

```bash
# Option 1: Install the package first
pip install flights
python examples/basic_one_way_search.py

# Option 2: Install dependencies manually
pip install pydantic curl_cffi httpx
python examples/basic_one_way_search.py

# Option 3: Use virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install pydantic curl_cffi httpx
python examples/basic_one_way_search.py
```

**Dependency checking:**
All examples now include automatic dependency checking. If you're missing required packages, you'll see a helpful error message with installation instructions.

### Customizing Examples

Each example includes:

* Clear documentation and comments
* Configurable parameters (airports, dates, etc.)
* Error handling
* Result formatting

Feel free to modify the examples for your specific use cases:

1. **Change airports**: Replace `Airport.JFK` and `Airport.LAX` with your preferred airports
2. **Adjust dates**: Update travel dates to your desired timeframe
3. **Modify filters**: Change passenger counts, seat types, airlines, etc.
4. **Customize output**: Modify the result processing to match your needs

## Example Categories

| Category | Examples | Key Features |
|----------|----------|--------------|
| **Basic** | `basic_one_way_search`, `round_trip_search`, `date_range_search` | Core functionality, simple usage |
| **Advanced** | `complex_flight_search`, `time_restrictions_search`, `date_search_with_preferences` | Multiple filters, constraints |
| **Enterprise** | `complex_round_trip_validation`, `advanced_date_search_validation` | Validation, complex requirements |
| **Utilities** | `price_tracking`, `error_handling_with_retries`, `result_processing` | Robust implementation, analysis |

## Common Patterns

### Airport Selection

```python
from fli.models import Airport

# Major US airports
Airport.JFK, Airport.LAX, Airport.ORD, Airport.DFW
Airport.SFO, Airport.BOS, Airport.MIA, Airport.SEA

# International airports  
Airport.LHR, Airport.CDG, Airport.NRT, Airport.SYD
```

### Date Handling

```python
from datetime import datetime, timedelta

# Future dates (required)
future_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

# Date ranges
from_date = "2024-06-01"
to_date = "2024-06-30"
```

### Passenger Configuration

```python
from fli.models import PassengerInfo

# Single traveler
PassengerInfo(adults=1)

# Family with children
PassengerInfo(adults=2, children=2, infants_on_lap=1)
```

## Support

For questions about the examples or the Fli library:

* Check the [main documentation](../docs/)
* Review the [API reference](../docs/api/)
* See [advanced usage patterns](../docs/examples/advanced.md)

## Contributing

Found an issue or want to add an example? Contributions are welcome!

* Ensure examples are well-documented
* Include error handling
* Test with various configurations
* Follow the existing code style
