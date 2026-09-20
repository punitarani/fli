# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Fli is a Python library that provides programmatic access to Google Flights data through direct API interaction (reverse engineering). The project consists of:

- **CLI interface** (`fli/cli/`) - Typer-based command line tool with `flights` and `dates` commands
- **MCP server** (`fli/mcp/`) - Model Context Protocol server for AI assistant integration
- **Core utilities** (`fli/core/`) - Shared parsing and building utilities
- **Search engine** (`fli/search/`) - Flight and date search implementations using Google Flights API
- **Data models** (`fli/models/`) - Pydantic models for airports, airlines, and flight data structures

## Development Commands

### Core Development Tasks
```bash
# Install dependencies
uv sync --all-extras

# Run tests (use these specific commands)
make test                    # Standard test suite (offline only)
make test-fuzz              # Run fuzzing tests (pytest -vv --fuzz)
make test-all               # Run all offline tests, including fuzz (pytest -vv --all)
make test-live              # Run the small, stable live tests (pytest -vv -m live --live)
make test-live-fuzz         # Also run the flakier fuzz-gated live test (opt-in only)
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
- Tests use pytest with custom markers: `fuzz` (requires `--fuzz` flag), `parallel` (for
  pytest-xdist), and `live` (requires `--live` flag). `--strict-markers` is set in `pytest.ini`,
  so a typo'd marker fails collection instead of silently running (or silently not being gated).
- Test structure mirrors source code: `tests/cli/`, `tests/models/`, `tests/search/`, `tests/mcp/`
- Fuzzing tests are available but gated behind `--fuzz` flag
- `live`-marked tests make real network calls to Google Flights (the fuzz case in
  `test_search_flights_fuzz.py`, all of `test_search_flights_new_filters_live.py`, the four
  search tests in `tests/mcp/test_mcp_server.py::TestMCPServer`, and a handful of
  historically-unmocked cases in `test_search_flights.py` / `test_search_dates.py`). They're
  skipped by default and **`--all` does not enable them** — `ci.yml` runs `pytest tests/ --all`,
  which stays fully offline so a flaky Google response never blocks a merge.
  - **How `--fuzz` / `--live` / `--all` interact**: each gate is independent and skip-only —
    `--all` enables `fuzz`-marked tests but deliberately does *not* enable `live`-marked ones (you
    always need `--live` for those), and `--live` alone does *not* enable `fuzz`-marked ones (a
    test marked both `fuzz` *and* `live`, i.e. the one case in `test_search_flights_fuzz.py`, needs
    **both** `--all` (or `--fuzz`) *and* `--live` together — `-m live --live` alone silently drops
    it from collection before the marker filter even runs).
  - `make test-live` (`pytest -m live --live`, no `--all`) runs the small, stable live set — the
    same set `.github/workflows/live-canary.yml` runs daily against the real network, which
    files/comments/closes a GitHub issue on failure/recovery instead of failing a build. It
    retries a single failure batch once (`--last-failed`) after a short pause before treating the
    run as failed, to absorb a lone transient page.
  - `make test-live-fuzz` (`pytest --all -m live --live tests/search/test_search_flights_fuzz.py`)
    additionally runs the 100-case fuzz-gated live test, which is opt-in for humans only — it
    measured ~11% per-case failures under a fast back-to-back burst in testing, well above the
    stable set's rate, so it is never scheduled.

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
   - FastMCP-based server with four tools: `search_flights`, `search_dates`, `get_booking_options`, `find_airports`
   - Industry-standard parameter naming: `origin`, `destination`, `cabin_class`, `max_stops`
   - Per-flight booking deep-link URLs (`tfs` protobuf) in every search result
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

## Search transport

Searches go through Google's public search page, not the
`FlightsFrontendService` RPC. Since 2026-08 `GetShoppingResults` and
`GetCalendarGraph` require an `x-goog-batchexecute-bgr` header that only the
page's JavaScript can produce, so the client issues
`GET https://www.google.com/travel/flights?tfs=<protobuf>` and reads the
`AF_initDataCallback` blob keyed `ds:1`. Request encoding lives in
`fli/search/_tfs.py` and `fli/search/_proto.py`.

Consequences to keep in mind when changing search code:

- `emissions`, `bags` and `exclude_basic_economy` have no `tfs` field and no
  post-hoc equivalent; `unsupported_filters()` names them and the caller warns.
