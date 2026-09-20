/**
 * Regenerates src/models/airport.ts and src/models/airline.ts from data/*.csv.
 *
 * Mirrors the Python project's scripts/generate_enums.py — same CSV inputs,
 * same digit-prefixed key handling (codes starting with a digit get a
 * leading underscore so they're valid identifiers).
 */

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(__dirname, "..", "..");
const dataDir = join(repoRoot, "data");
const outDir = join(__dirname, "..", "src", "models");

/**
 * Minimal RFC4180-compatible CSV parser. Mirrors Python's `csv.DictReader`
 * for the fields we actually use: it understands quoted values, embedded
 * commas, and `""` as an escaped double-quote (e.g. `PAQ,"Warren ""Bud""
 * Woods Palmer Municipal Airport"`). Returns `[code, name]` pairs from the
 * first two columns, skipping the header row.
 */
function parseCsv(path: string): Array<[string, string]> {
  const text = readFileSync(path, "utf8");
  const records: string[][] = [];
  let field = "";
  let row: string[] = [];
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += ch;
      }
      continue;
    }
    if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      row.push(field);
      field = "";
    } else if (ch === "\n" || ch === "\r") {
      // CRLF: consume the LF that follows the CR.
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      records.push(row);
      field = "";
      row = [];
    } else {
      field += ch;
    }
  }
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    records.push(row);
  }

  const out: Array<[string, string]> = [];
  for (let i = 1; i < records.length; i++) {
    const r = records[i];
    if (!r || r.length < 2) continue;
    const code = (r[0] ?? "").trim();
    const name = (r[1] ?? "").trim();
    if (code) out.push([code, name]);
  }
  return out;
}

function toKey(code: string): string {
  return /^[0-9]/.test(code) ? `_${code}` : code;
}

function escapeStringLiteral(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function renderEnum(
  typeName: string,
  namesConst: string,
  docHeader: string,
  rows: Array<[string, string]>,
): string {
  const entries: string[] = [];
  for (const [code, name] of rows) {
    const key = toKey(code);
    entries.push(`  ${key}: "${escapeStringLiteral(name)}",`);
  }

  const aliasEntries: string[] = [];
  for (const [code] of rows) {
    const key = toKey(code);
    aliasEntries.push(`  ${key}: "${key}",`);
  }

  return `${docHeader}
/** Map of IATA code → human-readable name (raw lookup, no enum wrapping). */
export const ${namesConst}: Record<string, string> = {
${entries.join("\n")}
};

/**
 * IATA code constants. Each value equals its key so ${typeName}.JFK === "JFK".
 * Codes that start with a digit are prefixed with "_" (e.g. ${typeName}._3F)
 * to remain valid identifiers; the leading "_" is stripped during wire serialisation.
 */
export const ${typeName} = {
${aliasEntries.join("\n")}
} as const;

export type ${typeName} = (typeof ${typeName})[keyof typeof ${typeName}];
`;
}

const airports = parseCsv(join(dataDir, "airports.csv"));
const airlines = parseCsv(join(dataDir, "airlines.csv"));

// Airlines file in Python also includes alliance pseudo-codes appended at the
// end. data/airlines.csv already lists IATA carriers; the alliances live in
// the Python source as literal additions. Replicate that here.
const allianceRows: Array<[string, string]> = [
  ["ONEWORLD", "Oneworld"],
  ["SKYTEAM", "SkyTeam"],
  ["STAR_ALLIANCE", "Star Alliance"],
];

const allAirlines = [...airlines, ...allianceRows];

const airportFile = renderEnum(
  "Airport",
  "AIRPORT_NAMES",
  `/**
 * Airport IATA codes.
 *
 * Auto-generated from data/airports.csv — run \`bun run generate:enums\` to refresh.
 */`,
  airports,
);

const airlineFile = renderEnum(
  "Airline",
  "AIRLINE_NAMES",
  `/**
 * Airline IATA codes (plus alliance pseudo-codes ONEWORLD / SKYTEAM / STAR_ALLIANCE).
 *
 * Auto-generated from data/airlines.csv — run \`bun run generate:enums\` to refresh.
 */`,
  allAirlines,
);

writeFileSync(join(outDir, "airport.ts"), airportFile);
writeFileSync(join(outDir, "airline.ts"), airlineFile);

console.log(`Wrote ${airports.length} airports, ${allAirlines.length} airlines.`);
