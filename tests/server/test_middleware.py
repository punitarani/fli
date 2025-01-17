"""Tests for server middleware and logging."""

import logging
import re
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient

from fli.server.logging import CustomFormatter, setup_logging
from fli.server.middleware import RequestTracingMiddleware


def test_custom_formatter():
    """Test custom log formatter."""
    formatter = CustomFormatter("%(message)s")

    # Test with request ID
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None,
    )
    record.request_id = "test-id"
    formatted = formatter.format(record)
    assert "[Request-ID: test-id]" in formatted

    # Test with dict message
    record.msg = {"event": "test", "value": 123}
    formatted = formatter.format(record)
    assert "'event': 'test'" in formatted
    assert "'value': 123" in formatted


def test_request_tracing_middleware():
    """Test request tracing middleware."""
    app = FastAPI()

    @app.get("/test")
    async def test_endpoint():
        return {"message": "test"}

    @app.get("/error")
    async def error_endpoint():
        raise HTTPException(status_code=400, detail="Test error")

    @app.exception_handler(Exception)
    async def exception_handler(request: Request, exc: Exception):
        return Response(
            content=str(exc),
            status_code=500 if not isinstance(exc, HTTPException) else exc.status_code,
        )

    app.add_middleware(RequestTracingMiddleware)
    client = TestClient(app)

    # Test successful request
    response = client.get("/test")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert re.match(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        response.headers["X-Request-ID"],
    )

    # Test error request
    response = client.get("/error")
    assert response.status_code == 400
    assert "X-Request-ID" in response.headers


@pytest.mark.asyncio
async def test_middleware_logging():
    """Test middleware logging functionality."""
    # Create mock logger
    mock_logger = MagicMock()

    # Create test app with middleware
    app = FastAPI()
    middleware = RequestTracingMiddleware(app)

    @app.get("/test")
    async def test_endpoint():
        return {"message": "test"}

    # Create test request
    request = Request(scope={"type": "http", "method": "GET", "path": "/test", "headers": []})

    # Mock response
    async def mock_call_next(_):
        return Response(content="test", status_code=200)

    with patch("fli.server.middleware.logger", mock_logger):
        # Process request
        await middleware.dispatch(request, mock_call_next)

        # Check log calls
        assert mock_logger.info.call_count == 2

        # Check request log
        request_log = mock_logger.info.call_args_list[0][0][0]
        assert request_log["event"] == "request_started"
        assert "request_id" in request_log
        assert request_log["method"] == "GET"
        assert request_log["url"].endswith("/test")

        # Check response log
        response_log = mock_logger.info.call_args_list[1][0][0]
        assert response_log["event"] == "request_completed"
        assert response_log["status_code"] == 200


def test_setup_logging():
    """Test logging setup."""
    # Reset logging
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    logger = logging.getLogger("fli.server")
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Setup logging
    setup_logging(level="DEBUG")
    logger = logging.getLogger("fli.server")

    # Check logger configuration
    assert logger.level == logging.DEBUG
    assert len(logger.handlers) == 1

    handler = logger.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    assert isinstance(handler.formatter, CustomFormatter)
