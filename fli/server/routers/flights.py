"""Router for flight search endpoints."""

from fastapi import APIRouter, Request
from pydantic import ValidationError as PydanticValidationError

from fli.models import FlightResult, FlightSearchFilters
from fli.search import SearchFlights

from ..exceptions import SearchClientError, ValidationError
from ..logging import logger

router = APIRouter()


@router.post(
    "/search", response_model=list[FlightResult | tuple[FlightResult, FlightResult]] | None
)
async def search_flights(
    request: Request, filters: FlightSearchFilters
) -> list[FlightResult | tuple[FlightResult, FlightResult]] | None:
    """Search for flights using the given filters.

    Args:
        request: The FastAPI request object
        filters: FlightSearchFilters object containing search parameters

    Returns:
        List of FlightResult objects containing flight details

    Raises:
        ValidationError: If the filters are invalid
        NoFlightsFoundError: If no flights match the criteria
        SearchClientError: If there is an error with the search client

    """
    logger.info(
        {
            "event": "search_flights:start",
            "request_id": request.state.request_id,
            "filters": filters.model_dump(),
        }
    )

    try:
        search_client = SearchFlights()
        flights = search_client.search(filters)

        logger.info(
            {
                "event": "search_flights:success",
                "request_id": request.state.request_id,
                "num_flights": len(flights),
            }
        )

        return flights

    except PydanticValidationError as e:
        logger.error(
            {
                "event": "search_flights:validation:error",
                "request_id": request.state.request_id,
                "error": str(e),
            }
        )
        raise ValidationError(str(e)) from e
    except Exception as e:
        logger.error(
            {
                "event": "search_flights:error",
                "request_id": request.state.request_id,
                "error": str(e),
            }
        )
        raise SearchClientError(f"Failed to search flights: {str(e)}") from e
