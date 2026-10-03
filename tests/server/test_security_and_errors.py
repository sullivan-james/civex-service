"""Regression tests for the local security guard, the HTTP error boundary, and
log scrubbing.

These pin down behaviour added for production-readiness so it can't silently
regress: DNS-rebinding/CSRF protection, SSRF blocking on the Ollama endpoint,
generic (non-leaking) 500s with a correlation id, preserved domain-error
messages, validation errors with submitted input stripped, and secret redaction
in logs.
"""

from __future__ import annotations

import io
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# `project_dir` and `client` fixtures come from tests/conftest.py.

# ---------------------------------------------------------------------------
# LocalGuardMiddleware — DNS rebinding (Host header allowlist)
# ---------------------------------------------------------------------------


def test_loopback_host_allowed(client: TestClient) -> None:
    # TestClient's default Host is "testserver", which is on the allowlist.
    assert client.get("/health").status_code == 200


def test_non_local_host_blocked(client: TestClient) -> None:
    resp = client.get("/health", headers={"Host": "evil.example.com"})
    assert resp.status_code == 403
    assert "local" in resp.json()["detail"].lower()


def test_allow_remote_env_bypasses_host_guard(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # When the operator has opted into remote exposure, the guard stands down.
    monkeypatch.setenv("CIVEX_ALLOW_REMOTE", "1")
    resp = client.get("/health", headers={"Host": "evil.example.com"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# LocalGuardMiddleware — CSRF (Origin check on mutating requests)
# ---------------------------------------------------------------------------


def test_cross_origin_mutation_blocked(client: TestClient) -> None:
    resp = client.post(
        "/api/collections",
        json={"name": "study"},
        headers={"Origin": "http://evil.example.com"},
    )
    assert resp.status_code == 403


def test_same_origin_mutation_allowed(client: TestClient) -> None:
    # A loopback Origin (e.g. the Vite dev server) passes the guard.
    resp = client.post(
        "/api/collections",
        json={"name": "study"},
        headers={"Origin": "http://localhost:5173"},
    )
    assert resp.status_code == 201


def test_get_needs_no_origin(client: TestClient) -> None:
    # Non-mutating requests are never subject to the Origin check.
    assert client.get("/api/schemas").status_code == 200


# ---------------------------------------------------------------------------
# SSRF guard on the Ollama models endpoint
# ---------------------------------------------------------------------------


def test_ollama_models_rejects_non_local_base_url(client: TestClient) -> None:
    resp = client.get(
        "/api/ai/ollama/models", params={"base_url": "http://169.254.169.254/v1"}
    )
    assert resp.status_code == 400
    assert "local" in resp.json()["detail"].lower()


def test_ollama_models_allows_local_base_url(client: TestClient) -> None:
    # A localhost base_url passes the SSRF guard. With no Ollama running the
    # endpoint reports 503 (connection refused) — the point is it's NOT the 400
    # SSRF rejection. If Ollama happens to be running locally, 200 is fine too.
    resp = client.get(
        "/api/ai/ollama/models", params={"base_url": "http://localhost:11434/v1"}
    )
    assert resp.status_code != 400


# ---------------------------------------------------------------------------
# HTTP error boundary — unhandled exceptions, domain errors, validation
# ---------------------------------------------------------------------------


@pytest.fixture()
def boundary_client() -> TestClient:
    """A minimal app wired with the same middleware + handlers, plus routes that
    deliberately fail — so we exercise the error boundary without the SPA
    catch-all route shadowing test endpoints."""
    from pydantic import BaseModel

    from civex.domain.exceptions import NotFoundError
    from civex.server.errors import RequestContextMiddleware, register_error_handlers

    # Keep the expected traceback out of the captured test output.
    logging.getLogger("civex.server").setLevel(logging.CRITICAL)

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)

    class Item(BaseModel):
        count: int  # non-secret field so we can force a type error

    @app.get("/boom")
    def boom():
        raise RuntimeError("internal path /etc/secret leaked here")

    @app.get("/missing")
    def missing():
        raise NotFoundError("Schema 'foo' not found")

    @app.post("/validate")
    def validate(item: Item):
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


def test_unhandled_exception_returns_generic_500(boundary_client: TestClient) -> None:
    resp = boundary_client.get("/boom")
    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"] == "Internal server error"
    # The internal exception text must never reach the client.
    assert "secret" not in resp.text


def test_unhandled_exception_carries_request_id(boundary_client: TestClient) -> None:
    resp = boundary_client.get("/boom")
    header_id = resp.headers.get("x-request-id")
    assert header_id
    assert resp.json()["request_id"] == header_id


def test_request_id_echoed_from_incoming_header(boundary_client: TestClient) -> None:
    resp = boundary_client.get("/missing", headers={"X-Request-ID": "abc123"})
    assert resp.headers.get("x-request-id") == "abc123"


def test_domain_error_message_preserved(boundary_client: TestClient) -> None:
    resp = boundary_client.get("/missing")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Schema 'foo' not found"


def test_validation_error_strips_submitted_input(boundary_client: TestClient) -> None:
    # A secret submitted in a bad request must not be echoed back in the error.
    resp = boundary_client.post("/validate", json={"count": "sk-super-secret"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"] == "Request validation failed"
    assert "sk-super-secret" not in resp.text
    for err in body["errors"]:
        assert "input" not in err


# ---------------------------------------------------------------------------
# Log scrubbing
# ---------------------------------------------------------------------------


def test_sensitive_keys_are_redacted_in_logs() -> None:
    import structlog

    from civex.observability import configure_logging, get_logger

    configure_logging(level="INFO", json_console=True)

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        )
    )
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        get_logger("civex.test").info(
            "login", api_key="sk-ant-SECRET", token="tok-SECRET", user="jim"
        )
    finally:
        root.removeHandler(handler)

    out = buf.getvalue()
    record = json.loads(out.strip().splitlines()[-1])
    assert record["api_key"] == "***"
    assert record["token"] == "***"
    assert record["user"] == "jim"  # non-sensitive fields survive
    assert "SECRET" not in out
