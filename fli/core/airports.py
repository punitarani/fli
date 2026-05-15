"""Airport search utilities for looking up airports by city or name."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fli.models import Airport
from fli.models.airport import AIRPORT_NAMES

# Curated mapping of city names and common abbreviations to IATA codes.
# Provides multi-airport groupings (e.g., "new york" -> JFK, LGA, EWR) and
# short aliases (e.g., "sf", "la", "nyc") that pure airport-name substring
# search would miss. Validated against the Airport enum at import time.
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

for _city, _codes in CITY_AIRPORTS.items():
    for _code in _codes:
        if _code not in AIRPORT_NAMES:
            raise RuntimeError(f"CITY_AIRPORTS[{_city!r}] references unknown IATA code {_code!r}")

MatchType = Literal["iata_exact", "iata_prefix", "city", "name"]


class AirportMatch(BaseModel):
    """A matched airport from a search query."""

    model_config = ConfigDict(frozen=True)

    code: Airport
    name: str
    match_type: MatchType
    score: float = Field(ge=0.0, le=100.0)


def search_airports(query: str, limit: int = 10) -> list[AirportMatch]:
    """Search airports by city name, airport name, or IATA code.

    Results are ranked by a 5-priority cascade, scored 0-100 (higher = better):

      1. iata_exact  (score 100) - query is an exact IATA code (e.g. "JFK")
      2. city        (score 90)  - query is an exact city/alias in CITY_AIRPORTS
      3. city        (score 80)  - query is a prefix of a city in CITY_AIRPORTS
      4. name        (score <=70) - query is a substring of an airport's name;
                                   earlier match position scores higher
      5. iata_prefix (score 60)  - query (<=3 chars) is a prefix of an IATA code

    Within a single result list, each IATA code appears at most once: the
    highest-priority match wins.

    Args:
        query: Search string (e.g., "new york", "san fran", "JFK", "heathrow").
        limit: Maximum results to return. Values < 1 yield an empty list.

    Returns:
        List of matching airports sorted by relevance (best match first).

    """
    query_lower = query.strip().lower()
    if not query_lower or limit < 1:
        return []

    results: list[AirportMatch] = []
    seen_codes: set[str] = set()

    # Priority 1: Exact IATA code match
    query_upper = query.strip().upper()
    if query_upper in Airport.__members__:
        airport = Airport[query_upper]
        results.append(
            AirportMatch(code=airport, name=airport.value, match_type="iata_exact", score=100.0)
        )
        seen_codes.add(query_upper)

    # Priority 2: Exact city name lookup (handles "new york" -> JFK, LGA, EWR)
    if query_lower in CITY_AIRPORTS:
        for code in CITY_AIRPORTS[query_lower]:
            if code not in seen_codes:
                airport = Airport[code]
                results.append(
                    AirportMatch(code=airport, name=airport.value, match_type="city", score=90.0)
                )
                seen_codes.add(code)

    # Priority 3: Partial city name match (handles "new yo" matching "new york")
    if query_lower not in CITY_AIRPORTS:
        for city, codes in CITY_AIRPORTS.items():
            if city.startswith(query_lower):
                for code in codes:
                    if code not in seen_codes:
                        airport = Airport[code]
                        results.append(
                            AirportMatch(
                                code=airport, name=airport.value, match_type="city", score=80.0
                            )
                        )
                        seen_codes.add(code)

    # Priority 4: Airport name substring match.
    # Iterate the raw dict instead of the Enum — skips Enum-member
    # attribute access (``.value``, ``.name``) on each of ~7,900 entries,
    # which is the dominant cost when no other priority matched first.
    for code, airport_name in AIRPORT_NAMES.items():
        if code in seen_codes:
            continue
        airport_name_lower = airport_name.lower()
        if query_lower in airport_name_lower:
            # 0.1-per-position weight keeps name matches (max ~70) below
            # city matches (80) regardless of where the substring lands.
            pos = airport_name_lower.find(query_lower)
            score = 70.0 - (pos * 0.1)
            results.append(
                AirportMatch(code=Airport[code], name=airport_name, match_type="name", score=score)
            )
            seen_codes.add(code)

    # Priority 5: IATA code prefix match (handles "SF" matching "SFO").
    if len(query_upper) <= 3:
        for code, airport_name in AIRPORT_NAMES.items():
            if code in seen_codes:
                continue
            if code.startswith(query_upper):
                results.append(
                    AirportMatch(
                        code=Airport[code],
                        name=airport_name,
                        match_type="iata_prefix",
                        score=60.0,
                    )
                )
                seen_codes.add(code)

    # Sort by score descending, then by IATA code alphabetically.
    results.sort(key=lambda m: (-m.score, m.code.name))
    return results[:limit]
