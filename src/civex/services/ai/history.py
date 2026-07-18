"""Canonical chat history -> provider-native multi-turn tool format.

Anthropic and OpenAI each represent "assistant said X and called tools Y, Z"
differently (content blocks vs. a tool_calls field + separate tool-role
messages), and both require the assistant's tool calls and the matching
tool results to be paired in adjacent messages. _iter_turns() groups a run
of ToolCallMessages together with any AssistantMessage text that preceded
them in the same original model turn; each provider adapter below then
renders that group into its own native shape.
"""

from __future__ import annotations

import json


def _iter_turns(history: list):
    """Yield ("user", text) or ("assistant", text, tool_calls) tuples."""
    i, n = 0, len(history)
    while i < n:
        msg = history[i]
        if msg.role == "user":
            yield ("user", msg.content)
            i += 1
            continue

        text = ""
        if msg.role == "assistant":
            text = msg.content
            i += 1
        tool_calls = []
        while i < n and history[i].role == "tool_call":
            tool_calls.append(history[i])
            i += 1
        yield ("assistant", text, tool_calls)


def _history_to_anthropic(history: list) -> list[dict]:
    api_msgs: list[dict] = []
    for turn in _iter_turns(history):
        if turn[0] == "user":
            api_msgs.append({"role": "user", "content": turn[1]})
            continue
        _, text, tool_calls = turn
        if not tool_calls:
            if text:
                api_msgs.append({"role": "assistant", "content": text})
            continue
        content: list[dict] = []
        if text:
            content.append({"type": "text", "text": text})
        for tc in tool_calls:
            content.append(
                {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input}
            )
        api_msgs.append({"role": "assistant", "content": content})
        api_msgs.append(
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": tc.id, "content": tc.result}
                    for tc in tool_calls
                ],
            }
        )
    return api_msgs


def _history_to_openai(history: list) -> list[dict]:
    api_msgs: list[dict] = []
    for turn in _iter_turns(history):
        if turn[0] == "user":
            api_msgs.append({"role": "user", "content": turn[1]})
            continue
        _, text, tool_calls = turn
        if not tool_calls:
            if text:
                api_msgs.append({"role": "assistant", "content": text})
            continue
        api_msgs.append(
            {
                "role": "assistant",
                "content": text or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.input),
                        },
                    }
                    for tc in tool_calls
                ],
            }
        )
        for tc in tool_calls:
            api_msgs.append(
                {"role": "tool", "tool_call_id": tc.id, "content": tc.result}
            )
    return api_msgs
