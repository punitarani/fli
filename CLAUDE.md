# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Fli is a Python library that provides programmatic access to Google Flights data through direct API interaction (reverse engineering). The project consists of:

- **CLI interface** (`fli/cli/`) - Typer-based command line tool with `search` and `cheap` commands
- **Core search engine** (`fli/search/`) - Flight and date search implementations using Google Flights API
- **Data models** (`fli/models/`) - Pydantic models for airports, airlines, and flight data structures
- **FastAPI server** (`fli/server/`) - REST API endpoints for flight search functionality

## Development Commands

### Core Development Tasks
```bash
# Install dependencies
poetry install

# Run tests (use these specific commands)
make test                    # Standard test suite
make test-fuzz              # Run fuzzing tests (pytest -vv --fuzz)
make test-all               # Run all tests (pytest -vv --all)
poetry run pytest -vv      # Alternative direct command

# Code quality
make lint                   # Check code with ruff
make lint-fix              # Auto-fix linting issues
make format                 # Format code with ruff
poetry run ruff check .     # Direct ruff check
poetry run ruff format .    # Direct ruff format

# Server development
make server                 # Run production server
make server-dev            # Run development server with reload
poetry run uvicorn fli.server.main:app --reload

# Documentation
make docs                   # Build MkDocs documentation
poetry run mkdocs serve     # Serve docs locally
poetry run mkdocs build     # Build static docs

# Dependencies
make requirements          # Generate requirements.txt from poetry.lock
```

### Test Configuration
- Tests use pytest with custom markers: `fuzz` (requires `--fuzz` flag) and `parallel` (for pytest-xdist)
- Test structure mirrors source code: `tests/cli/`, `tests/models/`, `tests/search/`, `tests/server/`
- Fuzzing tests are available but gated behind `--fuzz` flag

## Architecture Overview

### Core Components

1. **Client Layer** (`fli/search/client.py`)
   - Rate-limited HTTP client (10 req/sec) using curl-cffi for browser impersonation
   - Automatic retries with exponential backoff
   - Session management for Google Flights API communication

2. **Search Engine** (`fli/search/`)
   - `SearchFlights`: Core flight search using Google Flights API
   - `SearchDates`: Find cheapest dates within date ranges
   - Direct API integration (no web scraping)

3. **Data Models** (`fli/models/`)
   - **Base models**: `Airport`, `Airline` enums with IATA codes
   - **Google Flights models**: `FlightSearchFilters`, `FlightResult`, `FlightLeg`, etc.
   - **Filter models**: `TimeRestrictions`, `MaxStops`, `SeatType`, `SortBy`
   - All models use Pydantic for validation

4. **CLI Interface** (`fli/cli/`)
   - Typer-based with two main commands: `search` and `cheap`
   - Smart argument parsing (treats non-command args as search)
   - Rich console output for flight results

5. **Server API** (`fli/server/`)
   - FastAPI application with CORS middleware
   - Routes: `/flights/` and `/dates/` 
   - Request tracing middleware for monitoring

### Key Design Patterns

- **Direct API Access**: Uses reverse-engineered Google Flights API endpoints (not web scraping)
- **Rate Limiting**: Built-in 10 req/sec limit with automatic retry logic
- **Enum-Based Configuration**: Airports, airlines, seat types, etc. are strongly typed enums
- **Filter Pattern**: Search functionality uses comprehensive filter objects
- **Validation**: Pydantic models ensure data integrity throughout

## Key Files and Entry Points

- `fli/cli/main.py` - CLI entry point and command registration
- `fli/server/main.py` - FastAPI application setup and router registration  
- `fli/search/flights.py` - Core flight search implementation
- `fli/search/client.py` - HTTP client with rate limiting and retries
- `fli/models/google_flights/` - All Google Flights data structures
- `pyproject.toml` - Poetry configuration with script entry points

## Code Style and Standards

- **Linting**: Uses Ruff with pycodestyle, pyflakes, isort, flake8-bugbear, and pydocstyle
- **Formatting**: Ruff formatter with 100 character line length, 4-space indentation
- **Type Hints**: Python 3.12+ with full type annotations
- **Docstrings**: Google-style docstrings (configured in mkdocs.yml)
- **Testing**: pytest with asyncio support and parallel execution capabilities

## Important Implementation Notes

- Google Flights API integration requires careful rate limiting (handled automatically)
- Airport and airline codes use official IATA standards
- Flight search supports complex filters: time ranges, cabin classes, stop preferences, sorting
- Date search finds cheapest flights within flexible date ranges
- Server includes request tracing for monitoring API usage
- CLI supports both explicit commands and smart argument inference