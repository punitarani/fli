"""Tests for TLS certificate error classification and CA-bundle configuration.

Carries forward the TLS half of PR #164 (the `error_type` half already
landed via PR #248's shared classifier). Every test below explicitly
clears/sets all three CA-bundle env vars — never relies on ambient state —
so a developer's own `REQUESTS_CA_BUNDLE` (common on corporate machines)
can't leak into the assertions.
"""

from __future__ import annotations

import pytest
from curl_cffi.requests import exceptions as curl_exc

import fli.search.client as client_module
from fli.search.client import Client, _ca_bundle_from_env, _wrap_request_error
from fli.search.exceptions import SearchCertificateError, SearchConnectionError


@pytest.fixture(autouse=True)
def _clean_ca_bundle_env(monkeypatch):
    """Clear all three CA-bundle env vars before every test in this module.

    Individual tests opt back in with ``monkeypatch.setenv`` for the
    variable(s) they care about — this fixture only guarantees no ambient
    value (e.g. a developer's own ``REQUESTS_CA_BUNDLE``) leaks in.

    Fix round 1 (C1) added an equivalent autouse fixture to
    ``tests/conftest.py`` that clears the same three variables for the
    *whole* suite, which makes the delenv calls here mechanically
    redundant. Kept anyway, deliberately: this file's entire subject is
    CA-bundle env var behavior, so a reader should be able to trust its
    isolation by reading this file alone, without having to go verify
    conftest.py also does it — explicit beats implicit for the one file
    where it's the whole point.
    """
    monkeypatch.delenv("FLI_CA_BUNDLE", raising=False)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)


@pytest.fixture(autouse=True)
def _reset_client_singleton():
    """Each test starts with a clean singleton so tests don't share state."""
    original = client_module.client
    client_module.client = None
    yield
    client_module.client = original


# ---------------------------------------------------------------------------
# _ca_bundle_from_env: precedence, empty values, and bad paths
# ---------------------------------------------------------------------------


class TestCaBundleFromEnv:
    def test_fli_ca_bundle_wins_over_the_others(self, monkeypatch, tmp_path):
        fli_bundle = tmp_path / "fli.pem"
        curl_bundle = tmp_path / "curl.pem"
        requests_bundle = tmp_path / "requests.pem"
        for path in (fli_bundle, curl_bundle, requests_bundle):
            path.write_text("cert data", encoding="utf-8")

        monkeypatch.setenv("FLI_CA_BUNDLE", str(fli_bundle))
        monkeypatch.setenv("CURL_CA_BUNDLE", str(curl_bundle))
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(requests_bundle))

        assert _ca_bundle_from_env() == str(fli_bundle)

    def test_curl_ca_bundle_wins_over_requests_ca_bundle(self, monkeypatch, tmp_path):
        curl_bundle = tmp_path / "curl.pem"
        requests_bundle = tmp_path / "requests.pem"
        for path in (curl_bundle, requests_bundle):
            path.write_text("cert data", encoding="utf-8")

        monkeypatch.delenv("FLI_CA_BUNDLE", raising=False)
        monkeypatch.setenv("CURL_CA_BUNDLE", str(curl_bundle))
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(requests_bundle))

        assert _ca_bundle_from_env() == str(curl_bundle)

    def test_falls_back_to_requests_ca_bundle_alone(self, monkeypatch, tmp_path):
        requests_bundle = tmp_path / "requests.pem"
        requests_bundle.write_text("cert data", encoding="utf-8")

        monkeypatch.delenv("FLI_CA_BUNDLE", raising=False)
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(requests_bundle))

        assert _ca_bundle_from_env() == str(requests_bundle)

    def test_empty_values_are_skipped_in_favor_of_the_next_variable(self, monkeypatch, tmp_path):
        """An empty string (not unset) should be treated the same as unset."""
        requests_bundle = tmp_path / "requests.pem"
        requests_bundle.write_text("cert data", encoding="utf-8")

        monkeypatch.setenv("FLI_CA_BUNDLE", "")
        monkeypatch.setenv("CURL_CA_BUNDLE", "")
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(requests_bundle))

        assert _ca_bundle_from_env() == str(requests_bundle)

    def test_no_variables_set_returns_none(self, monkeypatch):
        monkeypatch.delenv("FLI_CA_BUNDLE", raising=False)
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

        assert _ca_bundle_from_env() is None

    def test_missing_path_raises_certificate_error_naming_the_variable(self, monkeypatch, tmp_path):
        missing = tmp_path / "does-not-exist.pem"
        monkeypatch.setenv("FLI_CA_BUNDLE", str(missing))
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

        with pytest.raises(SearchCertificateError) as exc_info:
            _ca_bundle_from_env()
        assert "FLI_CA_BUNDLE" in str(exc_info.value)
        assert str(missing) in str(exc_info.value)

    def test_directory_path_is_not_a_readable_file(self, monkeypatch, tmp_path):
        """A directory passes ``os.access`` but is not a bundle — ``isfile`` must reject it."""
        directory = tmp_path / "not-a-file"
        directory.mkdir()
        monkeypatch.delenv("FLI_CA_BUNDLE", raising=False)
        monkeypatch.setenv("CURL_CA_BUNDLE", str(directory))
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

        with pytest.raises(SearchCertificateError) as exc_info:
            _ca_bundle_from_env()
        assert "CURL_CA_BUNDLE" in str(exc_info.value)

    def test_bad_path_in_lower_priority_variable_still_raises(self, monkeypatch, tmp_path):
        """Precedence is only for *finding* the bundle — a bad path never falls through."""
        missing = tmp_path / "missing.pem"
        monkeypatch.delenv("FLI_CA_BUNDLE", raising=False)
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(missing))

        with pytest.raises(SearchCertificateError, match="REQUESTS_CA_BUNDLE"):
            _ca_bundle_from_env()


