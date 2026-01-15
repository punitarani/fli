try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        """Shim for Python < 3.11."""

        def __str__(self):
            return str(self.value)

        def __format__(self, format_spec):
            return str(self.value).__format__(format_spec)


class DayOfWeek(StrEnum):
    """Days of the week."""

    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"
