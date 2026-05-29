"""Shared URL helpers for Google Flights deep links.

Both the CLI and MCP surface a clickable Google Flights link alongside
search results so a consumer can open the route (and complete a booking)
in a browser. The natural-language ``q`` form used here is the same one
Google's own frontend accepts.

``with_locale_params`` lives here (rather than in :mod:`fli.search`) so the
core layer stays free of any dependency on the search package; the search
modules re-export it from :mod:`fli.search._urls` for backwards
compatibility.
"""

from __future__ import annotations

import urllib.parse

GOOGLE_FLIGHTS_URL = "https://www.google.com/travel/flights"


def with_locale_params(
    url: str,
    currency: str | None,
    language: str | None,
    country: str | None,
) -> str:
    """Append optional ``curr``/``hl``/``gl`` parameters to ``url``.

    - ``currency`` is uppercased ("usd" → "USD") because Google rejects
      lowercase codes silently (still 200, but ignores the override).
    - ``language`` is passed through verbatim (BCP-47, may contain a hyphen).
    - ``country`` is uppercased (ISO 3166-1 alpha-2).

    All values are percent-encoded so a caller typo (a stray ``&``, ``+``,
    or whitespace) can't break the URL — typical inputs like ``en-GB`` are
    already URL-safe so the encoding is a no-op for them.

    No-op when all three are None — returns the input URL unchanged so
    callers can pass through without checking.
    """
    params: list[str] = []
    if currency:
        params.append(f"curr={urllib.parse.quote(currency.upper(), safe='')}")
    if language:
        params.append(f"hl={urllib.parse.quote(language, safe='')}")
    if country:
        params.append(f"gl={urllib.parse.quote(country.upper(), safe='')}")
    if not params:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{'&'.join(params)}"


def google_flights_url(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None = None,
    *,
    currency: str | None = None,
    language: str | None = None,
    country: str | None = None,
) -> str:
    """Build a shareable Google Flights deep link for a route and dates.

    ``origin`` and ``destination`` are bare IATA codes (e.g. ``"JFK"``).
    The returned URL pre-fills the route and outbound date (plus the return
    date for round trips); locale knobs (``curr``/``hl``/``gl``) are appended
    when supplied.
    """
    query = f"Flights from {origin} to {destination} on {departure_date}"
    if return_date:
        query += f" through {return_date}"
    url = f"{GOOGLE_FLIGHTS_URL}?q={urllib.parse.quote(query)}"
    return with_locale_params(url, currency, language, country)
