"""Custom exceptions for the FastAPI server."""

from typing import Any

from fastapi import HTTPException, status


class FlightSearchError(HTTPException):
    """Base exception for flight search errors."""

    def __init__(
        self,
        detail: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        headers: dict[str, Any] | None = None,
    ):
        """Initialize the exception.

        Args:
            detail: Error message
            status_code: HTTP status code (default: 500)
            headers: Optional response headers

        """
        super().__init__(status_code=status_code, detail=detail, headers=headers)


class ValidationError(FlightSearchError):
    """Exception for validation errors."""

    def __init__(self, detail: str, headers: dict[str, Any] | None = None):
        """Initialize validation error.

        Args:
            detail: Error message
            headers: Optional response headers

        """
        super().__init__(
            detail=detail, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, headers=headers
        )


class NoFlightsFoundError(FlightSearchError):
    """Exception when no flights match the search criteria."""

    def __init__(self, detail: str = "No flights found matching the given criteria"):
        """Initialize no flights found error.

        Args:
            detail: Error message

        """
        super().__init__(detail=detail, status_code=status.HTTP_404_NOT_FOUND)


class SearchClientError(FlightSearchError):
    """Exception for search client errors."""

    def __init__(self, detail: str = "Failed to search flights"):
        """Initialize search client error.

        Args:
            detail: Error message

        """
        super().__init__(detail=detail, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