- Airline include/exclude, price cap, max duration and departure windows are
  applied after fetching by `apply_client_side_filters()`; stops, cabin,
  passengers, alliances and layover bounds are encoded into the request.
- Multi-city raises `SearchUnsupportedError` — the page inlines no rows for it.
- `get_booking_options` hits `GetBookingResults`, which is still gated, so it
  currently raises `SearchRejectedError`. Booking deep links (`tfs`) are built
  offline and unaffected.
- A search returns fewer rows than the old RPC (~20-45), and client-side
  filtering is not back-filled.
- **Children and infants thin the results — sometimes to nothing.** Google
  prices those parties client-side, so the page inlines fewer itineraries for
  them, and in premium cabins often none (measured 2026-09: JFK→LHR economy
  23 rows for one adult, 16 with an infant; SFO→NRT business 9 rows for one
  or two adults, 0 with a child). Extra adults cost nothing. An empty result
  for such a search does not mean the route has no flights: `SearchFlights.search`
  / `SearchDates.search` log a warning (`SPARSE_PASSENGER_MIX_WARNING`), the
  MCP `search_flights` empty response carries the same text as `note`, and the
  CLI prints it under "No flights found." — an adults-only search shows the
  schedule.
- Date searches have no calendar grid: one page fetch per date, capped at
  `fli.search.dates.MAX_DATES_PER_SEARCH` (93) per `SearchDates.search`. At the
  cap that is several hundred MB of pages and parsed JSON at peak.
- `_SweepHealth` (`SWEEP_FAILURE_THRESHOLD`, 5) is the sweep's circuit breaker.
  It counts **only** payload-less pages — that failure is deterministic, so the
  untried dates will fail the same way; a timeout or connection error says
  nothing about them and deliberately does not count. It is armed only while no
  date has loaded a page and disarmed permanently by the first success, so a
  working sweep keeps the full retry budget for transient misses.
  Measured with the real backoff, it turns a fully blocked 93-date sweep from
  279 page fetches (up to 837 HTTP requests once the client's own retries
  multiply) into 42 in ~4s, bounded at
  (threshold + pool workers) x `PAGE_FETCH_ATTEMPTS` = 45 regardless of range —
  the bound scales with `configure_concurrency`.
  When it trips but prices still come back, `_collect` emits exactly one
  warning naming the skipped count: a truncated answer must never be silent.
- The breaker alone can't catch "1 loaded, 29 timeouts" — one loaded page,
  even empty, disarms it for good. So `_collect` also raises when 0 priced
  and at least half the attempted dates never loaded (`failed >= loaded`),
  without the `FLI_SOCS_COOKIE` hint (a page did load, so it isn't a consent
  wall). A minority of load failures with 0 results still returns `None`;
  a minority alongside partial results still returns those results; both
  log exactly one summary warning naming the counts.
- ~1 page in 60 arrives HTTP 200 with no `ds:1` blob. `fetch_payload` in
  `fli/search/_tfs.py` is the single fetch path for both flights and dates and
  retries exactly that case (`PAGE_FETCH_ATTEMPTS`, `PAGE_RETRY_BACKOFF`);
  HTTP errors and error-13 rejections are not retried there.
