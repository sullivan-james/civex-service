from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from civex.config import AIConfig, load_config, save_config
from civex.context import build_local_context
from civex.domain.exceptions import ConfigError
from civex.services.ai.config import ANTHROPIC_MODELS, DEFAULT_MODEL
from civex.services.ai.service import _sse

router = APIRouter(prefix="/ai", tags=["ai"])


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class UserMessage(BaseModel):
    role: Literal["user"] = "user"
    content: str


class AssistantMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class ToolCallMessage(BaseModel):
    """A tool call + its result, as originally exchanged with the model.

    The frontend keeps this alongside plain text turns in conversation history
    and resends it verbatim on every later request, so a tool call made (and
    its result received) in an earlier turn is not lost across separate HTTP
    requests -- see civex.services.ai.history's _iter_turns()/
    _history_to_anthropic()/_history_to_openai().
    """

    role: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    input: dict[str, Any]
    result: str


ChatMessage = Annotated[
    Union[UserMessage, AssistantMessage, ToolCallMessage],
    Field(discriminator="role"),
]


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------


class AiConfigResponse(BaseModel):
    configured: bool
    source: str  # "config" | "env" | "none"
    model: str
    provider: str  # "anthropic" | "openai-compat"
    base_url: str | None
    key_hint: str | None  # last 6 chars of key, or None


class AiConfigUpdate(BaseModel):
    api_key: str | None = None
    model: str | None = None
    provider: str | None = None
    base_url: str | None = None


@router.get("/config", response_model=AiConfigResponse)
def get_ai_config():
    try:
        config = load_config()
    except ConfigError as e:
        raise HTTPException(503, detail=str(e))
    if not config.ai:
        return AiConfigResponse(
            configured=False,
            source="none",
            model=DEFAULT_MODEL,
            provider="anthropic",
            base_url=None,
            key_hint=None,
        )
    key = config.ai.api_key
    hint = f"...{key[-6:]}" if len(key) >= 6 else "***"
    return AiConfigResponse(
        configured=True,
        source="env" if config.ai.from_env else "config",
        model=config.ai.model,
        provider=config.ai.provider,
        base_url=config.ai.base_url,
        key_hint=hint,
    )


@router.patch("/config", response_model=AiConfigResponse)
def update_ai_config(body: AiConfigUpdate):
    try:
        config = load_config()
    except ConfigError as e:
        raise HTTPException(503, detail=str(e))

    current = config.ai
    new_provider = (
        body.provider
        if body.provider is not None
        else (current.provider if current else "anthropic")
    )
    new_base_url = (
        body.base_url
        if body.base_url is not None
        else (current.base_url if current else None)
    )

    if new_provider not in ("anthropic", "openai-compat"):
        raise HTTPException(
            422, detail="provider must be 'anthropic' or 'openai-compat'"
        )
    if new_provider == "openai-compat" and not new_base_url:
        raise HTTPException(
            422, detail="base_url is required for openai-compat provider"
        )

    new_model = (
        body.model
        if body.model is not None
        else (current.model if current else DEFAULT_MODEL)
    )
    if new_provider == "anthropic" and new_model not in ANTHROPIC_MODELS:
        raise HTTPException(
            422,
            detail=f"Unsupported Anthropic model. Choose one of: {', '.join(ANTHROPIC_MODELS)}",
        )

    current_key = current.api_key if current else ""
    new_key = body.api_key if body.api_key is not None else current_key
    if not new_key:
        raise HTTPException(422, detail="api_key is required")

    config.ai = AIConfig(
        api_key=new_key,
        model=new_model,
        provider=new_provider,
        base_url=new_base_url or None,
        from_env=False,
    )
    try:
        save_config(config)
    except Exception as e:
        raise HTTPException(500, detail=str(e))

    hint = f"...{new_key[-6:]}" if len(new_key) >= 6 else "***"
    return AiConfigResponse(
        configured=True,
        source="config",
        model=new_model,
        provider=new_provider,
        base_url=new_base_url or None,
        key_hint=hint,
    )


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------


