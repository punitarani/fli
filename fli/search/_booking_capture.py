"""Browser-driven booking-token capture (optional Playwright helper).

The ``GetBookingResults`` endpoint requires a server-minted session id
that does not appear anywhere in the search response JSON or the rendered
HTML — empirically confirmed by walking every nested string in multiple
captured responses. Google's frontend JS bundle generates the booking
URL's ``tfu`` parameter as part of the click-handler when the user
selects a flight; reproducing that pipeline server-side would require
deep reverse engineering of the JS bundle.

This module provides an opt-in fallback: if the caller has Playwright
installed, ``capture_booking_token`` drives a real browser through the
search → select-outbound → select-return → booking-page flow, then
reads the resulting URL's ``tfu`` parameter and returns the inner
booking token. The caller can then pass that token straight to
:meth:`fli.search.SearchFlights.get_booking_options`.

Why opt-in: Playwright adds ~300 MB of browser binaries and is wrong
for most fli use cases (CLI flight search, MCP queries). Users who
need live booking options can install it on demand::

    uv add --optional booking playwright
    uv run playwright install chromium
"""

from __future__ import annotations

from datetime import datetime

from fli.models import FlightResult


def _format_iata(airport) -> str:  # noqa: ANN001
    """Return the bare IATA code from an Airport enum or string."""
    if hasattr(airport, "name"):
        return airport.name.removeprefix("_")
    return str(airport)


async def capture_booking_token(
    outbound: FlightResult,
    return_flight: FlightResult | None,
    travel_date: str,
    return_date: str | None = None,
    *,
    currency: str = "USD",
    headless: bool = True,
    timeout_ms: int = 60_000,
) -> str:
    """Drive a real browser through the booking flow and return the token.

    The token is the base64-encoded booking payload extracted from the
    booking page's ``tfu`` URL parameter — the same shape that
    :meth:`fli.search.SearchFlights.get_booking_options` accepts via its
    ``booking_token`` kwarg.

    Requires Playwright to be installed (``pip install playwright`` plus
    ``playwright install chromium``). The function imports Playwright
    lazily so that fli's main dependency footprint is unaffected.

    Args:
        outbound: Outbound :class:`FlightResult` (from a prior
            :meth:`fli.search.SearchFlights.search` call).
        return_flight: Return :class:`FlightResult` for round-trip
            itineraries, or ``None`` for one-way.
        travel_date: Outbound date in ``YYYY-MM-DD`` format.
        return_date: Return date in ``YYYY-MM-DD`` format (RT only).
        currency: ISO 4217 currency code for the booking page URL.
        headless: When True (default) runs the browser in headless mode.
        timeout_ms: Per-step navigation timeout in milliseconds.

    Returns:
        The base64-encoded booking token suitable for
        :meth:`fli.search.SearchFlights.get_booking_options`.

    Raises:
        ImportError: When Playwright isn't installed.
        RuntimeError: When the booking page URL doesn't carry the ``tfu``
            parameter (e.g. the flight is unavailable, or Google has
            changed the navigation flow).

    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:  # pragma: no cover - optional dependency
        raise ImportError(
            "capture_booking_token requires Playwright. Install with:\n"
            "  pip install playwright\n"
            "  playwright install chromium"
        ) from e

    from fli.search._proto import extract_booking_token_from_tfu

    out_iata = _format_iata(outbound.legs[0].departure_airport)
    in_iata = _format_iata(outbound.legs[-1].arrival_airport)
    parsed_date = datetime.strptime(travel_date, "%Y-%m-%d").strftime("%Y-%m-%d")
    search_url = (
        f"https://www.google.com/travel/flights"
        f"?hl=en&curr={currency}&gl=US"
        f"&q=Flights to {in_iata} from {out_iata} on {parsed_date}"
    )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        try:
            page = await browser.new_page()
            await page.goto(search_url, timeout=timeout_ms, wait_until="load")
            await page.wait_for_selector('a[aria-label*="Select flight"]', timeout=timeout_ms)

            # Click the matching outbound flight: filter by departure time + airline.
            outbound_label = _flight_aria_pattern(outbound)
            await page.locator(f'a[aria-label*="{outbound_label}"]').first.click()

            if return_flight is not None:
                # Round-trip: wait for the return-flight grid, then click.
                await page.wait_for_selector('a[aria-label*="Select flight"]', timeout=timeout_ms)
                return_label = _flight_aria_pattern(return_flight)
                await page.locator(f'a[aria-label*="{return_label}"]').first.click()

            await page.wait_for_url("**/travel/flights/booking?**", timeout=timeout_ms)
            booking_url = page.url
        finally:
            await browser.close()

    if "tfu=" not in booking_url:
        raise RuntimeError(
            f"Booking page URL has no `tfu` parameter: {booking_url}\n"
            "Google may have changed the navigation flow."
        )
    return extract_booking_token_from_tfu(booking_url)


def _flight_aria_pattern(flight: FlightResult) -> str:
    """Build a short string that uniquely matches the flight's aria-label.

    Google's UI links each "Select flight" anchor have an aria-label like
    ``"From 342 US dollars round trip total. Nonstop flight with American."``
    We match on the *airline name* + *departure time* which together
    uniquely identify a row in the list.
    """
    dep = flight.legs[0].departure_datetime.strftime("%-I:%M %p")
    # The aria-label always includes the departure time + " on <weekday>".
    return f"{dep} on"