# ---------------------------------------------------------------------------
# _session(): applies the configured bundle, keeps the SOCS cookie either way
# ---------------------------------------------------------------------------


class TestSessionCaBundle:
    def test_session_uses_configured_ca_bundle(self, monkeypatch, tmp_path):
        ca_bundle = tmp_path / "custom-ca.pem"
        ca_bundle.write_text("cert data", encoding="utf-8")

        monkeypatch.setenv("FLI_CA_BUNDLE", str(ca_bundle))
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

        # A fresh Client — _session() is cached per-thread, so an existing
        # instance would silently reuse a session built before the env was
        # patched.
        client = Client()
        session = client._session()

        assert session.verify == str(ca_bundle)

    def test_session_leaves_default_verify_when_unconfigured(self, monkeypatch):
        monkeypatch.delenv("FLI_CA_BUNDLE", raising=False)
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

        client = Client()
        session = client._session()

        assert session.verify is True

    def test_socs_cookie_still_set_when_ca_bundle_configured(self, monkeypatch, tmp_path):
        ca_bundle = tmp_path / "custom-ca.pem"
        ca_bundle.write_text("cert data", encoding="utf-8")
        monkeypatch.setenv("FLI_CA_BUNDLE", str(ca_bundle))
        monkeypatch.setattr(client_module, "SOCS_COOKIE", "TESTSOCS")

        client = Client()
        session = client._session()

        assert session.cookies.get("SOCS", domain=".google.com") == "TESTSOCS"

    def test_socs_cookie_still_set_when_ca_bundle_unconfigured(self, monkeypatch):
        monkeypatch.setattr(client_module, "SOCS_COOKIE", "TESTSOCS")

        client = Client()
        session = client._session()

        assert session.cookies.get("SOCS", domain=".google.com") == "TESTSOCS"

    def test_bad_ca_bundle_raises_on_first_session_access(self, monkeypatch, tmp_path):
        missing = tmp_path / "missing-ca.pem"
        monkeypatch.setenv("FLI_CA_BUNDLE", str(missing))

        client = Client()

        with pytest.raises(SearchCertificateError, match="FLI_CA_BUNDLE"):
            client._session()


# ---------------------------------------------------------------------------
# _wrap_request_error: certificate mapping, checked before the generic
# connection/SSL mapping, without disturbing the existing mappings.
# ---------------------------------------------------------------------------