@router.post("/chat")
async def chat(body: ChatRequest):
    try:
        config = load_config()
    except ConfigError as err:
        message = "AI assistant unavailable: no civex project found. Run `civex init` to create one."
        if "No civex project found" not in str(err):
            message = "AI assistant unavailable due to configuration error."

        async def no_project():
            yield _sse({"type": "error", "message": message})

        return StreamingResponse(
            no_project(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if not config.ai:

        async def no_key():
            yield _sse(
                {
                    "type": "error",
                    "message": (
                        "AI assistant not configured. Click the ⚙ gear icon to set up a provider.\n\n"
                        "Free option: use Groq (no credit card, generous free tier).\n"
                        "Get a free key at console.groq.com → API Keys.\n\n"
                        "Or set ANTHROPIC_API_KEY environment variable for Claude."
                    ),
                }
            )

        return StreamingResponse(
            no_key(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    ctx = build_local_context(config)

    async def gen():
        try:
            async for chunk in ctx.ai_svc.stream_chat(body.messages, config.ai):
                yield chunk
        except Exception as e:
            yield _sse({"type": "error", "message": f"Unexpected error: {e}"})
        finally:
            ctx.close()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# OpenRouter OAuth + limits endpoints
# ---------------------------------------------------------------------------

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@router.get("/openrouter/auth-url")
async def openrouter_auth_url(request: Request):
    """Return the OAuth URL for the OpenRouter login flow."""
    base = str(request.base_url).rstrip("/")
    callback = f"{base}/api/ai/openrouter/callback"
    return {"url": f"https://openrouter.ai/auth?callback_url={callback}"}


@router.get("/openrouter/callback")
async def openrouter_callback(code: str):
    """Receive OAuth code from OpenRouter, exchange for key, save to config."""
    import httpx2 as httpx

    try:
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                "https://openrouter.ai/api/v1/auth/keys",
                json={"code": code},
            )
        if not resp.is_success:
            raise ValueError(
                f"OpenRouter returned {resp.status_code}: {resp.text[:200]}"
            )
        key = resp.json().get("key")
        if not key:
            raise ValueError("No key in OpenRouter response")
    except Exception as e:
        return HTMLResponse(
            f"<html><body style='font-family:sans-serif;padding:2rem'>"
            f"<h2 style='color:#d1242f'>Login failed</h2><p>{e}</p></body></html>",
            status_code=400,
        )

    try:
        config = load_config()
        default_model = (
            config.ai.model
            if config.ai and "openrouter" not in (config.ai.base_url or "")
            else "meta-llama/llama-3.1-8b-instruct:free"
        )
        config.ai = AIConfig(
            api_key=key,
            model=default_model,
            provider="openai-compat",
            base_url=OPENROUTER_BASE_URL,
            from_env=False,
        )
        save_config(config)
    except Exception as e:
        return HTMLResponse(
            f"<html><body style='font-family:sans-serif;padding:2rem'>"
            f"<h2 style='color:#d1242f'>Could not save config</h2><p>{e}</p></body></html>",
            status_code=500,
        )

    return HTMLResponse("""<html><head><title>civex — OpenRouter connected</title></head>
<body style="font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#f6f8fa">
<div style="text-align:center;padding:2rem">
  <div style="font-size:2.5rem">✓</div>
  <h2 style="margin:.5rem 0;color:#1a7f37">Connected to OpenRouter</h2>
  <p style="color:#656d76;margin:0">You can close this tab and return to civex.</p>
</div>
<script>setTimeout(()=>window.close(),1500)</script>
</body></html>""")


@router.get("/ollama/models")
async def ollama_models(base_url: str = "http://localhost:11434/v1"):
    """List models installed in a running Ollama instance."""
    import httpx2 as httpx
    from urllib.parse import urlparse

    # SSRF guard: this endpoint fetches base_url server-side, so restrict it to a
    # local Ollama instance — never let a caller point the server at arbitrary URLs.
    if (urlparse(base_url).hostname or "").lower() not in (
        "localhost",
        "127.0.0.1",
        "::1",
    ):
        raise HTTPException(
            400, detail="base_url must point to a local Ollama instance (localhost)."
        )

    tags_url = base_url.rstrip("/").removesuffix("/v1") + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5) as http:
            resp = await http.get(tags_url)
        if not resp.is_success:
            raise HTTPException(
                resp.status_code, detail=f"Ollama error: {resp.text[:200]}"
            )
        raw = resp.json().get("models", [])
        return {"models": [{"name": m["name"], "size": m.get("size", 0)} for m in raw]}
    except httpx.ConnectError:
        raise HTTPException(
            503, detail=f"Ollama is not running at {base_url.removesuffix('/v1')}"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/openrouter/limits")
async def openrouter_limits():
    """Proxy GET https://openrouter.ai/api/v1/key to expose usage/rate-limit info."""
    try:
        config = load_config()
    except ConfigError as e:
        raise HTTPException(400, detail=str(e))
    if not config.ai or "openrouter.ai" not in (config.ai.base_url or ""):
        raise HTTPException(400, detail="Not configured for OpenRouter")

    import httpx2 as httpx

    async with httpx.AsyncClient(timeout=10) as http:
        resp = await http.get(
            "https://openrouter.ai/api/v1/key",
            headers={"Authorization": f"Bearer {config.ai.api_key}"},
        )
    if not resp.is_success:
        raise HTTPException(resp.status_code, detail=f"OpenRouter: {resp.text[:200]}")
    return resp.json()
