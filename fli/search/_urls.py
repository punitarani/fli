"""URL-construction helpers for the FlightsFrontendService RPC endpoints.

The locale tuple (``curr=``, ``hl=``, ``gl=``) is the only knob we expose at
the URL layer. Google honours these on every endpoint we talk to and they
materially change the prices / language of the response, so we surface them
as explicit kwargs on the search methods rather than hiding them as
undocumented HTTP details.

The implementation now lives in :mod:`fli.core.links` so the same helper can
build the public-facing Google Flights deep links shown by the CLI and MCP.
It is re-exported here to keep ``fli.search._urls.with_locale_params`` stable
for existing callers.
"""

from __future__ import annotations

from fli.core.links import with_locale_params

__all__ = ["with_locale_params"]
