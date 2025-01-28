"""Router for date search endpoints."""

from fastapi import APIRouter, Request

from fli.models import DateSearchFilters
from fli.search.dates import DatePrice, SearchDates

from ..exceptions import SearchClientError
from ..logging import logger

router = APIRouter()


@router.post("/search", response_model=list[DatePrice])
async def search_dates(request: Request, filters: DateSearchFilters) -> list[DatePrice] | None:
    """Search for flight dates using the given filters.

    Args:
        request: The FastAPI request object
        filters: DateSearchFilters object containing search parameters

    Returns:
        List of DatePrice objects containing date and price pairs

    Raises:
        ValidationError: If the filters are invalid
        NoFlightsFoundError: If no dates match the criteria
        SearchClientError: If there is an error with the search client

    """
    logger.info(
        {
            "event": "search_dates:start",
            "request_id": request.state.request_id,
            "filters": filters.model_dump(),
        }
    )

    try:
        search_client = SearchDates()
        dates = search_client.search(filters)

        logger.info(
            {
                "event": "search_dates:success",
                "request_id": request.state.request_id,
                "num_dates": len(dates),
            }
        )

        return dates

    except Exception as e:
        logger.error(
            {
                "event": "search_dates:error",
                "request_id": request.state.request_id,
                "error": str(e),
            }
        )
        raise SearchClientError(f"Failed to search dates: {str(e)}") from e
