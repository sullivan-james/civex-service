"""civex.tls: civex's own HTTPS requests trust what the operating system does,
and a failed certificate check is said in plain words."""

from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from typing import Any

import pytest

from civex import updates
from civex.domain.sync import SyncError
from civex.services import sync_transport
from civex.tls import certificate_problem, ssl_context


def _cert_failure() -> urllib.error.URLError:
    error = ssl.SSLCertVerificationError(1, "certificate verify failed")
    error.verify_message = "unable to get local issuer certificate"
    return urllib.error.URLError(error)


def test_the_context_checks_certificates_and_names() -> None:
    context = ssl_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname


def test_it_uses_the_operating_system_s_trust() -> None:
    import truststore

    assert isinstance(ssl_context(), truststore.SSLContext)


def test_a_certificate_failure_says_what_to_do() -> None:
    said = certificate_problem(_cert_failure())
    assert said and "unable to get local issuer certificate" in said
    assert "trusted certificates" in said
    assert certificate_problem(urllib.error.URLError("connection refused")) is None


def test_sync_requests_use_it_and_do_not_retry_a_bad_certificate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def urlopen(request: Any, timeout: float, context: ssl.SSLContext) -> Any:
        seen["context"] = context
        raise _cert_failure()

    monkeypatch.setattr(sync_transport.urllib.request, "urlopen", urlopen)
    transport = sync_transport.HttpSyncTransport.__new__(
        sync_transport.HttpSyncTransport
    )
    transport._timeout = 1
    with pytest.raises(SyncError) as raised:
        transport._open(urllib.request.Request("https://civex.example.com/x"))
    assert isinstance(seen["context"], ssl.SSLContext)
    assert not raised.value.retryable
    assert "certificate couldn't be checked" in str(raised.value)


def test_the_update_check_uses_it(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class _Answer:
        def __enter__(self) -> _Answer:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"info": {"version": "9.9.9"}, "releases": {}}'

    def urlopen(url: str, timeout: float, context: ssl.SSLContext) -> _Answer:
        seen["context"] = context
        return _Answer()

    monkeypatch.setattr(updates.urllib.request, "urlopen", urlopen)
    assert updates.latest_version() == "9.9.9"
    assert isinstance(seen["context"], ssl.SSLContext)
