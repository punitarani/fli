#!/usr/bin/env python3
"""Script to generate Airport and Airline enums from CSV data files.

This script reads airport and airline data from CSV files and generates
corresponding Python ``Enum`` classes. The generated enums are used
throughout the application to ensure consistent handling of airport and
airline codes.

The script expects CSV files in the following locations:
- ``data/airports.csv``: Contains airport codes and names
- ``data/airlines.csv``: Contains airline IATA codes and names

The generated enum files are written to:
- ``fli/models/airport.py``: Contains the ``Airport`` enum
- ``fli/models/airline.py``: Contains the ``Airline`` enum

Output format
-------------

We emit a single dict literal containing every (code → human name) pair
and construct the ``Enum`` programmatically via ``Enum(name, mapping)``.
This is dramatically faster to import than the previous per-member
``class`` body — a 7,883-member ``Airport`` enum import drops from
~310ms to ~70ms because Python parses one dict literal instead of
running 7,883 metaclass-driven attribute assignments. The runtime API
(``Airport.JFK``, ``isinstance``, Pydantic compat, ``__members__``,
iteration) is identical to the previous form.
"""

import csv
from pathlib import Path

PROJECT_DIR = Path(__file__).parents[1].resolve()


def _sanitize_code(code: str, allow_digit_prefix: bool = False) -> str:
    """Return a valid Python identifier for an IATA code.

    Airline codes that start with a digit (e.g. ``3F``) are prefixed
    with an underscore to keep them Python-legal. Airport codes never
    start with a digit, so the prefix is gated on the caller.
    """
    sanitized = "".join(c if c.isalnum() else "_" for c in code)
    if allow_digit_prefix and sanitized and sanitized[0].isdigit():
        sanitized = f"_{sanitized}"
    return sanitized


def _write_enum_module(
    output_path: Path,
    enum_name: str,
    doc: str,
    source_csv: str,
    entries: list[tuple[str, str]],
) -> None:
    """Write a Python module that defines ``enum_name`` from a dict literal.

    The generated module exposes two public names at module scope:

    * ``<enum_name>`` — the ``Enum`` class users import (e.g. ``Airport``).
      Identical public surface to a class-body-defined Enum: attribute
      access, value lookup, isinstance checks, Pydantic field typing,
      and iteration all behave the same way. Built through the
      :class:`enum.Enum` functional API so the metaclass only walks the
      mapping once at module load instead of once per member, cutting
      import time ~5x for a 7,883-entry enum.

    * ``<ENUM_NAME>_NAMES`` — the underlying ``dict[str, str]`` of
      ``IATA-code → human-readable-name``. Public so callers that want
      raw dict semantics (cheap ``in`` checks, iteration without paying
      Enum-member overhead, JSON dumping) can use it directly. The
      ``Enum`` stays the canonical type for typed APIs; the dict is the
      fast path.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    map_name = f"{enum_name.upper()}_NAMES"
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(f'"""{doc}\n\n')
        fh.write(f"Auto-generated from {source_csv}.\n\n")
        fh.write("Exports:\n\n")
        fh.write(
            f"* :data:`{enum_name}` — the ``Enum`` class for typed APIs.\n"
            f"* :data:`{map_name}` — the underlying ``dict[code, name]``\n"
            f"  for callers that want raw dict speed.\n"
        )
        fh.write('"""\n\n')
        fh.write("from enum import Enum\n\n")
        fh.write(
            "# A single dict literal — Python parses this in one pass.\n"
            "# Defining the same data as ``class <Enum>(Enum):`` members\n"
            "# costs one metaclass call per member; ``Enum(name, mapping)``\n"
            "# below walks the dict once instead.\n"
        )
        fh.write(f"{map_name}: dict[str, str] = {{\n")
        for code, name in entries:
            sanitized = _sanitize_code(code, allow_digit_prefix=(enum_name == "Airline"))
            # Use repr() for proper escaping of any quotes/backslashes.
            fh.write(f"    {sanitized!r}: {name!r},\n")
        fh.write("}\n\n")
        fh.write(
            f'{enum_name} = Enum({enum_name!r}, {map_name})\n{enum_name}.__doc__ = """{doc}"""\n'
        )


def generate_airport_enum() -> None:
    """Generate ``Airport`` enum from ``data/airports.csv``."""
    csv_path = PROJECT_DIR / "data" / "airports.csv"
    out_path = PROJECT_DIR / "fli" / "models" / "airport.py"
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    try:
        with open(csv_path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            entries = [(row["Code"].strip().upper(), row["Name"].strip()) for row in reader]
    except (KeyError, csv.Error) as e:
        raise ValueError(f"Error reading CSV file: {e}") from e

    _write_enum_module(
        out_path,
        enum_name="Airport",
        doc="Airport IATA codes.",
        source_csv="data/airports.csv",
        entries=entries,
    )
    print(f"Generated {len(entries)} Airport members in {out_path}")


def generate_airline_enum() -> None:
    """Generate ``Airline`` enum from ``data/airlines.csv``.

    Three manual aliases — ``ONEWORLD``, ``SKYTEAM``, ``STAR_ALLIANCE`` —
    are appended after the CSV-derived entries. Those values are not
    actual IATA airline codes, but Google's flight-search API accepts
    them in the ``airlines`` filter as alliance pseudo-codes and the
    parser surfaces them as :class:`Airline` members. Keep them in sync
    with :data:`fli.models.google_flights.base.Alliance`.
    """
    csv_path = PROJECT_DIR / "data" / "airlines.csv"
    out_path = PROJECT_DIR / "fli" / "models" / "airline.py"
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    try:
        with open(csv_path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            entries = [(row["IATA"].strip().upper(), row["Airline"].strip()) for row in reader]
    except (KeyError, csv.Error) as e:
        raise ValueError(f"Error reading CSV file: {e}") from e

    # Append alliance pseudo-codes. Position matters only for
    # iteration order — value-based lookups (``Airline("Oneworld")``)
    # work regardless.
    entries.extend(
        [
            ("ONEWORLD", "Oneworld"),
            ("SKYTEAM", "SkyTeam"),
            ("STAR_ALLIANCE", "Star Alliance"),
        ]
    )

    _write_enum_module(
        out_path,
        enum_name="Airline",
        doc="Airline IATA codes.",
        source_csv="data/airlines.csv",
        entries=entries,
    )
    print(f"Generated {len(entries)} Airline members in {out_path}")


if __name__ == "__main__":
    generate_airport_enum()
    generate_airline_enum()
