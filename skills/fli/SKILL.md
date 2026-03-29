---
name: fli
description: >
  Guidance for installing and using Fli correctly as a CLI and MCP server.
  Use when: setting up Fli with pipx, running `fli` flight searches, configuring
  Claude Desktop with `fli-mcp`, using the HTTP MCP server, or troubleshooting
  Fli command availability and common usage mistakes.
license: MIT
---

# Fli install and usage skill

Use this skill when the goal is to install Fli and use its CLI or MCP server correctly.

The primary path is:

1. install with `pipx install flights`
2. use `fli` for terminal searches
3. use `fli-mcp` for Claude Desktop or other STDIO MCP clients
4. use `fli-mcp-http` only when an HTTP MCP endpoint is specifically needed

Do not default to cloning the repository or using a source checkout. Only mention cloning the repo when the user explicitly wants to contribute to Fli itself.

## What Fli is

Fli is a Python package for accessing Google Flights data through direct API interaction.

It has three public surfaces:

- CLI via `fli`
- Python library via the `fli` package
- MCP server via `fli-mcp` and `fli-mcp-http`

For this skill, focus on the CLI and MCP server first.

## Core install rule

If the user wants to use Fli as a tool, recommend `pipx install flights`.

Why:

- it is the documented recommended install path for CLI and MCP usage
- it keeps the install isolated from other Python projects
- it exposes `fli`, `fli-mcp`, and `fli-mcp-http` on the user's PATH

Only fall back to `pip install flights` or `uvx` when:

- `pipx` is unavailable
- the user wants library-only usage
- the user explicitly prefers another Python package manager

## Standard installation flow

### Preferred install

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
pipx install flights
```

If `pipx` is already installed, skip directly to:

```bash
pipx install flights
```

### Verify installation

Run these checks after install:

```bash
fli --help
fli-mcp --help
which fli-mcp
```

If the commands are not found after `pipx install flights`, have the user run:

```bash
python3 -m pipx ensurepath
```

Then restart the terminal session.

## What the install provides

After `pipx install flights`, these commands should be available:

- `fli` - main CLI for flight searches
- `fli-mcp` - MCP server over STDIO
- `fli-mcp-http` - MCP server over HTTP, defaulting to `http://127.0.0.1:8000/mcp/`

Important naming detail:

- the package to install is `flights`
- the commands to run are `fli`, `fli-mcp`, and `fli-mcp-http`

Do not tell users to run `pipx install fli`.

## CLI usage

### Basic flight search

Use:

```bash
fli flights JFK LAX 2026-10-25
```

### Cheapest-date search

Use:

```bash
fli dates JFK LAX --from 2026-01-01 --to 2026-01-31
```

### Common filters

Use filters like these when the user asks for them:

```bash
fli flights JFK LHR 2026-10-25 \
  --time 6-20 \
  --airlines BA KL \
  --class BUSINESS \
  --stops NON_STOP \
  --sort DURATION
```

Supported language to map correctly:

- cabin classes: `ECONOMY`, `PREMIUM_ECONOMY`, `BUSINESS`, `FIRST`
- stop filters: `ANY`, `NON_STOP`, `ONE_STOP`, `TWO_PLUS_STOPS`
- sort options: `CHEAPEST`, `DURATION`, `DEPARTURE_TIME`, `ARRIVAL_TIME`

### CLI shorthand

Fli supports a convenience shorthand where a non-command invocation is treated as a flights search.

Example:

```bash
fli JFK LAX 2026-05-15
```

This behaves like:

```bash
fli flights JFK LAX 2026-05-15
```

Use the explicit `flights` subcommand in examples unless the user asks for shortcuts.

## MCP usage

### Default MCP mode

Use `fli-mcp` for Claude Desktop and other STDIO-based MCP clients.

```bash
fli-mcp
```

This is the default recommendation for local assistant integration.

### HTTP MCP mode

Use `fli-mcp-http` only when the user needs an HTTP endpoint.

