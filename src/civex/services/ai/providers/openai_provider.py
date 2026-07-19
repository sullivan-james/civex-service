"""OpenAI-compatible ChatProvider adapter (Groq, Gemini, Ollama, OpenRouter, ...).

Absorbs what was _stream_chat_openai in services/ai/service.py verbatim in
behavior -- same lazy `from openai import AsyncOpenAI` (so tests can
monkeypatch openai.AsyncOpenAI before this ever runs), same OpenRouter
extra_headers, same Ollama OLLAMA_NUM_CTX workaround, same tool-call-delta
accumulation and finish_reason handling, same mid-stream provider-error
wrapping.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, AsyncIterator, Iterable

from civex.services.ai.history import _history_to_openai
from civex.services.ai.providers.base import (
    ChatProvider,
    ErrorEvent,
    ProviderEvent,
    RoundEnd,
    TextDelta,
    ToolCallRequest,
)

if TYPE_CHECKING:
    from civex.services.ai.tools.base import AiTool

# Ollama's default context window (2048-4096 tokens depending on version/model) is
# easily blown past by system prompt (~2-3k tokens with real schemas) + a single
# large tool result (get_workflow_authoring_guide alone is ~1.4k tokens) + the
# actual conversation. Ollama silently truncates from the front rather than
# erroring, which can drop the task or instructions right as the model needs them
# most -- producing a blank/degenerate reply instead of a visible failure. Request
# a larger window explicitly rather than relying on the per-install default.
OLLAMA_NUM_CTX = 8192


def _is_ollama(ai_cfg) -> bool:
    return (
        ai_cfg is not None
        and ai_cfg.provider == "openai-compat"
        and ":11434" in (ai_cfg.base_url or "")
    )


class OpenAIProvider(ChatProvider):
    def parse_history(self, history: list) -> list[Any]:
        return _history_to_openai(history)

    def render_system(self, prompt: str) -> Any:
        return prompt

    def render_tools(self, tools: Iterable[type[AiTool]]) -> Any:
        return [
            {
                "type": "function",
                "function": {
                    "name": cls.name,
                    "description": cls.description,
                    "parameters": cls.input_schema,
                },
            }
            for cls in tools
        ]

    async def stream_round(
        self, *, system: Any, tools: Any, messages: list[Any]
    ) -> AsyncIterator[ProviderEvent]:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            yield ErrorEvent(
                "openai package not installed. Run: pip install 'civex[ai]'"
            )
            return

        assert self.ai_cfg is not None
        ai_cfg = self.ai_cfg
        is_openrouter = "openrouter.ai" in (ai_cfg.base_url or "")
        extra_headers = (
            {"HTTP-Referer": "http://localhost:8000", "X-Title": "civex"}
            if is_openrouter
            else {}
        )
        client = AsyncOpenAI(
            api_key=ai_cfg.api_key,
            base_url=ai_cfg.base_url,
            default_headers=extra_headers,
        )
        api_msgs: list[dict] = [{"role": "system", "content": system}] + messages
        # See OLLAMA_NUM_CTX above -- request a larger context window than Ollama's
        # default so a big tool result (e.g. the workflow authoring guide) doesn't
        # silently push the task/instructions out of the model's view mid-turn.
        extra_body = (
            {"options": {"num_ctx": OLLAMA_NUM_CTX}} if _is_ollama(ai_cfg) else None
        )

        stream = await client.chat.completions.create(
            model=ai_cfg.model,
            messages=api_msgs,  # type: ignore[arg-type]
            tools=tools,
            stream=True,
            extra_body=extra_body,
        )

        finish_reason: str | None = None
        assistant_text = ""
        tool_calls_acc: dict[int, dict] = {}

        try:
            async for chunk in stream:  # type: ignore[union-attr]
                choice = chunk.choices[0] if chunk.choices else None
                if not choice:
                    continue
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
                delta = choice.delta
                if delta.content:
                    assistant_text += delta.content
                    yield TextDelta(delta.content)
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": "",
                                "name": "",
                                "arguments": "",
                            }
                        if tc.id:
                            tool_calls_acc[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_acc[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_calls_acc[idx]["arguments"] += (
                                    tc.function.arguments
                                )
        except Exception as api_err:
            yield ErrorEvent(f"Provider error: {api_err}. Try rephrasing your request.")
            return

        if finish_reason != "tool_calls" or not tool_calls_acc:
            yield RoundEnd(tool_calls=[], is_final=True, raw=None)
            return

        tool_calls = []
        for tc in tool_calls_acc.values():
            try:
                tool_input = json.loads(tc["arguments"])
                if not isinstance(tool_input, dict):
                    tool_input = {}
            except json.JSONDecodeError:
                tool_input = {}
            tool_calls.append(
                ToolCallRequest(id=tc["id"], name=tc["name"], input=tool_input)
            )

        assistant_msg = {
            "role": "assistant",
            "content": assistant_text or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in tool_calls_acc.values()
            ],
        }
        yield RoundEnd(tool_calls=tool_calls, is_final=False, raw=assistant_msg)

    def append_tool_results(
        self,
        messages: list[Any],
        round_end: RoundEnd,
        results: list[tuple[ToolCallRequest, str]],
    ) -> None:
        messages.append(round_end.raw)
        for tc, result_str in results:
            messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": result_str}
            )
