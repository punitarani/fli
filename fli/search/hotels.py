"""Hotel search implementation.

Uses the `fast_hotels` library to build the Google Hotels request (protobuf
`ths` parameter), but performs the HTTP fetch and HTML parsing ourselves so we
can extract clean, trustworthy prices.

The upstream `fast_hotels.core.parse_response` grabs the first `$N` match it
finds in each card's full text, which picks up promotional copy like
"$1 cleaning fee off", strike-through prefixes, and other non-price noise —
producing "$1" rows for real hotels. It also contains a last-resort fallback
that pairs arbitrary `<h2>` tags with arbitrary price regex matches by index,
surfacing "Photos" / FAQ cards as hotels.

Our parser:
- uses the dedicated price element (`span.qQOQpe.prxS3d`) and falls back to
  `$N nightly` / `$N total` text inside `div.CQYfx.UDzrdc`,
- requires both a hotel name element AND a price element on each card,
- drops cards with implausibly low prices (under $10/night).
"""

from __future__ import annotations

import contextlib
import os
import re
from dataclasses import dataclass


class HotelSearchError(Exception):
    """Raised when a hotel search fails."""


@dataclass
class HotelResult:
    """A single hotel search result."""

    name: str
    price: float
    rating: float | None = None
    url: str | None = None
    amenities: list[str] | None = None


# Prices below this (USD equivalent) are almost certainly parsing artifacts,
# not real room rates. Keeps the worst mis-parses out of the output.
MIN_PLAUSIBLE_PRICE = 10.0