```bash
fli-mcp-http
```

By default, it serves at:

- `http://127.0.0.1:8000/mcp/`

For HTTP integrations, the client should send:

- `Accept: application/json, text/event-stream`

## Claude Desktop setup

When the user wants Claude Desktop integration, recommend this config first:

```json
{
  "mcpServers": {
    "fli": {
      "command": "fli-mcp",
      "args": []
    }
  }
}
```

Suggested config paths:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\\Claude\\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

After editing the config:

1. fully quit Claude Desktop
2. relaunch it
3. start a new conversation
4. ask for a flight search

Good validation prompt:

`Can you search for flights from JFK to LHR on 2026-03-15?`

### Optional MCP environment variables

If the user wants defaults, these environment variables are relevant:

- `FLI_MCP_DEFAULT_PASSENGERS`
- `FLI_MCP_DEFAULT_CURRENCY`
- `FLI_MCP_DEFAULT_CABIN_CLASS`
- `FLI_MCP_DEFAULT_SORT_BY`
- `FLI_MCP_DEFAULT_DEPARTURE_WINDOW`
- `FLI_MCP_MAX_RESULTS`

Example:

```json
{
  "mcpServers": {
    "fli": {
      "command": "fli-mcp",
      "args": [],
      "env": {
        "FLI_MCP_DEFAULT_CURRENCY": "EUR",
        "FLI_MCP_DEFAULT_CABIN_CLASS": "BUSINESS",
        "FLI_MCP_MAX_RESULTS": "10"
      }
    }
  }
}
```

## How to guide users well

### If the user asks to install Fli

Give them the `pipx install flights` path first.

### If the user asks how to use the command line tool

Show `fli flights ...` and `fli dates ...` examples first.

### If the user asks how to connect Claude or another assistant

Show `fli-mcp` and the Claude Desktop config first.

### If the user asks for a web endpoint

Then show `fli-mcp-http` and mention the `/mcp/` path and `Accept` header.

### If the user asks how to contribute or hack on the codebase

That is outside the primary scope of this skill. Only then discuss cloning the repository and using development commands.

## Common mistakes to prevent

- telling users to clone the repository when they only want the tool
- telling users to install `fli` instead of `flights`
- focusing on the Python API when the user asked for CLI or MCP setup
- giving HTTP MCP instructions when STDIO MCP is enough
- forgetting to tell Claude Desktop users to fully restart the app
- omitting the PATH fix when `pipx` installs successfully but commands are not found

## Troubleshooting

### `fli` or `fli-mcp` not found

Try:

```bash
python3 -m pipx ensurepath
```

Then restart the terminal.

### Python version problems

Fli requires Python 3.10 or newer.

Check with:

```bash
python3 --version
```

### Claude Desktop does not show the tools

Check these in order:

1. `fli-mcp --help` works in a terminal
2. the Claude Desktop config file path is correct
3. the JSON is valid
4. Claude Desktop was fully quit and reopened

### Rate limiting or temporary failures

Fli includes automatic rate limiting and retries, but live Google Flights requests can still fail temporarily.

If a query fails:

- retry after a short delay
- reduce repeated back-to-back searches
- do not assume the CLI or MCP setup is broken just because one upstream request failed

## Public docs

Use these docs for product-facing guidance:

- introduction: `https://punitarani-fli.mintlify.app/introduction`
- installation: `https://punitarani-fli.mintlify.app/installation`
- MCP setup: `https://punitarani-fli.mintlify.app/mcp/setup`
- docs index: `https://punitarani-fli.mintlify.app/llms.txt`

Use product docs for examples and onboarding. Use the actual installed command names when writing instructions.

## Summary

The default recommendation is `pipx install flights`. After that, use `fli` for terminal searches, `fli-mcp` for Claude Desktop and other STDIO MCP clients, and `fli-mcp-http` only when an HTTP MCP endpoint is specifically needed.
