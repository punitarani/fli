# Fli Documentation

Fli provides direct, reverse-engineered access to Google Flights' API. Unlike
libraries that scrape HTML or drive a browser, Fli speaks the Flights API
directly — making it fast, reliable, and far less likely to break when the UI
changes.

Fli ships in two flavors with a shared design:

| | Package | Install | Docs |
|---|---|---|---|
| **Python** | [`flights`](https://pypi.org/project/flights/) (PyPI) | `pip install flights` | [Python Quick Start](python/quickstart.md) |
| **TypeScript** | [`fli-js`](https://www.npmjs.com/package/fli-js) (npm) | `bun add fli-js` | [TypeScript Quick Start](typescript/quickstart.md) |

The TypeScript package is a 1:1 port of the Python library — same models, same
filter encoding, same wire-format decoders.

## Key Features

* **Direct API access** — no scraping, no browser automation, no HTML parsing.
* **Rich search** — one-way, round-trip, and multi-city; cabin classes; stop
  and layover limits; airline/alliance include & exclude; currency and locale.
* **Cheapest-date search** — scan a flexible date window for the best fares.
* **Built-in protection** — 10 req/s rate limiting, automatic retries with
  exponential backoff, typed errors, and input validation.
* **MCP server** (Python) — search flights from AI assistants like Claude via
  the Model Context Protocol.

## Python in 30 seconds

```python
from datetime import datetime, timedelta
from fli.models import (
    Airport, FlightSearchFilters, FlightSegment,
    MaxStops, PassengerInfo, SeatType, SortBy,
)
from fli.search import SearchFlights

filters = FlightSearchFilters(
    passenger_info=PassengerInfo(adults=1),
    flight_segments=[
        FlightSegment(
            departure_airport=[[Airport.JFK, 0]],
            arrival_airport=[[Airport.LAX, 0]],
            travel_date=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
        )
    ],
    seat_type=SeatType.ECONOMY,
    stops=MaxStops.NON_STOP,
    sort_by=SortBy.CHEAPEST,
)

for flight in SearchFlights().search(filters) or []:
    print(f"${flight.price} — {flight.duration} min — {flight.stops} stop(s)")
```

## TypeScript in 30 seconds

```ts
import {
  Airport, FlightSearchFilters, FlightSegment,
  MaxStops, SearchFlights, SeatType, SortBy,
} from "fli-js";

const filters = new FlightSearchFilters({
  passenger_info: { adults: 1, children: 0, infants_in_seat: 0, infants_on_lap: 0 },
  flight_segments: [
    new FlightSegment({
      departure_airport: [[[Airport.JFK, 0]]],
      arrival_airport: [[[Airport.LAX, 0]]],
      travel_date: "2026-12-25",
    }),
  ],
  seat_type: SeatType.ECONOMY,
  stops: MaxStops.NON_STOP,
  sort_by: SortBy.CHEAPEST,
});

for (const flight of (await new SearchFlights().search(filters, { currency: "USD" })) ?? []) {
  console.log(`$${flight.price} — ${flight.duration} min — ${flight.stops} stop(s)`);
}
```

## Command line (Python)

```bash
pipx install flights

fli flights JFK LHR 2026-06-01 --class BUSINESS --stops NON_STOP
fli dates JFK LHR --from 2026-06-01 --to 2026-06-30
```

## Where to next

* [Python Quick Start](python/quickstart.md) · [Python Examples](python/examples.md) · [Python API Reference](python/api/models.md)
* [TypeScript Quick Start](typescript/quickstart.md) · [TypeScript Examples](typescript/examples.md)
* [MCP Server Guide](guides/mcp.md) — flight search for AI assistants

## License

Fli is released under the MIT License. See the `LICENSE` file for details.
