"""Airport search utilities for looking up airports by city or name."""

from fli.models import Airport

# Mapping of city names to IATA codes for airports where the city name
# is NOT in the airport name (e.g., JFK doesn't contain "New York")
CITY_AIRPORTS: dict[str, list[str]] = {
    "new york": ["JFK", "LGA", "EWR"],
    "nyc": ["JFK", "LGA", "EWR"],
    "chicago": ["ORD", "MDW"],
    "washington": ["IAD", "DCA", "BWI"],
    "washington dc": ["IAD", "DCA", "BWI"],
    "london": ["LHR", "LGW", "STN", "LTN", "LCY"],
    "paris": ["CDG", "ORY"],
    "tokyo": ["NRT", "HND"],
    "osaka": ["KIX", "ITM"],
    "seoul": ["ICN", "GMP"],
    "beijing": ["PEK", "PKX"],
    "shanghai": ["PVG", "SHA"],
    "bangkok": ["BKK", "DMK"],
    "istanbul": ["IST", "SAW"],
    "moscow": ["SVO", "DME", "VKO"],
    "milan": ["MXP", "LIN"],
    "rome": ["FCO", "CIA"],
    "berlin": ["BER"],
    "mumbai": ["BOM"],
    "delhi": ["DEL"],
    "sao paulo": ["GRU", "CGH"],
    "rio": ["GIG", "SDU"],
    "rio de janeiro": ["GIG", "SDU"],
    "toronto": ["YYZ", "YTZ"],
    "montreal": ["YUL"],
    "mexico city": ["MEX"],
    "buenos aires": ["EZE", "AEP"],
    "dubai": ["DXB", "DWC"],
    "singapore": ["SIN"],
    "hong kong": ["HKG"],
    "taipei": ["TPE", "TSA"],
    "sydney": ["SYD"],
    "melbourne": ["MEL"],
    "san francisco": ["SFO", "OAK", "SJC"],
    "sf": ["SFO", "OAK", "SJC"],
    "bay area": ["SFO", "OAK", "SJC"],
    "los angeles": ["LAX", "BUR", "SNA", "ONT", "LGB"],
    "la": ["LAX", "BUR", "SNA", "ONT", "LGB"],
    "dallas": ["DFW", "DAL"],
    "houston": ["IAH", "HOU"],
    "atlanta": ["ATL"],
    "denver": ["DEN"],
    "seattle": ["SEA"],
    "boston": ["BOS"],
    "miami": ["MIA", "FLL"],
    "detroit": ["DTW"],
    "minneapolis": ["MSP"],
    "phoenix": ["PHX"],
    "orlando": ["MCO"],
    "las vegas": ["LAS"],
    "honolulu": ["HNL"],
}


class AirportMatch:
    """A matched airport from a search query."""

    def __init__(self, code: str, name: str, match_type: str, score: float):
        """Initialize a matched airport result."""
        self.code = code
        self.name = name
        self.match_type = match_type  # "code", "city", "name"
        self.score = score

    def __repr__(self) -> str:
        """Return a debug representation for the match."""
        return (
            f"AirportMatch(code={self.code!r}, name={self.name!r}, match_type={self.match_type!r})"
        )


def search_airports(query: str, limit: int = 10) -> list[AirportMatch]:
    """Search airports by city name, airport name, or IATA code.

    Args:
        query: Search string (e.g., "new york", "san fran", "JFK", "heathrow")
        limit: Maximum results to return.

    Returns:
        List of matching airports sorted by relevance (best match first).

    """
    query_lower = query.strip().lower()
    if not query_lower:
        return []

    results: list[AirportMatch] = []
    seen_codes: set[str] = set()

    # Priority 1: Exact IATA code match
    query_upper = query.strip().upper()
    try:
        airport = Airport[query_upper]
        results.append(AirportMatch(query_upper, airport.value, "code", 100.0))
        seen_codes.add(query_upper)
    except KeyError:
        pass

    # Priority 2: City name lookup (handles "new york" -> JFK, LGA, EWR)
    if query_lower in CITY_AIRPORTS:
        for code in CITY_AIRPORTS[query_lower]:
            if code not in seen_codes:
                try:
                    airport = Airport[code]
                    results.append(AirportMatch(code, airport.value, "city", 90.0))
                    seen_codes.add(code)
                except KeyError:
                    pass

    # Priority 3: Partial city name match (handles "new yo" matching "new york")
    for city, codes in CITY_AIRPORTS.items():
        if city.startswith(query_lower) and query_lower not in CITY_AIRPORTS:
            for code in codes:
                if code not in seen_codes:
                    try:
                        airport = Airport[code]
                        results.append(AirportMatch(code, airport.value, "city", 80.0))
                        seen_codes.add(code)
                    except KeyError:
                        pass

    # Priority 4: Airport name substring match
    for airport in Airport:
        if airport.name in seen_codes:
            continue
        airport_name_lower = airport.value.lower()
        if query_lower in airport_name_lower:
            # Score based on how early the match occurs.
            pos = airport_name_lower.find(query_lower)
            score = 70.0 - (pos * 0.1)  # Earlier matches score higher.
            results.append(AirportMatch(airport.name, airport.value, "name", score))
            seen_codes.add(airport.name)

    # Priority 5: IATA code prefix match (handles "SF" matching "SFO")
    if len(query_upper) <= 3:
        for airport in Airport:
            if airport.name in seen_codes:
                continue
            if airport.name.startswith(query_upper):
                results.append(AirportMatch(airport.name, airport.value, "code", 60.0))
                seen_codes.add(airport.name)

    # Sort by score descending, then by code alphabetically
    results.sort(key=lambda m: (-m.score, m.code))
    return results[:limit]
