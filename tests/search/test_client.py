"""Unit tests for fli.search.client — error mapping, host extraction, and singleton."""

from __future__ import annotations

import os
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


class TestConsentCookie:
    """EU/EEA IPs hit Google's consent interstitial without a SOCS cookie."""

    def test_session_carries_socs_cookie_for_google(self, monkeypatch):
        monkeypatch.setattr(client_module, "SOCS_COOKIE", "TESTSOCS")
        session = get_client()._session()
        assert session.cookies.get("SOCS", domain=".google.com") == "TESTSOCS"

    def test_empty_env_value_sends_no_cookie(self, monkeypatch):
        monkeypatch.setattr(client_module, "SOCS_COOKIE", "")
        session = get_client()._session()
        assert session.cookies.get("SOCS", domain=".google.com") is None

    @staticmethod
    def _reimport_client(env_value: str | None):
        """Re-evaluate the module's import-time env read, in a throwaway module.

        ``importlib.reload`` would rebind the real ``fli.search.client``,
        resetting the process-wide client singleton for every later test.
        Executing the source into a fresh module object exercises the same
        import-time expression while leaving ``sys.modules`` untouched.
        """
        import importlib.util
        import os

        previous = os.environ.get("FLI_SOCS_COOKIE")
        if env_value is None:
            os.environ.pop("FLI_SOCS_COOKIE", None)
        else:
            os.environ["FLI_SOCS_COOKIE"] = env_value
        try:
            spec = importlib.util.spec_from_file_location(
                "fli_client_env_probe", client_module.__file__
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        finally:
            if previous is None:
                os.environ.pop("FLI_SOCS_COOKIE", None)
            else:
                os.environ["FLI_SOCS_COOKIE"] = previous

    def test_empty_env_var_disables_the_cookie(self):
        """``FLI_SOCS_COOKIE=""`` must mean "send nothing", not "use the default"."""
        module = self._reimport_client("")
        assert module.SOCS_COOKIE == ""
        session = module.Client()._session()
        assert session.cookies.get("SOCS", domain=".google.com") is None

    def test_env_var_overrides_the_default(self):
        module = self._reimport_client("OVERRIDDEN")
        assert module.SOCS_COOKIE == "OVERRIDDEN"

    def test_unset_env_var_keeps_the_cookie_on(self):
        """The author's default stays on — EU IPs otherwise hit the consent page.

        Resolved from a clean environment rather than from the module constant,
        so the test does not fail for a developer who exports the variable.
        """
        module = self._reimport_client(None)
        assert module.SOCS_COOKIE == module.DEFAULT_SOCS_COOKIE
        assert module.SOCS_COOKIE

    def test_process_client_module_is_untouched(self):
        """The probes above must not disturb the real module or its singleton."""
        before = client_module.client
        self._reimport_client("")
        assert client_module.client is before
        assert client_module.SOCS_COOKIE == os.environ.get(
            "FLI_SOCS_COOKIE", client_module.DEFAULT_SOCS_COOKIE
        )
