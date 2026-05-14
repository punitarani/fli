"""URL-construction helpers for the FlightsFrontendService RPC endpoints.

Currently the only knob we expose at the URL layer is the locale tuple
(``curr=``, ``hl=``, ``gl=``). Google honours these on every endpoint we
talk to and they materially change the prices / language of the response,
so we surface them as explicit kwargs on the search methods rather than
hiding them as undocumented HTTP details.
"""

from __future__ import annotations


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

    No-op when all three are None — returns the input URL unchanged so
    callers can pass through without checking.
    """
    params: list[str] = []
    if currency:
        params.append(f"curr={currency.upper()}")
    if language:
        params.append(f"hl={language}")
    if country:
        params.append(f"gl={country.upper()}")
    if not params:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{'&'.join(params)}"
