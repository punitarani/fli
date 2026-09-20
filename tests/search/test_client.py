"""Unit tests for fli.search.client — error mapping, host extraction, and singleton."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import fli.search.client as client_module
from fli.search.client import _host_from_url, _wrap_request_error, get_client
from fli.search.exceptions import (
    SearchClientError,
    SearchConnectionError,
    SearchHTTPError,
    SearchTimeoutError,
)


@pytest.fixture(autouse=True)
def _reset_client_singleton():
    """Each test starts with a clean singleton so tests don't share state."""
    original = client_module.client
    client_module.client = None
    yield
    client_module.client = original


class TestWrapRequestError:
    """_wrap_request_error must map curl_cffi errors to typed SearchClientError subclasses."""

    def test_timeout_exc_returns_search_timeout_error(self):
        from curl_cffi.requests import exceptions as curl_exc

        exc = curl_exc.Timeout("curl: (28) timed out", 28, None)
        result = _wrap_request_error("GET", "https://www.google.com/path", exc)
        assert isinstance(result, SearchTimeoutError)

    def test_timeout_message_includes_host(self):
        from curl_cffi.requests import exceptions as curl_exc

        exc = curl_exc.Timeout("timed out", 28, None)
        result = _wrap_request_error("GET", "https://flights.google.com/search", exc)
        assert "flights.google.com" in str(result)

    def test_connection_exc_returns_search_connection_error(self):
        from curl_cffi.requests import exceptions as curl_exc

        exc = curl_exc.ConnectionError("dns lookup failed", 6, None)
        result = _wrap_request_error("GET", "https://www.google.com/", exc)
        assert isinstance(result, SearchConnectionError)

    def test_http_exc_with_status_returns_search_http_error(self):
        from curl_cffi.requests import exceptions as curl_exc

        mock_response = MagicMock()
        mock_response.status_code = 403
        exc = curl_exc.HTTPError("403 Forbidden", 403, mock_response)
        exc.response = mock_response

        result = _wrap_request_error("POST", "https://www.google.com/", exc)
        assert isinstance(result, SearchHTTPError)
        assert result.status_code == 403
        assert "403" in str(result)

    def test_http_exc_without_response_has_none_status(self):
        from curl_cffi.requests import exceptions as curl_exc

        exc = curl_exc.HTTPError("error", 0, None)
        result = _wrap_request_error("POST", "https://www.google.com/", exc)
        assert isinstance(result, SearchHTTPError)
        assert result.status_code is None

    def test_unknown_exc_returns_search_client_error(self):
        exc = ValueError("something unexpected")
        result = _wrap_request_error("GET", "https://www.google.com/", exc)
        assert isinstance(result, SearchClientError)
        assert not isinstance(result, SearchTimeoutError | SearchConnectionError | SearchHTTPError)

    def test_already_typed_error_passes_through_unchanged(self):
        original = SearchTimeoutError("already typed")
        result = _wrap_request_error("GET", "https://www.google.com/", original)
        assert result is original

    def test_message_uses_url_as_fallback_on_parse_failure(self):
        exc = RuntimeError("boom")
        result = _wrap_request_error("GET", "not-a-url", exc)
        # Should include the raw string when urlparse can't extract a host.
        assert "not-a-url" in str(result)


class TestHostFromUrl:
    def test_standard_https_url(self):
        assert _host_from_url("https://www.google.com/path?q=1") == "www.google.com"

    def test_url_without_host_returns_input(self):
        assert _host_from_url("not-a-url") == "not-a-url"

    def test_empty_string_returns_empty(self):
        # Shouldn't raise — empty is a valid degenerate case.
        result = _host_from_url("")
        assert result == ""


class TestGetClientSingleton:
    def test_returns_client_instance(self):
        from fli.search.client import Client

        c = get_client()
        assert isinstance(c, Client)

    def test_returns_same_instance_on_repeated_calls(self):
        c1 = get_client()
        c2 = get_client()
        assert c1 is c2

    def test_reset_global_creates_new_instance(self):
        c1 = get_client()
        client_module.client = None
        c2 = get_client()
        assert c1 is not c2
