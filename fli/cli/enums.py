import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        """Compatibility StrEnum for Python 3.10."""

        def __str__(self) -> str:
            return str(self.value)

        def _generate_next_value_(name, start, count, last_values):
            return name.lower()


class DayOfWeek(StrEnum):
    """Days of the week."""

    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"