def _parse_price(text: str) -> float | None:
    """Extract the first well-formed dollar amount from text.

    Handles "$1,234", "$1234.50", "$231". Returns None on no match.
    """
    m = re.search(r"\$([0-9][0-9,]*(?:\.[0-9]+)?)", text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_hotel_card(card) -> dict | None:
    """Parse a single hotel card element. Returns None if it's not a real hotel."""
    # Google serves two distinct card layouts. Primary uses h2.BgYkof; the
    # alt layout (seen more often with children > 0) uses h2.Cx32Ud. Fall back
    # to any h2 inside the card as a last resort.
    name_elem = card.css_first("h2.BgYkof") or card.css_first("h2.Cx32Ud") or card.css_first("h2")
    if not name_elem:
        return None
    name = name_elem.text(strip=True)
    if not name or len(name) < 3:
        return None

    # Price selectors, in order of how clean / unambiguous they are. Each
    # targets a dedicated price element; we avoid regex-over-full-card-text
    # because that picks up promotional "$1" copy.
    price: float | None = None
    for selector in (
        "span.qQOQpe.prxS3d",  # primary layout
        "span.W9vOvb.nDkDDb",  # alt layout
        "span.VfPpkd-vQzf8d",  # "view deal" button label
    ):
        elem = card.css_first(selector)
        if elem:
            price = _parse_price(elem.text(strip=True))
            if price is not None:
                break

    # Fallback: scan "$N nightly" / "$N total" blocks
    if price is None:
        for block in card.css("div.CQYfx.UDzrdc"):
            txt = block.text(strip=True)
            if "nightly" in txt or "night" in txt or "total" in txt:
                price = _parse_price(txt)
                if price is not None:
                    break

    if price is None or price < MIN_PLAUSIBLE_PRICE:
        return None

    # Rating
    rating: float | None = None
    rating_elem = card.css_first("span.KFi5wf.lA0BZ")
    if rating_elem:
        try:
            rating = float(rating_elem.text(strip=True))
        except ValueError:
            rating = None
    if rating is None:
        aria_elem = card.css_first('span[aria-label*="out of 5 stars"]')
        if aria_elem:
            aria = aria_elem.attributes.get("aria-label", "") or ""
            m = re.search(r"([0-9.]+) out of 5", aria)
            if m:
                try:
                    rating = float(m.group(1))
                except ValueError:
                    rating = None

    # Amenities — use the canonical selector; skip the heuristic regex fallback
    # that produced junk entries in upstream.
    amenities: list[str] = []
    for a in card.css("span.LtjZ2d"):
        t = a.text(strip=True)
        if t and len(t) > 2 and t not in amenities:
            amenities.append(t)

    url: str | None = None
    link_elem = card.css_first("a[href]")
    if link_elem:
        href = link_elem.attributes.get("href")
        if href and href.startswith("/travel/"):
            url = "https://www.google.com" + href
        elif href:
            url = href

    return {
        "name": name,
        "price": price,
        "rating": rating,
        "amenities": amenities,
        "url": url,
    }


def _parse_hotels_html(html: str) -> list[dict]:
    """Parse a Google Hotels search HTML page into clean hotel dicts."""
    from selectolax.lexbor import LexborHTMLParser

    parser = LexborHTMLParser(html)
    hotels: list[dict] = []
    for card in parser.css("div.uaTTDe"):
        parsed = _parse_hotel_card(card)
        if parsed:
            hotels.append(parsed)
    return hotels


# Browser fingerprints to try in order. Google Hotels sometimes returns an
# empty SSR page for a given UA (especially when `children` > 0 triggers a
# different layout variant), so we retry with alternates before giving up.
# Ordered: a plain default first, then specific versions known-valid across
# primp 1.2.x releases.
_IMPERSONATE_CHAIN = ("chrome", "chrome_130", "chrome_128", "firefox_128", "safari_18")


@contextlib.contextmanager
def _silence_stderr():
    """Temporarily redirect fd 2 to /dev/null.

    Needed because primp writes its "Impersonate X does not exist" notice from
    Rust directly to fd 2, bypassing `sys.stderr`. That noise pollutes the
    `--format json` output when callers redirect 2>&1 before piping to `jq`.
    """
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        yield
        return
    saved = os.dup(2)
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        os.close(devnull)


def _fetch_hotels_html(
    location: str,
    check_in_date: str,
    check_out_date: str,
    adults: int,
    children: int,
    currency: str,
) -> str:
    """Build the Google Hotels request and return the raw HTML.

    Retries with alternate browser fingerprints if the response has no hotel
    cards — Google sometimes serves an empty SSR page depending on the UA.
    """
    from fast_hotels.filter import THSData
    from fast_hotels.hotels_impl import Guests as FastGuests
    from fast_hotels.hotels_impl import HotelData as FastHotelData
    from fast_hotels.primp import Client
    from fast_hotels.utils import get_city_from_iata

    hotel_data = [
        FastHotelData(
            checkin_date=check_in_date,
            checkout_date=check_out_date,
            location=location,
        )
    ]
    guests = FastGuests(adults=adults, children=children)
    filt = THSData.from_interface(hotel_data=hotel_data, guests=guests, room_type="standard")
    params = {
        "ths": filt.as_b64().decode("utf-8"),
        "hl": "en",
        "curr": currency,
    }
    city = get_city_from_iata(location)
    location_url = city.strip().replace(" ", "+").lower()
    url = f"https://www.google.com/travel/hotels/{location_url}"

    last_text = ""
    for impersonate in _IMPERSONATE_CHAIN:
        with _silence_stderr():
            try:
                client = Client(impersonate=impersonate, verify=False)
                res = client.get(url, params=params)
            except Exception:  # noqa: BLE001
                continue
        if res.status_code != 200:
            last_text = res.text
            continue
        # Quick check: does this response actually contain hotel cards?
        if "uaTTDe" in res.text:
            return res.text
        last_text = res.text

    if last_text:
        # Return the last response so the parser can still surface any stragglers.
        return last_text
    raise HotelSearchError("Google Hotels returned no usable response")


class SearchHotels:
    """Hotel search implementation using Google Travel.

    Builds the request via `fast_hotels` protobuf helpers and parses the
    response with a stricter parser than the upstream library provides.
    """

    def search(
        self,
        location: str,
        check_in_date: str,
        check_out_date: str,
        adults: int = 2,
        children: int = 0,
        currency: str = "USD",
        sort_by: str | None = None,
        limit: int | None = None,
    ) -> list[HotelResult] | None:
        """Search for hotels using Google Travel.

        Args:
            location: City name or IATA airport code
            check_in_date: Check-in date (YYYY-MM-DD)
            check_out_date: Check-out date (YYYY-MM-DD)
            adults: Number of adult guests
            children: Number of child guests
            currency: Currency code (e.g., USD, EUR)
            sort_by: 'price', 'rating', or None for best value
            limit: Maximum number of results to return

        Returns:
            List of HotelResult, or None if no hotels found.

        Raises:
            HotelSearchError: If the search fails
            ImportError: If the 'hotels' extra isn't installed

        """
        try:
            import fast_hotels  # noqa: F401
            import selectolax  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "Hotel search requires the 'hotels' extra. "
                "Install with: pip install flights[hotels]"
            ) from e

        try:
            html = _fetch_hotels_html(
                location=location,
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                adults=adults,
                children=children,
                currency=currency,
            )
            hotels = _parse_hotels_html(html)
        except HotelSearchError:
            raise
        except Exception as e:
            raise HotelSearchError(f"Hotel search failed: {e}") from e

        if not hotels:
            return None

        if sort_by == "price":
            hotels.sort(key=lambda h: h["price"])
        elif sort_by == "rating":
            hotels.sort(key=lambda h: h["rating"] or 0, reverse=True)
        else:
            # Best value: highest rating / price ratio
            def value_ratio(h: dict) -> float:
                if h["rating"] and h["price"] > 0:
                    return h["rating"] / h["price"]
                return 0.0

            hotels.sort(key=value_ratio, reverse=True)

        if limit:
            hotels = hotels[:limit]

        return [
            HotelResult(
                name=h["name"],
                price=h["price"],
                rating=h["rating"],
                url=h["url"],
                amenities=h["amenities"],
            )
            for h in hotels
        ]

    def find_hotel(
        self,
        hotel_name: str,
        location: str,
        check_in_date: str,
        check_out_date: str,
        adults: int = 2,
        children: int = 0,
        currency: str = "USD",
    ) -> HotelResult | None:
        """Look up the rate for a specific hotel on specific dates.

        Tries the city-level search first and fuzzy-matches by name. If no good
        match is found, retries with the hotel name itself as the Google Hotels
        query — which typically returns the hotel's own entity page when the
        name is specific enough.

        Args:
            hotel_name: Hotel name to match (e.g. "Hilton Copacabana").
            location: City / area used for the initial search.
            check_in_date: Check-in date (YYYY-MM-DD).
            check_out_date: Check-out date (YYYY-MM-DD).
            adults: Number of adult guests.
            children: Number of child guests.
            currency: Currency code.

        Returns:
            The best-matching HotelResult, or None if no credible match found.

        """
        # Pass 1: city-level search, fuzzy-match by name.
        hits = (
            self.search(
                location=location,
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                adults=adults,
                children=children,
                currency=currency,
                limit=40,
            )
            or []
        )
        match = _best_name_match(hotel_name, hits)
        if match is not None:
            return match

        # Pass 2: use the hotel name itself as the location query — Google
        # often resolves this to the hotel's entity page.
        hits = (
            self.search(
                location=f"{hotel_name} {location}",
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                adults=adults,
                children=children,
                currency=currency,
                limit=10,
            )
            or []
        )
        return _best_name_match(hotel_name, hits)


def _best_name_match(query: str, results: list[HotelResult]) -> HotelResult | None:
    """Pick the best hotel match for `query` from `results`.

    Uses difflib ratio on lowercased tokens, with a minimum threshold so we
    don't return unrelated hotels that happened to top the list.
    """
    if not results:
        return None

    import difflib

    q = query.lower().strip()
    scored: list[tuple[float, HotelResult]] = []
    for r in results:
        name = r.name.lower()
        ratio = difflib.SequenceMatcher(None, q, name).ratio()
        # Substring boost: "hilton copacabana" inside "Hilton Rio de Janeiro
        # Copacabana" should score well even though ratio alone is lukewarm.
        if all(tok in name for tok in q.split() if len(tok) > 2):
            ratio = max(ratio, 0.75)
        scored.append((ratio, r))
    scored.sort(key=lambda s: s[0], reverse=True)
    best_score, best = scored[0]
    if best_score < 0.5:
        return None
    return best
