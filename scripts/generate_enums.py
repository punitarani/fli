#!/usr/bin/env python3

import csv
from pathlib import Path

PROJECT_DIR = Path(__file__).parents[1].resolve()


def generate_airport_enum():
    airport_csv_path = PROJECT_DIR.joinpath("data", "airports.csv")
    airport_enum_path = PROJECT_DIR.joinpath("fli", "models", "airport.py")

    # Validate input file exists
    if not airport_csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {airport_csv_path}")

    # Read airport entries from CSV
    try:
        with open(airport_csv_path, "r", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            entries = [(row["Code"].strip().upper(), row["Name"].strip()) for row in reader]
    except (KeyError, csv.Error) as e:
        raise ValueError(f"Error reading CSV file: {e}")

    # Ensure output directory exists
    airport_enum_path.parent.mkdir(parents=True, exist_ok=True)

    # Write the Enum class to the output file
    with open(airport_enum_path, "w", encoding="utf-8") as output_file:
        output_file.write("from enum import Enum\n\n")
        output_file.write("class Airport(Enum):\n")

        for code, name in sorted(entries):
            # Sanitize enum key to ensure valid Python identifier
            sanitized_code = "".join(c if c.isalnum() else "_" for c in code)
            output_file.write(f'    {sanitized_code} = "{name}"\n')

    print(f"Generated {len(entries)} enums in {airport_enum_path}")


def generate_airline_enum():
    airline_csv_path = PROJECT_DIR.joinpath("data", "airlines.csv")
    airline_enum_path = PROJECT_DIR.joinpath("fli", "models", "airline.py")

    # Validate input file exists
    if not airline_csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {airline_csv_path}")

    # Read airline entries from CSV
    try:
        with open(airline_csv_path, "r", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            entries = [(row["IATA"].strip().upper(), row["Airline"].strip()) for row in reader]
    except (KeyError, csv.Error) as e:
        raise ValueError(f"Error reading CSV file: {e}")

    # Ensure output directory exists
    airline_enum_path.parent.mkdir(parents=True, exist_ok=True)

    # Write the Enum class to the output file
    with open(airline_enum_path, "w", encoding="utf-8") as output_file:
        output_file.write("from enum import Enum\n\n")
        output_file.write("class Airline(Enum):\n")

        for code, name in sorted(entries):
            # Sanitize enum key to ensure valid Python identifier
            sanitized_code = "".join(c if c.isalnum() else "_" for c in code)
            if sanitized_code[0].isdigit():
                output_file.write(f'    _{sanitized_code} = "{name}"\n')
            else:
                output_file.write(f'    {sanitized_code} = "{name}"\n')

    print(f"Generated {len(entries)} enums in {airline_enum_path}")


if __name__ == "__main__":
    generate_airport_enum()
    generate_airline_enum()
