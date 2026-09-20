# AGENTS.md

## Cursor Cloud specific instructions

### Overview

Fli is a Python library providing programmatic access to Google Flights data via reverse-engineered API. It offers a CLI (`fli`), MCP server (`fli-mcp` / `fli-mcp-http`), and Python API. No external services (databases, caches, etc.) are required.

### Development commands

All standard commands are in the `Makefile` and `CLAUDE.md`. Key ones:

- **Install deps**: `uv sync --all-extras`
- **Lint**: `make lint` (ruff)
- **Format**: `make format`
- **Tests**: `make test` (standard, offline), `make test-all` (including fuzz, still offline), `make test-live` (real network)
- **CLI**: `uv run fli flights JFK LAX 2026-05-15`
- **MCP HTTP server**: `uv run fli-mcp-http` (serves at `http://127.0.0.1:8000/mcp/`)

### Testing caveats

- Almost all tests, including most of `tests/search/`, run entirely offline against captured
  fixtures/stubs — no network access is required and none of them are rate-limited.
- A small number of tests are marked `live` because they call the real Google Flights API:
  `test_search_flights_new_filters_live.py`, the parametrized case in
  `test_search_flights_fuzz.py`, the four search tests in
  `tests/mcp/test_mcp_server.py::TestMCPServer`, and a handful of previously-unmocked cases in
  `test_search_flights.py` / `test_search_dates.py`. These are skipped unless `--live` is passed
  (`--all` does **not** enable them), so `make test` / `make test-all` never hit the network. Run
  them with `make test-live` (`pytest --all -m live --live` — `--all` is still required together
  with `--live`, or the fuzz-gated live case is dropped before `-m live` sees it) if you have
  network access; they may be skipped on a transient transport failure and fail on an actual
  regression. They also run daily
  in `.github/workflows/live-canary.yml`, which files a GitHub issue on failure.

### Releasing

Releases are manual: GitHub Actions → **Release** → Run workflow on `main`,
choose `bump=patch|minor|major|explicit`. Run with `dry_run=true` first to
preview. Bump logic is in `scripts/bump_version.py` (testable). See the
Releasing section in `CLAUDE.md` and the `.github/workflows/release*.yml`
workflows for the full process.

### MCP server notes

- The MCP HTTP endpoint requires `Accept: application/json, text/event-stream` header.
- The `fli/server/` module has been removed from the codebase.
