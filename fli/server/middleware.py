"""Middleware for the FastAPI server."""

import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from .logging import logger


class RequestTracingMiddleware(BaseHTTPMiddleware):
    """Middleware to add request ID and logging."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Process the request.

        Args:
            request: The incoming request
            call_next: The next middleware/endpoint to call

        Returns:
            The response from the next middleware/endpoint

        """
        # Generate request ID
        request_id = str(uuid.uuid4())

        # Add request ID to request state
        request.state.request_id = request_id

        # Log request
        logger.info(
            {
                "event": "request_started",
                "request_id": request_id,
                "method": request.method,
                "url": str(request.url),
            }
        )

        try:
            # Process request
            response = await call_next(request)

            # Log response
            logger.info(
                {
                    "event": "request_completed",
                    "request_id": request_id,
                    "status_code": response.status_code,
                }
            )

            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id
            return response

        except Exception as e:
            # Log error
            logger.error(
                {
                    "event": "request_failed",
                    "request_id": request_id,
                    "error": str(e),
                }
            )
            raise
