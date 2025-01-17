"""Logging configuration for the FastAPI server."""

import logging
import sys
from typing import Any


class CustomFormatter(logging.Formatter):
    """Custom formatter adding correlation ID and structured output."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with additional fields."""
        # Add request_id if available
        request_id = getattr(record, "request_id", None)
        if request_id:
            record.msg = f"[Request-ID: {request_id}] {record.msg}"

        # Convert record to structured format if msg is a dict
        if isinstance(record.msg, dict):
            record.msg = self.format_dict(record.msg)

        return super().format(record)

    def format_dict(self, msg: dict[str, Any]) -> str:
        """Format dictionary into a structured log string."""
        return " | ".join(f"{k}={v}" for k, v in msg.items())


def setup_logging(level: str = "INFO") -> None:
    """Configure logging for the application.

    Args:
        level: Logging level (default: INFO)

    """
    # Create logger
    logger = logging.getLogger("fli.server")
    logger.setLevel(level)

    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    # Create formatter
    formatter = CustomFormatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    handler.setFormatter(formatter)

    # Add handler to logger
    logger.addHandler(handler)


# Create logger instance
logger = logging.getLogger("fli.server")
