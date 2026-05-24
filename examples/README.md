# Fli Examples

Practical, runnable examples for the Fli flight-search library, organized by
language. Both sets mirror each other so you can compare the Python and
TypeScript APIs side by side.

| Language | Directory | Run with |
|----------|-----------|----------|
| Python | [`python/`](python) | `uv run python examples/python/<file>.py` |
| TypeScript | [`typescript/`](typescript) | `bun run examples/typescript/<file>.ts` |

> All examples hit the live Google Flights API. Requests are rate-limited
> (10 req/s) and results reflect real-time availability and pricing.

## What's covered

| Example | Python | TypeScript |
|---------|:------:|:----------:|
| One-way search | ✅ | ✅ |
| Round-trip search | ✅ | ✅ |
| Cheapest dates in a range | ✅ | ✅ |
| Multi-city itinerary | ✅ | ✅ |
| Advanced filters (alliances, exclusions, layovers, locale) | ✅ | ✅ |
| Error handling & client tuning | ✅ | ✅ |
| Time-restricted search | ✅ | — |
| Day-of-week / weekend date preferences | ✅ | — |
| Validation-heavy round trips & date ranges | ✅ | — |
| Price tracking over time | ✅ | — |
| Result processing (pandas) | ✅ | — |

See each directory's README for setup and the full file list:

- [Python examples →](python/README.md)
- [TypeScript examples →](typescript/README.md)
