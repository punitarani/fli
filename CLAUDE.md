# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Fli is a Python library that provides programmatic access to Google Flights data through direct API interaction (reverse engineering). The project consists of:

- **CLI interface** (`fli/cli/`) - Typer-based command line tool with `flights` and `dates` commands
- **MCP server** (`fli/mcp/`) - Model Context Protocol server for AI assistant integration
- **Core utilities** (`fli/core/`) - Shared parsing and building utilities
- **Search engine** (`fli/search/`) - Flight and date search implementations using Google Flights API
- **Data models** (`fli/models/`) - Pydantic models for airports, airlines, and flight data structures
- **FastAPI server** (`fli/server/`) - REST API endpoints for flight search functionality

## Development Commands

### Core Development Tasks
```bash
# Install dependencies
uv sync --all-extras

# Run tests (use these specific commands)
make test                    # Standard test suite
make test-fuzz              # Run fuzzing tests (pytest -vv --fuzz)
make test-all               # Run all tests (pytest -vv --all)
uv run pytest -vv           # Alternative direct command

# Code quality
make lint                   # Check code with ruff
make lint-fix              # Auto-fix linting issues
make format                 # Format code with ruff
uv run ruff check .         # Direct ruff check
uv run ruff format .        # Direct ruff format

# MCP server
fli-mcp                     # Run MCP server on STDIO
fli-mcp-http               # Run MCP server over HTTP

# Documentation
make docs                   # Build MkDocs documentation
uv run mkdocs serve         # Serve docs locally
uv run mkdocs build         # Build static docs
```

### Test Configuration
- Tests use pytest with custom markers: `fuzz` (requires `--fuzz` flag) and `parallel` (for pytest-xdist)
- Test structure mirrors source code: `tests/cli/`, `tests/models/`, `tests/search/`, `tests/mcp/`
- Fuzzing tests are available but gated behind `--fuzz` flag

## Architecture Overview

### Core Components

1. **Core Layer** (`fli/core/`)
   - `parsers.py`: Shared parsing utilities (airports, airlines, stops, cabin class, time ranges)
   - `builders.py`: Filter building utilities (flight segments, time restrictions)
   - Used by both CLI and MCP for consistent parameter handling

2. **Client Layer** (`fli/search/client.py`)
   - Rate-limited HTTP client (10 req/sec) using curl-cffi for browser impersonation
   - Automatic retries with exponential backoff
   - Session management for Google Flights API communication

3. **Search Engine** (`fli/search/`)
   - `SearchFlights`: Core flight search using Google Flights API
   - `SearchDates`: Find cheapest dates within date ranges
   - Direct API integration (no web scraping)

4. **Data Models** (`fli/models/`)
   - **Base models**: `Airport`, `Airline` enums with IATA codes
   - **Google Flights models**: `FlightSearchFilters`, `FlightResult`, `FlightLeg`, etc.
   - **Filter models**: `TimeRestrictions`, `MaxStops`, `SeatType`, `SortBy`
   - All models use Pydantic for validation

5. **MCP Server** (`fli/mcp/`)
   - FastMCP-based server with two tools: `search_flights` and `search_dates`
   - Industry-standard parameter naming: `origin`, `destination`, `cabin_class`, `max_stops`
   - Prompt templates for guided searches
   - Configuration via environment variables

6. **CLI Interface** (`fli/cli/`)
   - Typer-based with two main commands: `flights` and `dates`
   - Smart argument parsing (treats non-command args as flights)
   - Rich console output for flight results

### Key Design Patterns

- **Direct API Access**: Uses reverse-engineered Google Flights API endpoints (not web scraping)
- **Rate Limiting**: Built-in 10 req/sec limit with automatic retry logic
- **Enum-Based Configuration**: Airports, airlines, seat types, etc. are strongly typed enums
- **Filter Pattern**: Search functionality uses comprehensive filter objects
- **Shared Utilities**: Core parsing/building logic shared between CLI and MCP
- **Validation**: Pydantic models ensure data integrity throughout

## Key Files and Entry Points

- `fli/cli/main.py` - CLI entry point and command registration
- `fli/mcp/server.py` - MCP server with `search_flights` and `search_dates` tools
- `fli/core/parsers.py` - Shared parsing utilities
- `fli/core/builders.py` - Shared filter building utilities
- `fli/search/flights.py` - Core flight search implementation
- `fli/search/client.py` - HTTP client with rate limiting and retries
- `fli/models/google_flights/` - All Google Flights data structures
- `pyproject.toml` - Package configuration with script entry points

## MCP Tool Reference

### `search_flights`
Search for flights on a specific date.

**Key Parameters:**
- `origin` / `destination` - Airport IATA codes
- `departure_date` / `return_date` - Dates in YYYY-MM-DD format
- `cabin_class` - ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST
- `max_stops` - ANY, NON_STOP, ONE_STOP, TWO_PLUS_STOPS
- `departure_window` - Time range in 'HH-HH' format
- `airlines` - List of airline IATA codes
- `sort_by` - CHEAPEST, DURATION, DEPARTURE_TIME, ARRIVAL_TIME

### `search_dates`
Find cheapest travel dates within a range.

**Key Parameters:**
- `origin` / `destination` - Airport IATA codes
- `start_date` / `end_date` - Date range in YYYY-MM-DD format
- `trip_duration` - Number of days for round trips
- `is_round_trip` - Boolean for round-trip search
- `cabin_class`, `max_stops`, `departure_window`, `airlines` - Same as above
- `sort_by_price` - Boolean to sort by price

## Code Style and Standards

- **Linting**: Uses Ruff with pycodestyle, pyflakes, isort, flake8-bugbear, and pydocstyle
- **Formatting**: Ruff formatter with 100 character line length, 4-space indentation
- **Type Hints**: Python 3.10+ with full type annotations
- **Docstrings**: Google-style docstrings (configured in mkdocs.yml)
- **Testing**: pytest with asyncio support and parallel execution capabilities

## Important Implementation Notes

- Google Flights API integration requires careful rate limiting (handled automatically)
- Airport and airline codes use official IATA standards
- Flight search supports complex filters: time ranges, cabin classes, stop preferences, sorting
- Date search finds cheapest flights within flexible date ranges
- MCP server uses industry-standard naming: `origin`/`destination`, `cabin_class`, `max_stops`
- Core utilities ensure consistent parsing between CLI and MCP interfaces
