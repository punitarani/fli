---
name: fli
description: >
  Guidance for working effectively in the Fli repository across the CLI, Python
  library, and MCP server. Use when: editing the Fli codebase, debugging the
  CLI or MCP server, choosing safe test commands, updating documentation, or
  navigating the repository structure.
license: MIT
---

# Fli repository skill

Use this skill when you are working inside the Fli repository.

Fli is a Python project that provides direct access to Google Flights data through a reverse-engineered API. It has three primary user-facing surfaces:

- CLI via `fli`
- Python API via the `fli` package
- MCP server via `fli-mcp` and `fli-mcp-http`

Prefer repository-specific guidance from this skill over generic Python guidance.

## Quick orientation

- Package metadata lives in `pyproject.toml`.
- Main app areas are `fli/cli/`, `fli/mcp/`, `fli/core/`, `fli/search/`, and `fli/models/`.
- Tests mirror the source layout under `tests/`.
- Docs exist in `README.md`, `docs/`, and the public Mintlify site at `https://www.mintlify.com/punitarani/fli/introduction`.
- The Mintlify docs index is available at `https://punitarani-fli.mintlify.app/llms.txt`.

## What Fli does

Fli is not a scraper-driven browser automation project. It talks to Google Flights through direct API interaction and ships:

- a Typer CLI for `flights` and `dates`
- a FastMCP server with `search_flights` and `search_dates`
- a Python API for programmatic searches
- shared parsing and builder utilities
- Pydantic models for airports, airlines, filters, and results

## When to use this skill

Use this skill when the task involves any of the following:

- changing CLI behavior, arguments, help text, or output
- changing MCP tools, prompts, resources, or configuration
- changing search logic, result serialization, or model validation
- updating tests or choosing which tests are safe to run
- updating docs or examples for this repository
- figuring out where a change belongs in the codebase

## Source of truth

When guidance differs, prefer sources in this order:

1. User instructions
2. `AGENTS.md`
3. `CLAUDE.md`
4. Current source code
5. `README.md`
6. Mintlify docs

Use the Mintlify docs for public usage examples and surface-area context. Use the repository source for implementation truth.

## Repository map

### `fli/cli/`

CLI entrypoints and commands.

- `fli/cli/main.py` wires the Typer app
- `fli/cli/commands/flights.py` handles point-in-time flight search
- `fli/cli/commands/dates.py` handles cheapest-date search

If a user types `fli JFK LAX 2026-05-15`, the CLI treats that as a `flights` command automatically.

### `fli/mcp/`

MCP server behavior.

- `fli/mcp/server.py` defines the MCP server
- tools: `search_flights`, `search_dates`
- prompts: `search-direct-flight`, `find-budget-window`
- resource: `resource://fli-mcp/configuration`

### `fli/core/`

Shared parsing and filter-building utilities used by both the CLI and MCP layers.

- `parsers.py` converts user-facing values into domain models
- `builders.py` constructs search filters and segments

### `fli/search/`

Core search behavior.

- `client.py` handles rate limiting, retries, and HTTP behavior
- `flights.py` implements flight search
- `dates.py` implements cheapest-date search

### `fli/models/`

Domain models and enums.

- airport and airline enums
- filter models
- result models
- Google Flights-specific data structures

### `tests/`

Tests broadly mirror the package layout.

- `tests/cli/`
- `tests/core/`
- `tests/models/`
- `tests/mcp/`
- `tests/search/`

## Safe development workflow

Prefer `uv` for Python environment management in this repository.

### Install dependencies

- `uv sync --all-extras`

### Frequent quality commands

- `make lint`
- `make format`

### Stable default test command

Use this first in cloud or CI-like environments:

- `uv run pytest -vv --ignore=tests/search/`

Reason: `tests/search/` hits the live Google Flights API and is frequently rate-limited.

## Test selection rules

Do not reflexively run the full test suite.

### Default behavior

- normal `pytest` runs include most tests and skip fuzz tests unless special flags are used
- fuzz tests require `--fuzz` or `--all`
- MCP-only selection uses `--mcp`

### Reliable tests

Usually reliable:

- CLI tests
- core utility tests
- model tests
- most MCP tests

### Flaky tests

Use caution with:

- `tests/search/` because it hits the live Google Flights API
- MCP date-search paths that depend on live API results

### Good testing pattern

Match tests to the layer you changed:

- CLI change -> run relevant CLI tests
- parser/builder change -> run core and affected CLI or MCP tests
- MCP change -> run MCP tests and any affected core tests
- model change -> run model tests plus nearby consumers

## Important pitfalls

### Do not run the nonexistent app server target

`make server` and `make server-dev` reference `fli.server.main:app`, but `fli/server/` does not exist in this repository state. Do not use those targets unless the repository adds that package later.

### Respect live API constraints

Search logic depends on Google Flights behavior. Failures can be caused by:

- HTTP 429 rate limiting
- empty live search results
- transient upstream changes

Do not treat those failures as immediate proof of a code regression without isolating the test path first.

### MCP HTTP transport detail

For MCP HTTP integrations, the endpoint expects the `Accept: application/json, text/event-stream` header.

### Docs can lag source

The Mintlify docs are helpful, but the code is authoritative when implementation details differ.

## Public surfaces to keep aligned

When changing behavior, consider whether you also need to update:

- `README.md`
- `docs/`
- Mintlify-facing wording and examples
- CLI help text
- MCP parameter documentation
- examples under `examples/`

Keep terminology consistent:

- airports and airlines use IATA codes
- cabin classes: `ECONOMY`, `PREMIUM_ECONOMY`, `BUSINESS`, `FIRST`
- stop filters: `ANY`, `NON_STOP`, `ONE_STOP`, `TWO_PLUS_STOPS`

## Common task routing

### Add or change a CLI option

Look in:

- `fli/cli/commands/`
- `fli/core/parsers.py`
- `fli/core/builders.py`
- affected docs and examples

### Change MCP parameters or defaults

Look in:

- `fli/mcp/server.py`
- shared parsers and builders in `fli/core/`
- docs for MCP setup and tools

### Change search behavior

Look in:

- `fli/search/flights.py`
- `fli/search/dates.py`
- `fli/search/client.py`
- filter or result models in `fli/models/`

### Change model validation or serialization

Look in:

- `fli/models/`
- MCP serialization paths in `fli/mcp/server.py`
- CLI display code if output formatting is affected

## Useful user-facing commands

- `uv run fli flights JFK LAX 2026-05-15`
- `uv run fli dates JFK LAX --from 2026-05-01 --to 2026-05-31`
- `uv run fli-mcp`
- `uv run fli-mcp-http`

These are useful for understanding intended behavior, but prefer tests over ad hoc live API calls when a stable automated path exists.

## Done criteria

A repository change is usually not done until you have:

- updated the implementation
- run targeted checks appropriate to the changed layer
- avoided flaky live API paths unless they are necessary
- updated docs or examples when public behavior changed
- kept CLI, MCP, and shared parsing logic consistent

## Summary

Treat Fli as a Python library with three connected surfaces: CLI, Python API, and MCP server. Use `uv`, prefer targeted tests, avoid the broken `make server` targets, and treat live Google Flights API tests as potentially flaky rather than as default validation paths.
