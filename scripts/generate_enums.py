#!/usr/bin/env python3
"""Script to generate Airport and Airline enums from CSV data files.

This script reads airport and airline data from CSV files and generates corresponding
Python Enum classes. The generated enums are used throughout the application to ensure
consistent handling of airport and airline codes.

The script expects CSV files in the following locations:
- data/airports.csv: Contains airport codes and names
- data/airlines.csv: Contains airline IATA codes and names

The generated enum files are written to:
- fli/models/airport.py: Contains the Airport enum
- fli/models/airline.py: Contains the Airline enum
"""

import csv
from pathlib import Path

PROJECT_DIR = Path(__file__).parents[1].resolve()


def generate_airport_enum():
    """Generate Airport enum class from airports.csv data.

    Reads airport codes and names from the CSV file and generates a Python Enum class
    with airport codes as enum members and airport names as their values.

    Raises:
        FileNotFoundError: If the airports.csv file is not found
        ValueError: If there are errors reading or parsing the CSV file

    """
    airport_csv_path = PROJECT_DIR.joinpath("data", "airports.csv")
    airport_enum_path = PROJECT_DIR.joinpath("fli", "models", "airport.py")

    # Validate input file exists
    if not airport_csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {airport_csv_path}")

    # Read airport entries from CSV
    try:
        with open(airport_csv_path, encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            entries = [(row["Code"].strip().upper(), row["Name"].strip()) for row in reader]
    except (KeyError, csv.Error) as e:
        raise ValueError(f"Error reading CSV file: {e}") from e

    # Ensure output directory exists
    airport_enum_path.parent.mkdir(parents=True, exist_ok=True)

    # Write the Enum class to the output file
    with open(airport_enum_path, "w", encoding="utf-8") as output_file:
        output_file.write("from enum import Enum\n\n")
        output_file.write("class Airport(Enum):\n")

        for code, name in entries:
            # Sanitize enum key to ensure valid Python identifier
            sanitized_code = "".join(c if c.isalnum() else "_" for c in code)
            output_file.write(f'    {sanitized_code} = "{name}"\n')

    print(f"Generated {len(entries)} enums in {airport_enum_path}")


def generate_airline_enum():
    """Generate Airline enum class from airlines.csv data.

    Reads airline IATA codes and names from the CSV file and generates a Python Enum class
    with airline codes as enum members and airline names as their values. Handles cases
    where airline codes start with numbers by prefixing them with an underscore.

    Raises:
        FileNotFoundError: If the airlines.csv file is not found
        ValueError: If there are errors reading or parsing the CSV file

    """
    airline_csv_path = PROJECT_DIR.joinpath("data", "airlines.csv")
    airline_enum_path = PROJECT_DIR.joinpath("fli", "models", "airline.py")

    # Validate input file exists
    if not airline_csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {airline_csv_path}")

    # Read airline entries from CSV
    try:
        with open(airline_csv_path, encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            entries = [(row["IATA"].strip().upper(), row["Airline"].strip()) for row in reader]
    except (KeyError, csv.Error) as e:
        raise ValueError(f"Error reading CSV file: {e}") from e

    # Ensure output directory exists
    airline_enum_path.parent.mkdir(parents=True, exist_ok=True)

    # Write the Enum class to the output file
    with open(airline_enum_path, "w", encoding="utf-8") as output_file:
        output_file.write("from enum import Enum\n\n")
        output_file.write("class Airline(Enum):\n")

        for code, name in entries:
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
