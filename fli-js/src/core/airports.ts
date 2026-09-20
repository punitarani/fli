/**
 * Airport search by IATA code, city name, or airport name.
 * 1:1 port of fli/core/airports.py — same 5-priority cascade.
 */

import { AIRPORT_NAMES, type Airport } from "../models/airport.ts";

export type MatchType = "iata_exact" | "iata_prefix" | "city" | "name";

export interface AirportMatch {
  code: Airport;
  name: string;
  match_type: MatchType;
  score: number;
}

/**
 * Curated multi-airport city aliases (e.g., "new york" → JFK / LGA / EWR).
 * Mirrors the Python CITY_AIRPORTS dict.
 */
export const CITY_AIRPORTS: Record<string, string[]> = {
  "new york": ["JFK", "LGA", "EWR"],
  nyc: ["JFK", "LGA", "EWR"],
  chicago: ["ORD", "MDW"],
  washington: ["IAD", "DCA", "BWI"],
  "washington dc": ["IAD", "DCA", "BWI"],
  london: ["LHR", "LGW", "STN", "LTN", "LCY"],
  paris: ["CDG", "ORY"],
  tokyo: ["NRT", "HND"],
  osaka: ["KIX", "ITM"],
  seoul: ["ICN", "GMP"],
  beijing: ["PEK", "PKX"],
  shanghai: ["PVG", "SHA"],
  bangkok: ["BKK", "DMK"],
  istanbul: ["IST", "SAW"],
  moscow: ["SVO", "DME", "VKO"],
  milan: ["MXP", "LIN"],
  rome: ["FCO", "CIA"],
  berlin: ["BER"],
  mumbai: ["BOM"],
  delhi: ["DEL"],
  "sao paulo": ["GRU", "CGH"],
  rio: ["GIG", "SDU"],
  "rio de janeiro": ["GIG", "SDU"],
  toronto: ["YYZ", "YTZ"],
  montreal: ["YUL"],
  "mexico city": ["MEX"],
  "buenos aires": ["EZE", "AEP"],
  dubai: ["DXB", "DWC"],
  singapore: ["SIN"],
  "hong kong": ["HKG"],
  taipei: ["TPE", "TSA"],
  sydney: ["SYD"],
  melbourne: ["MEL"],
  "san francisco": ["SFO", "OAK", "SJC"],
  sf: ["SFO", "OAK", "SJC"],
  "bay area": ["SFO", "OAK", "SJC"],
  "los angeles": ["LAX", "BUR", "SNA", "ONT", "LGB"],
  la: ["LAX", "BUR", "SNA", "ONT", "LGB"],
  dallas: ["DFW", "DAL"],
  houston: ["IAH", "HOU"],
  atlanta: ["ATL"],
  denver: ["DEN"],
  seattle: ["SEA"],
  boston: ["BOS"],
  miami: ["MIA", "FLL"],
  detroit: ["DTW"],
  minneapolis: ["MSP"],
  phoenix: ["PHX"],
  orlando: ["MCO"],
  "las vegas": ["LAS"],
  honolulu: ["HNL"],
};

// Validate at module load — surfaces typos in CITY_AIRPORTS immediately
// instead of returning silently-empty results at search time.
for (const [city, codes] of Object.entries(CITY_AIRPORTS)) {
  for (const code of codes) {
    if (!(code in AIRPORT_NAMES)) {
      throw new Error(`CITY_AIRPORTS[${city}] references unknown IATA code '${code}'`);
    }
  }
}

/**
 * Search airports by city name, airport name, or IATA code.
 *
 * Results are ranked 0-100 (higher = better) via the same 5-priority
 * cascade used in the Python implementation:
 *
 *   1. iata_exact (100)   — exact IATA code
 *   2. city (90)          — exact city/alias
 *   3. city (80)          — prefix of a city/alias
 *   4. name (≤70)         — substring of an airport's name (position-weighted)
 *   5. iata_prefix (60)   — prefix of an IATA code (only for ≤3-char queries)
 */
export function searchAirports(query: string, limit = 10): AirportMatch[] {
  const queryLower = query.trim().toLowerCase();
  if (!queryLower || limit < 1) return [];

  const results: AirportMatch[] = [];
  const seen = new Set<string>();

  // 1. Exact IATA code match
  const queryUpper = query.trim().toUpperCase();
  if (queryUpper in AIRPORT_NAMES) {
    results.push({
      code: queryUpper as Airport,
      name: queryUpper,
      match_type: "iata_exact",
      score: 100.0,
    });
    seen.add(queryUpper);
  }

  // 2. Exact city alias match
  if (queryLower in CITY_AIRPORTS) {
    for (const code of CITY_AIRPORTS[queryLower] ?? []) {
      if (!seen.has(code)) {
        results.push({
          code: code as Airport,
          name: code,
          match_type: "city",
          score: 90.0,
        });
        seen.add(code);
      }
    }
  }

  // 3. City alias prefix match
  if (!(queryLower in CITY_AIRPORTS)) {
    for (const [city, codes] of Object.entries(CITY_AIRPORTS)) {
      if (city.startsWith(queryLower)) {
        for (const code of codes) {
          if (!seen.has(code)) {
            results.push({
              code: code as Airport,
              name: code,
              match_type: "city",
              score: 80.0,
            });
            seen.add(code);
          }
        }
      }
    }
  }

  // 4. Airport name substring match (position-weighted score)
  for (const [code, name] of Object.entries(AIRPORT_NAMES)) {
    if (seen.has(code)) continue;
    const nameLower = name.toLowerCase();
    const pos = nameLower.indexOf(queryLower);
    if (pos !== -1) {
      const score = 70.0 - pos * 0.1;
      results.push({ code: code as Airport, name, match_type: "name", score });
      seen.add(code);
    }
  }

  // 5. IATA prefix match (≤3-char query)
  if (queryUpper.length <= 3) {
    for (const [code, name] of Object.entries(AIRPORT_NAMES)) {
      if (seen.has(code)) continue;
      if (code.startsWith(queryUpper)) {
        results.push({
          code: code as Airport,
          name,
          match_type: "iata_prefix",
          score: 60.0,
        });
        seen.add(code);
      }
    }
  }

  results.sort((a, b) => {
    if (a.score !== b.score) return b.score - a.score;
    return a.code < b.code ? -1 : a.code > b.code ? 1 : 0;
  });
  return results.slice(0, limit);
}
