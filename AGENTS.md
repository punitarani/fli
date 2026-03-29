# AGENTS.md

## Cursor Cloud specific instructions

### Overview

Fli is a Python library providing programmatic access to Google Flights data via reverse-engineered API. It offers a CLI (`fli`), MCP server (`fli-mcp` / `fli-mcp-http`), and Python API. No external services (databases, caches, etc.) are required.

### Development commands

All standard commands are in the `Makefile` and `CLAUDE.md`. Key ones:

- **Install deps**: `uv sync --all-extras`
- **Lint**: `make lint` (ruff)
- **Format**: `make format`
- **Tests**: `make test` (standard), `make test-all` (including fuzz)
- **CLI**: `uv run fli flights JFK LAX 2026-05-15`
- **MCP HTTP server**: `uv run fli-mcp-http` (serves at `http://127.0.0.1:8000/mcp/`)

### Testing caveats

- Tests under `tests/search/` hit the live Google Flights API and are rate-limited (HTTP 429). These will frequently fail in cloud/CI environments. All other tests (CLI, core, models, MCP) are self-contained and pass reliably.
- Run `uv run pytest -vv --ignore=tests/search/` to skip flaky API-dependent tests.
- One MCP test (`test_search_dates_round_trip`) also makes a live API call and may fail with empty results.

### MCP server notes

- The MCP HTTP endpoint requires `Accept: application/json, text/event-stream` header.
- The `fli/server/` module has been removed from the codebase.
