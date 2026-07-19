"""Cross-provider contract tests (CIVEX-61): AnthropicProvider and
OpenAIProvider both implement ChatProvider and must satisfy the same
behavioral contract regardless of API shape -- covering every registered
tool in render_tools(), embedding the system prompt text in render_system(),
and yielding the same RoundEnd shape from stream_round() for equivalent
"plain text" / "one tool call" model responses.

Net-new pytest.fixture(params=...) pattern for this repo. The streaming
tests reuse the hand-rolled Fake SDK class + monkeypatch.setattr idiom
already established in tests/test_ai_act_tools.py (works because both
providers do a lazy in-function `import anthropic` / `from openai import
AsyncOpenAI`, so patching the SDK module attribute before stream_round()
runs is enough).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from civex.config import AIConfig
from civex.services.ai.providers import AnthropicProvider, OpenAIProvider
from civex.services.ai.providers.base import RoundEnd, TextDelta, TokenUsage
from civex.services.ai.tools.registry import all_tools


@pytest.fixture(params=[AnthropicProvider, OpenAIProvider])
def provider_cls(request: pytest.FixtureRequest):
    return request.param


def _ai_cfg(provider_cls) -> AIConfig:
    if provider_cls is OpenAIProvider:
        return AIConfig(
            api_key="x",
            model="m",
            provider="openai-compat",
            base_url="http://localhost:1/v1",
        )
    return AIConfig(api_key="x", model="m", provider="anthropic")


def _patch_openai_sdk(monkeypatch: pytest.MonkeyPatch, *, tool_call: bool) -> None:
    pytest.importorskip("openai")
    import openai

    def _chunk(*, content=None, tool_calls=None, finish=None):
        delta = type("D", (), {"content": content, "tool_calls": tool_calls})()
        choice = type("C", (), {"delta": delta, "finish_reason": finish})()
        return type("Chunk", (), {"choices": [choice], "usage": None})()

    # Final usage-only chunk, per the OpenAI streaming `include_usage` shape:
    # empty `choices`, a top-level `usage`.
    usage_chunk = type(
        "Chunk",
        (),
        {
            "choices": [],
            "usage": type(
                "Usage", (), {"prompt_tokens": 12, "completion_tokens": 34}
            )(),
        },
    )()

    if tool_call:
        tc = type(
            "TC",
            (),
            {
                "index": 0,
                "id": "call_1",
                "function": type(
                    "F",
                    (),
                    {"name": "list_collections", "arguments": json.dumps({"x": 1})},
                )(),
            },
        )()
        chunks = [_chunk(tool_calls=[tc], finish="tool_calls"), usage_chunk]
    else:
        chunks = [_chunk(content="hi", finish="stop"), usage_chunk]

    class FakeStream:
        def __aiter__(self):
            async def gen():
                for c in chunks:
                    yield c

            return gen()

    class FakeCompletions:
        async def create(self, **_kw):
            return FakeStream()

    class FakeClient:
        def __init__(self, *a, **k):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)


def _patch_anthropic_sdk(monkeypatch: pytest.MonkeyPatch, *, tool_call: bool) -> None:
    pytest.importorskip("anthropic")
    import anthropic

    def _text_block(text):
        return type(
            "TextBlock",
            (),
            {
                "type": "text",
                "text": text,
                "model_dump": lambda self: {"type": "text", "text": text},
            },
        )()

    def _tool_block(id_, name, input_):
        return type(
            "ToolBlock",
            (),
            {
                "type": "tool_use",
                "id": id_,
                "name": name,
                "input": input_,
                "model_dump": lambda self: {
                    "type": "tool_use",
                    "id": id_,
                    "name": name,
                    "input": input_,
                },
            },
        )()

    fake_usage = type("Usage", (), {"input_tokens": 12, "output_tokens": 34})()

    if tool_call:
        deltas: list[str] = []
        final = type(
            "Final",
            (),
            {
                "stop_reason": "tool_use",
                "content": [_tool_block("call_1", "list_collections", {"x": 1})],
                "usage": fake_usage,
            },
        )()
    else:
        deltas = ["hi"]
        final = type(
            "Final",
            (),
            {
                "stop_reason": "end_turn",
                "content": [_text_block("hi")],
                "usage": fake_usage,
            },
        )()

    class FakeMessageStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        @property
        def text_stream(self):
            async def gen():
                for d in deltas:
                    yield d

            return gen()

        async def get_final_message(self):
            return final

    class FakeMessages:
        def stream(self, **_kw):
            return FakeMessageStream()

    class FakeClient:
        def __init__(self, *a, **k):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeClient)


def _make_provider(provider_cls, monkeypatch: pytest.MonkeyPatch, *, tool_call: bool):
    if provider_cls is OpenAIProvider:
        _patch_openai_sdk(monkeypatch, tool_call=tool_call)
    else:
        _patch_anthropic_sdk(monkeypatch, tool_call=tool_call)
    return provider_cls(_ai_cfg(provider_cls))


async def _collect(provider) -> list:
    return [
        event
        async for event in provider.stream_round(system="sys", tools=[], messages=[])
    ]


# ---------------------------------------------------------------------------
# Static rendering contract -- no SDK involved
# ---------------------------------------------------------------------------


def test_render_tools_covers_every_registered_tool(provider_cls) -> None:
    provider = provider_cls()
    rendered = provider.render_tools(all_tools().values())
    assert len(rendered) == len(all_tools())


def test_render_system_embeds_the_prompt_text(provider_cls) -> None:
    provider = provider_cls()
    rendered = provider.render_system("UNIQUE_MARKER_TEXT")
    assert "UNIQUE_MARKER_TEXT" in json.dumps(rendered)


def test_parse_history_of_empty_history_is_an_empty_list(provider_cls) -> None:
    provider = provider_cls()
    assert provider.parse_history([]) == []


# ---------------------------------------------------------------------------
# stream_round() contract -- via the hand-rolled Fake SDK
# ---------------------------------------------------------------------------


def test_stream_round_text_only_ends_final_with_no_tool_calls(
    provider_cls, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _make_provider(provider_cls, monkeypatch, tool_call=False)
    events = asyncio.run(_collect(provider))

    assert any(isinstance(e, TextDelta) and e.text == "hi" for e in events)
    round_end = events[-1]
    assert isinstance(round_end, RoundEnd)
    assert round_end.is_final is True
    assert round_end.tool_calls == []
    assert round_end.usage == TokenUsage(input_tokens=12, output_tokens=34)


def test_stream_round_with_a_tool_call_ends_non_final_with_parsed_input(
    provider_cls, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _make_provider(provider_cls, monkeypatch, tool_call=True)
    events = asyncio.run(_collect(provider))

    round_end = events[-1]
    assert isinstance(round_end, RoundEnd)
    assert round_end.is_final is False
    assert len(round_end.tool_calls) == 1
    tc = round_end.tool_calls[0]
    assert tc.name == "list_collections"
    assert tc.input == {"x": 1}
    assert round_end.usage == TokenUsage(input_tokens=12, output_tokens=34)


def test_append_tool_results_grows_the_message_list(
    provider_cls, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _make_provider(provider_cls, monkeypatch, tool_call=True)
    round_end = asyncio.run(_collect(provider))[-1]

    messages: list = []
    provider.append_tool_results(messages, round_end, [(round_end.tool_calls[0], "{}")])
    # Assistant turn + tool result, in whatever native shape this provider uses.
    assert len(messages) == 2


# ---------------------------------------------------------------------------
# OpenAIProvider.prompt_fragment -- the OpenRouter free-tier budget note must
# only fire for an actual ":free" model slug, not for every OpenRouter
# request regardless of whether the user is on a paid model.
# ---------------------------------------------------------------------------


def test_openrouter_free_tier_note_only_fires_for_free_model_slug() -> None:
    free_cfg = AIConfig(
        api_key="x",
        model="meta-llama/llama-3.1-8b-instruct:free",
        provider="openai-compat",
        base_url="https://openrouter.ai/api/v1",
    )
    assert "REQUEST BUDGET" in OpenAIProvider(free_cfg).prompt_fragment()

    paid_cfg = AIConfig(
        api_key="x",
        model="anthropic/claude-sonnet-5",
        provider="openai-compat",
        base_url="https://openrouter.ai/api/v1",
    )
    assert "REQUEST BUDGET" not in OpenAIProvider(paid_cfg).prompt_fragment()

    non_openrouter_cfg = AIConfig(
        api_key="x",
        model="llama-3.3-70b-versatile",
        provider="openai-compat",
        base_url="https://api.groq.com/openai/v1",
    )
    assert "REQUEST BUDGET" not in OpenAIProvider(non_openrouter_cfg).prompt_fragment()


# ---------------------------------------------------------------------------
# OpenAIProvider-specific: stream_options include_usage must degrade
# gracefully, never break the turn, on a backend that rejects it.
# ---------------------------------------------------------------------------


def test_openai_falls_back_when_backend_rejects_stream_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("openai")
    import openai

    def _chunk(*, content=None, finish=None):
        delta = type("D", (), {"content": content, "tool_calls": None})()
        choice = type("C", (), {"delta": delta, "finish_reason": finish})()
        return type("Chunk", (), {"choices": [choice], "usage": None})()

    class FakeStream:
        def __aiter__(self):
            async def gen():
                yield _chunk(content="hi", finish="stop")

            return gen()

    calls: list[dict] = []

    class FakeCompletions:
        async def create(self, **kw):
            calls.append(kw)
            if "stream_options" in kw:
                raise TypeError("stream_options is not supported by this backend")
            return FakeStream()

    class FakeClient:
        def __init__(self, *a, **k):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)

    provider = OpenAIProvider(_ai_cfg(OpenAIProvider))
    events = asyncio.run(_collect(provider))

    round_end = events[-1]
    assert isinstance(round_end, RoundEnd)
    assert round_end.is_final is True
    assert round_end.usage is None  # backend never reported usage
    assert len(calls) == 2  # first attempt (rejected) + fallback retry
    assert "stream_options" not in calls[1]
