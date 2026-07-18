"""Characterization tests for GET/PATCH /api/ai/config and the /api/ai/chat
"no project"/"no key" SSE error paths.

Written ahead of the CIVEX-41 rearchitecture (moving this logic into an
AiService/AiConfigService) to pin the current HTTP contract and exact error
strings, so the extraction can be verified as behavior-preserving. See
/home/sulli/.claude/plans/vectorized-drifting-biscuit.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import civex.server.routers.ai as ai

# ---------------------------------------------------------------------------
# GET /api/ai/config
# ---------------------------------------------------------------------------


def test_get_ai_config_not_configured(client: TestClient) -> None:
    resp = client.get("/api/ai/config")
    assert resp.status_code == 200
    assert resp.json() == {
        "configured": False,
        "source": "none",
        "model": "claude-sonnet-4-6",
        "provider": "anthropic",
        "base_url": None,
        "key_hint": None,
    }


def test_get_ai_config_from_env_fallback(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-abcdef123456")
    resp = client.get("/api/ai/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["source"] == "env"
    assert body["provider"] == "anthropic"
    assert body["key_hint"] == "...123456"


# ---------------------------------------------------------------------------
# PATCH /api/ai/config — validation error strings
# ---------------------------------------------------------------------------


def test_patch_ai_config_missing_api_key(client: TestClient) -> None:
    resp = client.patch("/api/ai/config", json={})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "api_key is required"


def test_patch_ai_config_invalid_provider(client: TestClient) -> None:
    resp = client.patch(
        "/api/ai/config", json={"api_key": "x", "provider": "bogus"}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "provider must be 'anthropic' or 'openai-compat'"


def test_patch_ai_config_openai_compat_requires_base_url(client: TestClient) -> None:
    resp = client.patch(
        "/api/ai/config", json={"api_key": "x", "provider": "openai-compat"}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "base_url is required for openai-compat provider"


def test_patch_ai_config_unsupported_anthropic_model(client: TestClient) -> None:
    resp = client.patch(
        "/api/ai/config", json={"api_key": "x", "model": "not-a-real-model"}
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail.startswith("Unsupported Anthropic model. Choose one of:")
    for model in ai.ANTHROPIC_MODELS:
        assert model in detail


def test_patch_then_get_ai_config_round_trips(client: TestClient) -> None:
    patch_resp = client.patch(
        "/api/ai/config",
        json={"api_key": "sk-ant-abcdef123456", "model": ai.ANTHROPIC_MODELS[0]},
    )
    assert patch_resp.status_code == 200
    patch_body = patch_resp.json()
    assert patch_body == {
        "configured": True,
        "source": "config",
        "model": ai.ANTHROPIC_MODELS[0],
        "provider": "anthropic",
        "base_url": None,
        "key_hint": "...123456",
    }

    get_resp = client.get("/api/ai/config")
    assert get_resp.status_code == 200
    assert get_resp.json() == patch_body


# ---------------------------------------------------------------------------
# POST /api/ai/chat — the two "can't even start" SSE error paths, which
# don't require a real provider call.
# ---------------------------------------------------------------------------

_CHAT_BODY = {"messages": [{"role": "user", "content": "hi"}]}


def test_chat_sse_no_civex_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # no _civex/ dir here
    from civex.server.app import create_app

    raw_client = TestClient(create_app(), raise_server_exceptions=False)
    with raw_client.stream("POST", "/api/ai/chat", json=_CHAT_BODY) as resp:
        body = b"".join(resp.iter_bytes()).decode()
    assert "AI assistant unavailable: no civex project found" in body


def test_chat_sse_no_key_configured(client: TestClient) -> None:
    with client.stream("POST", "/api/ai/chat", json=_CHAT_BODY) as resp:
        body = b"".join(resp.iter_bytes()).decode()
    assert "AI assistant not configured. Click the" in body
    assert "Free option: use Groq" in body
