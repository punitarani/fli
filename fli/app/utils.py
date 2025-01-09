from enum import Enum


def format_enum(enum: Enum) -> str:
    """Format an enum value for display in a dropdown."""
    return " ".join(enum.name.split("_")).title()