- `FLI_SOCS_COOKIE` overrides the pre-accepted `SOCS` consent cookie the client
  sends so EU/EEA IPs skip Google's consent interstitial; set it empty to send
  no cookie.

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
- `origin` / `destination` - Airport IATA codes (comma-separated for multi-airport)
- `departure_date` / `return_date` - Dates in YYYY-MM-DD format
- `cabin_class` - ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST
- `max_stops` - ANY, NON_STOP, ONE_STOP, TWO_PLUS_STOPS
- `departure_window` - Time range in 'HH-HH' format
- `airlines` / `exclude_airlines` - Include / exclude airline IATA codes
- `alliance` / `exclude_alliance` - Include / exclude ONEWORLD / SKYTEAM / STAR_ALLIANCE
- `min_layover` / `max_layover` - Layover duration bounds in minutes
- `top_n` - Round-trip only: outbound options expanded into return-flight
  combinations (default 5, 1-10). Cost is `1 + top_n` page fetches. Round-trip
  results all from one airline? Raise `top_n` (or `sort_by` differently) — the
  default sort only ever expands the cheapest `top_n` outbounds, which are
  often the same carrier (issue #142). Ignored for one-way searches.
- `currency` / `language` / `country` - Google `curr=` / `hl=` / `gl=` URL params
- `sort_by` - CHEAPEST, DURATION, DEPARTURE_TIME, ARRIVAL_TIME
- `passengers` - Number of adult passengers (default 1)
- `children` / `infants_in_seat` / `infants_on_lap` - Passenger mix additions;
  see "Note on passenger limits" below

**Response:** Each flight in `flights[]` carries its own `booking_url` — a
`tfs` protobuf deep link that opens the specific itinerary's booking page
(vendor fares + "Continue" CTA) on Google Flights. The token is deterministic
(no session id), so the same itinerary always yields the same URL. The
top-level `booking_url` is a broader search-page link (route + dates
pre-filled) kept as a reliable fallback. Each flight's `flight_number` can be
passed to `get_booking_options` for per-vendor pricing.

### `search_dates`
Find cheapest travel dates within a range.

**Key Parameters:**
- `origin` / `destination` - Airport IATA codes
- `start_date` / `end_date` - Date range in YYYY-MM-DD format
- `trip_duration` - Number of days for round trips
- `is_round_trip` - Boolean for round-trip search
- `cabin_class`, `max_stops`, `departure_window`, `airlines` - Same as above
- `exclude_airlines`, `alliance`, `exclude_alliance`, `min_layover`, `max_layover` - Same as `search_flights`
- `currency`, `language`, `country` - Same locale knobs as `search_flights`
- `sort_by_price` - Boolean to sort by price
- `passengers`, `children`, `infants_in_seat`, `infants_on_lap` - Same as `search_flights`

**Response:** Each date result carries a `booking_url` deep-linking to Google
Flights for that specific date (and return date for round trips).

### `get_booking_options`
**Currently unavailable:** it calls `GetBookingResults`, which is gated behind
the browser-signed header (see "Search transport"), so it raises
`SearchRejectedError`. Use a flight's `booking_url` deep link instead. The rest
of this section describes the tool for when that RPC becomes reachable again.

Get bookable fares (vendor names, prices, and direct booking URLs) for a
single itinerary. Runs a fresh search, selects the flight identified by
`flight_numbers` (or the top result when omitted), then calls
`SearchFlights.get_booking_options` and returns the airline-direct and OTA
options — each with a clickable `booking_url` and `google_click_url`.

**Key Parameters:**
- `origin` / `destination` / `departure_date` / `return_date` - Same as `search_flights`
- `flight_numbers` - Ordered flight numbers identifying the itinerary, taken
  from a prior `search_flights` result (e.g. `['BA178']` one-way,
  `['AA100', 'AA200']` round-trip). Accepts bare (`'178'`) or airline-prefixed
  (`'BA178'`) forms. Omit to price the top result.
- `cabin_class`, `max_stops`, `passengers`, `children`, `infants_in_seat`,
  `infants_on_lap`, `airlines`, `exclude_basic_economy` - Same as `search_flights`
- `departure_window`, `sort_by`, `exclude_airlines`, `alliance`, `exclude_alliance`,
  `min_layover`, `max_layover`, `top_n`, `emissions`, `checked_bags`, `carry_on` - Same as
  `search_flights`. Pass the **same filters used for `search_flights`** (including
  `top_n`) so the re-run search reproduces the same result set; otherwise (especially when
  `flight_numbers` is omitted) the priced "top result" may differ from what the
  user saw.
- `currency`, `language`, `country` - Same locale knobs as `search_flights`

### Error responses (`error_type` / `retryable`)
Every tool's failure response (`success: false`) carries `error_type` (a
stable string) and `retryable` (bool) alongside the existing free-text
`error` message, so a caller can decide what to do without string-matching
`error`. `http_error` responses also carry `http_status` when the upstream
status code is known. Classification is by exception **type**, never by
message text — see `fli.core.errors.classify_error` (`fli/core/errors.py`).

**This vocabulary is shared** by the MCP tools *and* the CLI's
`--format json` error output (`fli/cli/errors.py::json_error_payload`) —
both call the same `classify_error`, so the same exception always produces
the same `error_type` string on either surface. Some values are a released
contract from the CLI (`"timeout"`, `"connection_error"`, `"http_error"`,
`"search_error"`, `"unexpected_error"`, shipped in v0.9.0) and were kept
as-is rather than renamed for the MCP tools.

