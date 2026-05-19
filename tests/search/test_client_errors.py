"""Tests for HTTP client error classification and configuration."""

import pytest
from curl_cffi.requests import exceptions as curl_exc

from fli.search.client import Client, _wrap_request_error
from fli.search.exceptions import SearchCertificateError


def test_certificate_verify_error_maps_to_certificate_error():
    """TLS verification failures should not be reported as generic connectivity errors."""
    exc = curl_exc.CertificateVerifyError("unable to get local issuer certificate", 60, None)

    wrapped = _wrap_request_error("GET", "https://www.google.com/travel/flights", exc)

    assert isinstance(wrapped, SearchCertificateError)
    assert "TLS certificate verification failed" in str(wrapped)
    assert "FLI_CA_BUNDLE" in str(wrapped)


def test_client_session_uses_configured_ca_bundle(monkeypatch, tmp_path):
    """The client should honor a user-provided CA bundle without disabling TLS checks."""
    ca_bundle = tmp_path / "custom-ca.pem"
    ca_bundle.write_text("certificate data", encoding="utf-8")

    monkeypatch.setenv("FLI_CA_BUNDLE", str(ca_bundle))
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

    client = Client()

    assert client._session().verify == str(ca_bundle)


def test_client_session_rejects_missing_ca_bundle(monkeypatch, tmp_path):
    """Bad CA bundle paths should produce the same structured certificate error type."""
    missing = tmp_path / "missing-ca.pem"
    monkeypatch.setenv("FLI_CA_BUNDLE", str(missing))
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

    client = Client()

    with pytest.raises(SearchCertificateError, match="does not exist or is not readable"):
        client._session()
