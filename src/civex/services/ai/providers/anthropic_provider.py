"""Anthropic (Claude) ChatProvider adapter.

Absorbs what was _stream_chat_anthropic in services/ai/service.py verbatim
in behavior -- same lazy `import anthropic` (so tests can monkeypatch
anthropic.AsyncAnthropic before this ever runs), same cache_control
placement on the system block and on the last tool, same stop_reason ==
"end_turn" termination check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator, Iterable

from civex.services.ai.history import _history_to_anthropic
from civex.services.ai.providers.base import (
    ChatProvider,
    ErrorEvent,
    ModelInfo,
    ProviderEvent,
    RoundEnd,
    TextDelta,
    TokenUsage,
    ToolCallRequest,
)

if TYPE_CHECKING:
    from civex.services.ai.tools.base import AiTool

# Static catalog, not live /v1/models discovery (CIVEX-53) -- same three
# models/labels the frontend's own copy (frontend/src/api/ai.ts) already
# hardcodes, kept here as the one backend-side source of truth.
_KNOWN_MODELS = [
    ModelInfo(id="claude-haiku-4-5-20251001", label="Haiku (fast, cheap)"),
    ModelInfo(id="claude-sonnet-4-6", label="Sonnet (balanced)"),
    ModelInfo(id="claude-opus-4-8", label="Opus (most capable)"),
]


class AnthropicProvider(ChatProvider):
    def known_models(self) -> list[ModelInfo]:
        return _KNOWN_MODELS

    def parse_history(self, history: list) -> list[Any]:
        return _history_to_anthropic(history)

    def render_system(self, prompt: str) -> Any:
        # cache_control on the system block caches the whole (static-per-
        # project) prompt server-side for ~5 min, so every extra tool round
        # in this turn -- and every follow-up message in the conversation
        # within that window -- reuses it instead of re-processing ~1.7k
        # tokens of instructions from scratch.
        return [
            {
                "type": "text",
                "text": prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def render_tools(self, tools: Iterable[type[AiTool]]) -> Any:
        rendered = [
            {
                "name": cls.name,
                "description": cls.description,
                "input_schema": cls.input_schema,
            }
            for cls in tools
        ]
        if rendered:
            # Anthropic caches everything in `tools` up to and including
            # whichever entry carries cache_control -- the list is fully
            # static per turn, so marking the last one caches the entire
            # tool-definitions block.
            rendered[-1] = {**rendered[-1], "cache_control": {"type": "ephemeral"}}
        return rendered

    async def stream_round(
        self, *, system: Any, tools: Any, messages: list[Any]
    ) -> AsyncIterator[ProviderEvent]:
        try:
            import anthropic
        except ImportError:
            yield ErrorEvent(
                "anthropic package not installed. Run: pip install 'civex[ai]'"
            )
            return

        assert self.ai_cfg is not None
        client = anthropic.AsyncAnthropic(api_key=self.ai_cfg.api_key)

        async with client.messages.stream(
            model=self.ai_cfg.model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=4096,
        ) as stream:
            async for delta in stream.text_stream:
                yield TextDelta(delta)
            final = await stream.get_final_message()

        tool_calls = [
            ToolCallRequest(id=block.id, name=block.name, input=block.input)
            for block in final.content
            if block.type == "tool_use"
        ]
        yield RoundEnd(
            tool_calls=tool_calls,
            is_final=final.stop_reason == "end_turn",
            raw=final,
            usage=TokenUsage(
                input_tokens=final.usage.input_tokens,
                output_tokens=final.usage.output_tokens,
            ),
        )

    def append_tool_results(
        self,
        messages: list[Any],
        round_end: RoundEnd,
        results: list[tuple[ToolCallRequest, str]],
    ) -> None:
        messages.append(
            {
                "role": "assistant",
                "content": [block.model_dump() for block in round_end.raw.content],
            }
        )
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": result_str,
                    }
                    for tc, result_str in results
                ],
            }
        )
