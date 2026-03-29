from enum import Enum


class DayOfWeek(Enum):
    """Days of the week."""

    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class OutputFormat(str, Enum):
    """Supported CLI output formats."""

    TEXT = "text"
    JSON = "json"
