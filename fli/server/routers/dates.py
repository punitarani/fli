"""Router for date search endpoints."""

from fastapi import APIRouter, Request
from pydantic import ValidationError as PydanticValidationError

from fli.models import DateSearchFilters
from fli.search import SearchDates
from fli.search.dates import DatePrice

from ..exceptions import NoFlightsFoundError, SearchClientError, ValidationError
from ..logging import logger

router = APIRouter()
search_client = SearchDates()


@router.post("/search", response_model=list[DatePrice])
async def search_dates(request: Request, filters: dict) -> list[DatePrice]:
    """Search for flight dates using the given filters.

    Args:
        request: The FastAPI request object
        filters: Dictionary containing search filters

    Returns:
        List of DatePrice objects containing date and price pairs

    Raises:
        ValidationError: If the filters are invalid
        NoFlightsFoundError: If no dates match the criteria
        SearchClientError: If there is an error with the search client

    """
    logger.info({
        "event": "search_dates_start",
        "request_id": request.state.request_id,
        "filters": filters,
    })

    # Basic validation
    if not filters.get("flight_segments"):
        logger.warning({
            "event": "search_dates_validation_failed",
            "request_id": request.state.request_id,
            "error": "No flight segments provided",
        })
        raise ValidationError("No flight segments provided")

    passenger_info = filters.get("passenger_info", {})
    if not passenger_info or passenger_info.get("adults", 0) <= 0:
        logger.warning({
            "event": "search_dates_validation_failed",
            "request_id": request.state.request_id,
            "error": "Invalid passenger count",
        })
        raise ValidationError("Invalid passenger count")

    # Convert airport codes to lists if needed
    for segment in filters["flight_segments"]:
        if not isinstance(segment["departure_airport"], list):
            segment["departure_airport"] = [[code, 0] for code in segment["departure_airport"]]
        if not isinstance(segment["arrival_airport"], list):
            segment["arrival_airport"] = [[code, 0] for code in segment["arrival_airport"]]

    # Validate filters - let the model handle date swapping
    try:
        validated_filters = DateSearchFilters(**filters)
    except PydanticValidationError as e:
        # Only raise validation error if it's not about date order
        if not any("date cannot be after" in err["msg"] for err in e.errors()):
            logger.warning({
                "event": "search_dates_validation_failed",
                "request_id": request.state.request_id,
                "error": str(e),
            })
            raise ValidationError(str(e)) from e
        # Otherwise, let the model handle it by swapping dates
        validated_filters = DateSearchFilters(**filters)

    try:
        dates = search_client.search(validated_filters)
        if not dates:
            logger.info({
                "event": "search_dates_no_results",
                "request_id": request.state.request_id,
            })
            raise NoFlightsFoundError("No dates found matching the search criteria")

        logger.info({
            "event": "search_dates_success",
            "request_id": request.state.request_id,
            "num_dates": len(dates),
        })
        return dates

    except Exception as e:
        logger.error({
            "event": "search_dates_error",
            "request_id": request.state.request_id,
            "error": str(e),
        })
        raise SearchClientError(f"Failed to search dates: {str(e)}") from e