| `error_type` | `retryable` | Meaning / what to do |
|---|---|---|
| `validation_error` | `false` | Bad input — unknown airport code, an invalid passenger mix, a date range over the 93-date cap, etc. Fix the request; retrying unchanged will fail again. |
| `unsupported_error` | `false` | The request is well-formed but this transport can't serve it (e.g. multi-city). Change the request. |
| `parse_error` | `false` | Google served a page fli couldn't read. Usually (not always) a regional consent/blocked interstitial. Not retryable as-is; set `FLI_SOCS_COOKIE` (EU/EEA) and retry — don't just retry the same request unchanged. |
| `rejected_error` | `false` | Google refused the RPC outright (e.g. `get_booking_options`'s `GetBookingResults` call today — see above). Deterministic; retrying the same request will not help. |
| `timeout` | `true` | The request to Google Flights timed out. See retry guidance below. |
| `connection_error` | `true` | A network/DNS issue prevented reaching Google Flights. See retry guidance below. |
| `http_error` | `true` iff `http_status` is 429 or 5xx | Non-2xx HTTP response from Google; check `http_status`. See retry guidance below. |
| `search_error` | `false` | Any other typed search-client failure not covered above. |
| `unexpected_error` | `false` | An unclassified exception — most likely a bug, worth reporting. |

**Retry guidance for `retryable: true`.** The HTTP client has *already*
retried internally with backoff before raising (`fli/search/client.py`'s
`tenacity` decorator) — a caller seeing `retryable: true` should retry **at
most once or twice more**, with its own exponential backoff in *seconds*
(not milliseconds) between attempts, not hammer the endpoint immediately.
`http_status: 429` specifically means Google is telling you to slow down —
back off more, not less.

### Note on passenger limits
`PassengerInfo` (`fli/models/google_flights/base.py`) validates every
passenger mix against Google Flights' own booking limits: total travelers
(`adults + children + infants_in_seat + infants_on_lap`) must be between 1
and 9, and `infants_on_lap` cannot exceed `adults` (each lap infant needs an
adult to sit with). A violation raises a pydantic `ValidationError` with the
specific offending values named in the message. Both interfaces flatten it
with the shared `fli.core.format_validation_error` helper: the CLI surfaces a
one-line `Error: ...` and a non-zero exit code; the MCP tools surface
`{"success": false, "error": "..."}` (same pattern PR #215 introduced for
other validators).

### Note on emissions
The API surface still accepts the `emissions` filter, but the search-page
transport has no `tfs` field for it, so it is **currently ignored** — the
search logs a warning naming it and returns unfiltered results. The same is
true of `checked_bags` / `carry_on` and `exclude_basic_economy`. See
"Search transport" above.

Independently of that: raw CO₂ figures are intentionally **not** returned in
CLI output or MCP tool responses, and that is unchanged.

## Releasing

The Python (`flights` on PyPI) and JavaScript (`fli-js` on npm) packages
are versioned and released **independently**, but with the same shape:
manual `workflow_dispatch` → bump → tag → GitHub Release → publish.

**PyPI** is cut via `.github/workflows/release.yml`
(Actions → Release → Run workflow on `main`). Choose
`bump=patch|minor|major|explicit`; the workflow bumps `pyproject.toml`,
refreshes `uv.lock`, commits + tags `vX.Y.Z` + creates a GitHub Release,
then calls `publish.yml` to upload to PyPI via Trusted Publishing.

**npm** is cut via `.github/workflows/release-npm.yml`
(Actions → Release npm → Run workflow on `main`). Same bump options;
the workflow bumps `fli-js/package.json`, refreshes `fli-js/bun.lock`,
commits + tags `fli-js-vX.Y.Z` + creates a GitHub Release, then calls
`publish-npm.yml` to build (`tsc -p tsconfig.build.json`) and upload to
npm with `--provenance` (uses the `NPM_TOKEN` secret).

Always run with `dry_run=true` first to preview the version and release
notes. The version-bump logic lives in `scripts/bump_version.py` (covered
by `tests/scripts/test_bump_version.py`); the same script handles both
`pyproject.toml` (via `--pyproject`) and `package.json` (via
`--package-json`), and the tag prefix is controlled by `--tag-prefix`.
The release workflows (`.github/workflows/release.yml` and
`release-npm.yml`) are the source of truth for the exact steps.

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
