"""Router for flight search endpoints."""

from fastapi import APIRouter, Request
from pydantic import ValidationError as PydanticValidationError

from fli.models import FlightResult, FlightSearchFilters
from fli.search import SearchFlights

from ..exceptions import NoFlightsFoundError, SearchClientError, ValidationError
from ..logging import logger

router = APIRouter()
search_client = SearchFlights()


@router.post("/search", response_model=list[FlightResult])
async def search_flights(request: Request, filters: dict) -> list[FlightResult]:
    """Search for flights using the given filters.

    Args:
        request: The FastAPI request object
        filters: Dictionary containing search filters

    Returns:
        List of FlightResult objects containing flight details

    Raises:
        ValidationError: If the filters are invalid
        NoFlightsFoundError: If no flights match the criteria
        SearchClientError: If there is an error with the search client

    """
    logger.info({
        "event": "search_flights_start",
        "request_id": request.state.request_id,
        "filters": filters,
    })

    # Basic validation
    if not filters.get("flight_segments"):
        logger.warning({
            "event": "search_flights_validation_failed",
            "request_id": request.state.request_id,
            "error": "No flight segments provided",
        })
        raise ValidationError("No flight segments provided")

    passenger_info = filters.get("passenger_info", {})
    if not passenger_info or passenger_info.get("adults", 0) <= 0:
        logger.warning({
            "event": "search_flights_validation_failed",
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

    # Validate filters
    try:
        validated_filters = FlightSearchFilters(**filters)
    except PydanticValidationError as e:
        logger.warning({
            "event": "search_flights_validation_failed",
            "request_id": request.state.request_id,
            "error": str(e),
        })
        raise ValidationError(str(e)) from e

    try:
        flights = search_client.search(validated_filters)
        if not flights:
            logger.info({
                "event": "search_flights_no_results",
                "request_id": request.state.request_id,
            })
            raise NoFlightsFoundError("No flights found matching the search criteria")

        logger.info({
            "event": "search_flights_success",
            "request_id": request.state.request_id,
            "num_flights": len(flights),
        })
        return flights

    except Exception as e:
        logger.error({
            "event": "search_flights_error",
            "request_id": request.state.request_id,
            "error": str(e),
        })
        raise SearchClientError(f"Failed to search flights: {str(e)}") from e