class TestWrapRequestErrorCertificate:
    def test_certificate_verify_error_maps_to_search_certificate_error(self):
        exc = curl_exc.CertificateVerifyError("unable to get local issuer certificate", 60, None)

        wrapped = _wrap_request_error("GET", "https://www.google.com/travel/flights", exc)

        assert isinstance(wrapped, SearchCertificateError)
        assert "TLS certificate verification failed" in str(wrapped)
        assert "FLI_CA_BUNDLE" in str(wrapped)
        assert "CURL_CA_BUNDLE" in str(wrapped)
        assert "REQUESTS_CA_BUNDLE" in str(wrapped)

    def test_certificate_verify_error_is_not_reported_as_plain_connection_error(self):
        """A cert failure is a SSLError/ConnectionError subclass — order matters.

        Without checking CertificateVerifyError first, the generic
        ``isinstance(exc, curl_exc.ConnectionError)`` branch below would
        catch it and report a vague "check your connection" message instead
        of naming the fix.
        """
        exc = curl_exc.CertificateVerifyError("self signed certificate", 60, None)

        wrapped = _wrap_request_error("GET", "https://www.google.com/", exc)

        assert type(wrapped) is SearchCertificateError
        assert type(wrapped) is not SearchConnectionError

    def test_code_60_on_a_bare_connection_error_also_maps_to_certificate_error(self):
        """Forward-compat: if a future curl_cffi ever raises the base class directly.

        In the installed curl_cffi (0.15.0), ``code2error`` deterministically
        maps ``CurlECode.PEER_FAILED_VERIFICATION`` (60) to
        ``CertificateVerifyError`` specifically — this exact shape is not
        reachable through today's request path. It mirrors the
        ``getattr(curl_exc, "CertificateVerifyError", ())`` forward-compat
        guard already used below: cheap insurance against a future release
        raising the plain base class with the same code instead.
        """
        exc = curl_exc.ConnectionError("SSL peer certificate could not be verified", 60, None)

        wrapped = _wrap_request_error("GET", "https://www.google.com/", exc)

        assert isinstance(wrapped, SearchCertificateError)

    def test_timeout_still_maps_to_search_timeout_error(self):
        exc = curl_exc.Timeout("curl: (28) timed out", 28, None)
        wrapped = _wrap_request_error("GET", "https://www.google.com/", exc)
        from fli.search.exceptions import SearchTimeoutError

        assert isinstance(wrapped, SearchTimeoutError)

    def test_plain_connection_error_still_maps_to_search_connection_error(self):
        exc = curl_exc.ConnectionError("dns lookup failed", 6, None)
        wrapped = _wrap_request_error("GET", "https://www.google.com/", exc)

        assert isinstance(wrapped, SearchConnectionError)
        assert not isinstance(wrapped, SearchCertificateError)

    def test_http_error_still_maps_to_search_http_error(self):
        from unittest.mock import MagicMock

        from fli.search.exceptions import SearchHTTPError

        mock_response = MagicMock()
        mock_response.status_code = 403
        exc = curl_exc.HTTPError("403 Forbidden", 403, mock_response)
        exc.response = mock_response

        wrapped = _wrap_request_error("POST", "https://www.google.com/", exc)

        assert isinstance(wrapped, SearchHTTPError)
        assert wrapped.status_code == 403


# ---------------------------------------------------------------------------
# No retry for deterministic certificate failures.
# ---------------------------------------------------------------------------


