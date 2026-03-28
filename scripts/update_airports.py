#!/usr/bin/env python3
"""Update airports.csv from the airportsdata package.

This script fetches current IATA airport codes and names from the
airportsdata package (https://pypi.org/project/airportsdata/) and
writes them to data/airports.csv in the format expected by
generate_enums.py.

Usage:
    pip install airportsdata
    python scripts/update_airports.py
"""

import csv
from pathlib import Path

import airportsdata

PROJECT_DIR = Path(__file__).parents[1].resolve()


def update_airports():
    """Fetch current IATA airports and write to data/airports.csv."""
    airports = airportsdata.load("IATA")

    output_path = PROJECT_DIR / "data" / "airports.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = sorted(airports.items())

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Code", "Name"])
        for code, info in rows:
            writer.writerow([code, info["name"]])

    print(f"Wrote {len(rows)} airports to {output_path}")


if __name__ == "__main__":
    update_airports()
