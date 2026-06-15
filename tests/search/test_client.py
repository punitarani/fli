"""Unit tests for fli.search.client — error mapping, host extraction, and singleton."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from tenacity import wait_none

import fli.search.client as client_module
from fli.search.client import _host_from_url, _wrap_request_error, get_client, post_rpc
from fli.search.exceptions import (
    SearchBackendError,
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


def _resp(text: str):
    """Return a minimal stand-in for a curl_cffi Response."""
    r = MagicMock()
    r.text = text
    r.raise_for_status = MagicMock()
    return r


def _ok_body():
    return ")]}'\n\n" + json.dumps([["wrb.fr", None, json.dumps([[1, "data"]])]])


def _error_body(code: int):
    type_url = "type.googleapis.com/travel.frontend.flights.ErrorResponse"
    row = ["wrb.fr", None, None, None, None, [code, None, [[type_url, [[None, [], 0]]]]]]
    return ")]}'\n\n" + json.dumps([row])


@pytest.fixture(autouse=True)
def _no_backoff_sleep():
    """Strip the exponential wait from post_rpc so retry tests run instantly."""
    original = post_rpc.retry.wait
    post_rpc.retry.wait = wait_none()
    yield
    post_rpc.retry.wait = original


class TestPostRpcBackendErrors:
    """post_rpc must turn Google's HTTP-200 error envelope into a retryable error (issue #200)."""

    def test_returns_body_text_on_success(self):
        c = MagicMock()
        c.post.return_value = _resp(_ok_body())
        assert post_rpc(c, "https://x/y", "ENC") == _ok_body()
        assert c.post.call_count == 1

    def test_retries_transient_internal_error_then_succeeds(self):
        c = MagicMock()
        c.post.side_effect = [_resp(_error_body(13)), _resp(_error_body(13)), _resp(_ok_body())]
        assert post_rpc(c, "https://x/y", "ENC") == _ok_body()
        assert c.post.call_count == 3

    def test_exhausts_retries_and_raises_backend_error(self):
        c = MagicMock()
        c.post.return_value = _resp(_error_body(13))
        with pytest.raises(SearchBackendError) as exc_info:
            post_rpc(c, "https://x/y", "ENC")
        assert exc_info.value.code == 13
        # stop_after_attempt(4) → exactly four POSTs before giving up.
        assert c.post.call_count == 4

    def test_non_retryable_code_fails_fast(self):
        c = MagicMock()
        c.post.return_value = _resp(_error_body(3))  # INVALID_ARGUMENT
        with pytest.raises(SearchBackendError) as exc_info:
            post_rpc(c, "https://x/y", "ENC")
        assert exc_info.value.code == 3
        assert exc_info.value.retryable is False
        assert c.post.call_count == 1

    def test_post_receives_freq_body(self):
        c = MagicMock()
        c.post.return_value = _resp(_ok_body())
        post_rpc(c, "https://x/y", "MYENCODED")
        _, kwargs = c.post.call_args
        assert kwargs["data"] == "f.req=MYENCODED"
        assert kwargs["impersonate"] == "chrome"


class TestSearchBackendErrorRetryable:
    def test_transient_codes_are_retryable(self):
        for code in (13, 14, 4, 8, None, -1):
            assert SearchBackendError("x", code=code).retryable is True

    def test_bad_request_codes_are_not_retryable(self):
        for code in (3, 5, 7, 9, 11, 16):
            assert SearchBackendError("x", code=code).retryable is False


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