class TestCertificateErrorIsNotRetried:
    """A bad CA path or an untrusted certificate never fixes itself on retry.

    ``Client.get``/``post`` retry everything by default (3 attempts,
    exponential backoff) — that is right for a transient connection blip but
    wastes the user's time (and the retry backoff) on a deterministic TLS
    failure before they ever see the actionable message. ``wait`` is patched
    to zero so a retried test does not actually sleep through the backoff.
    """

    @pytest.fixture(autouse=True)
    def _no_sleep(self, monkeypatch):
        """Replace both methods' backoff with an instant wait for this class."""
        from tenacity import wait_none

        monkeypatch.setattr(Client.get.retry, "wait", wait_none())
        monkeypatch.setattr(Client.post.retry, "wait", wait_none())

    def test_certificate_error_is_attempted_exactly_once(self, monkeypatch):
        client = Client()
        monkeypatch.setattr(client._rate_limiter, "acquire", lambda: None)

        calls = {"count": 0}

        class _FakeSession:
            def get(self, url, **kwargs):
                calls["count"] += 1
                raise curl_exc.CertificateVerifyError("bad cert", 60, None)

        monkeypatch.setattr(client, "_session", lambda: _FakeSession())

        with pytest.raises(SearchCertificateError):
            client.get("https://www.google.com/travel/flights")

        assert calls["count"] == 1

    def test_plain_connection_error_is_still_retried_three_times(self, monkeypatch):
        client = Client()
        monkeypatch.setattr(client._rate_limiter, "acquire", lambda: None)

        calls = {"count": 0}

        class _FakeSession:
            def get(self, url, **kwargs):
                calls["count"] += 1
                raise curl_exc.ConnectionError("dns lookup failed", 6, None)

        monkeypatch.setattr(client, "_session", lambda: _FakeSession())

        with pytest.raises(SearchConnectionError):
            client.get("https://www.google.com/travel/flights")

        assert calls["count"] == 3

    def test_bad_ca_bundle_path_raised_from_session_creation_is_attempted_once_on_get(
        self, monkeypatch
    ):
        """Fix round 1 (M1): the *session-creation* shape, not just the request shape.

        The other tests in this class fake ``_session()`` to return a stub
        whose ``.get``/``.post`` raises a curl-level error — that covers a
        certificate rejected *during the request*. A bad ``FLI_CA_BUNDLE``
        path instead makes ``_ca_bundle_from_env()`` raise
        ``SearchCertificateError`` directly *inside* ``_session()``, before
        any request is even attempted (see ``Client._session``). Nothing
        upstream of ``_wrap_request_error``'s
        ``isinstance(exc, SearchClientError): return exc`` short-circuit
        cares which of the two raised it, but a regression that moved
        ``_ca_bundle_from_env()``'s call site outside ``get``/``post``'s
        ``try`` block (or outside ``_session()`` entirely) would not be
        caught by the other tests in this class, since they never make
        ``_session()`` itself raise.
        """
        client = Client()
        monkeypatch.setattr(client._rate_limiter, "acquire", lambda: None)

        calls = {"count": 0}

        def _raise_bad_bundle():
            calls["count"] += 1
            raise SearchCertificateError(
                "FLI_CA_BUNDLE points to a CA bundle path that does not exist "
                "or is not readable: '/nonexistent/bad-bundle.pem'"
            )

        monkeypatch.setattr(client, "_session", _raise_bad_bundle)

        with pytest.raises(SearchCertificateError):
            client.get("https://www.google.com/travel/flights")

        assert calls["count"] == 1

    def test_bad_ca_bundle_path_raised_from_session_creation_is_attempted_once_on_post(
        self, monkeypatch
    ):
        client = Client()
        monkeypatch.setattr(client._rate_limiter, "acquire", lambda: None)

        calls = {"count": 0}

        def _raise_bad_bundle():
            calls["count"] += 1
            raise SearchCertificateError(
                "FLI_CA_BUNDLE points to a CA bundle path that does not exist "
                "or is not readable: '/nonexistent/bad-bundle.pem'"
            )

        monkeypatch.setattr(client, "_session", _raise_bad_bundle)

        with pytest.raises(SearchCertificateError):
            client.post("https://www.google.com/travel/flights")

        assert calls["count"] == 1

    def test_certificate_error_from_post_is_also_attempted_exactly_once(self, monkeypatch):
        client = Client()
        monkeypatch.setattr(client._rate_limiter, "acquire", lambda: None)

        calls = {"count": 0}

        class _FakeSession:
            def post(self, url, **kwargs):
                calls["count"] += 1
                raise curl_exc.CertificateVerifyError("bad cert", 60, None)

        monkeypatch.setattr(client, "_session", lambda: _FakeSession())

        with pytest.raises(SearchCertificateError):
            client.post("https://www.google.com/travel/flights")

        assert calls["count"] == 1
