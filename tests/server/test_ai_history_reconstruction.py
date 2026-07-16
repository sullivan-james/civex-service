"""Canonical chat history -> provider-native tool format.

Regression: each /api/ai/chat request used to be built from only role+content
strings, so a tool call (and its result) made in one browser-side turn was
invisible to the model on the next turn -- e.g. after calling
get_workflow_authoring_guide and pausing, "keep going" arrived with no memory
that the guide was ever fetched. ToolCallMessage plus _history_to_anthropic()/
_history_to_openai() let a tool call/result survive across separate requests
by reconstructing it into each provider's native multi-turn tool format.
"""

from __future__ import annotations

import civex.server.routers.ai as ai


def test_chat_request_discriminates_message_kinds() -> None:
    req = ai.ChatRequest(
        messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {
                "role": "tool_call",
                "id": "t1",
                "name": "list_schemas",
                "input": {},
                "result": "[]",
            },
        ]
    )
    assert [type(m).__name__ for m in req.messages] == [
        "UserMessage",
        "AssistantMessage",
        "ToolCallMessage",
    ]


def test_plain_text_history_passes_through_unchanged() -> None:
    history = [
        ai.UserMessage(content="hi"),
        ai.AssistantMessage(content="hello"),
        ai.UserMessage(content="how are you"),
    ]
    assert ai._history_to_anthropic(history) == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "how are you"},
    ]
    assert ai._history_to_openai(history) == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "how are you"},
    ]


def test_tool_call_with_preceding_text_merges_into_one_assistant_turn() -> None:
    """Anthropic rejects back-to-back assistant-role messages -- text and the
    tool call that followed it in the same original model turn must be one
    assistant message, immediately followed by the paired tool_result."""
    history = [
        ai.UserMessage(content="build a workflow"),
        ai.AssistantMessage(content="Let's get the guide."),
        ai.ToolCallMessage(
            id="t1", name="get_workflow_authoring_guide", input={}, result="GUIDE TEXT"
        ),
        ai.UserMessage(content="keep going"),
    ]
    anthropic_msgs = ai._history_to_anthropic(history)
    assert anthropic_msgs == [
        {"role": "user", "content": "build a workflow"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let's get the guide."},
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "get_workflow_authoring_guide",
                    "input": {},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "GUIDE TEXT"},
            ],
        },
        {"role": "user", "content": "keep going"},
    ]

    openai_msgs = ai._history_to_openai(history)
    assert openai_msgs[1] == {
        "role": "assistant",
        "content": "Let's get the guide.",
        "tool_calls": [
            {
                "id": "t1",
                "type": "function",
                "function": {"name": "get_workflow_authoring_guide", "arguments": "{}"},
            }
        ],
    }
    assert openai_msgs[2] == {
        "role": "tool",
        "tool_call_id": "t1",
        "content": "GUIDE TEXT",
    }
    assert openai_msgs[-1] == {"role": "user", "content": "keep going"}


def test_tool_call_with_no_preceding_text() -> None:
    """The model can call a tool with zero preamble text -- no empty text
    block/content should be emitted in that case."""
    history = [
        ai.UserMessage(content="list schemas"),
        ai.ToolCallMessage(id="t1", name="list_schemas", input={}, result="[]"),
    ]
    anthropic_msgs = ai._history_to_anthropic(history)
    assert anthropic_msgs[1] == {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": "t1", "name": "list_schemas", "input": {}}
        ],
    }

    openai_msgs = ai._history_to_openai(history)
    assert openai_msgs[1]["content"] is None


def test_multiple_tool_calls_in_one_turn_are_grouped_together() -> None:
    """Parallel tool calls from a single model completion must stay paired:
    one assistant message with all tool_use blocks, one user message with
    all matching tool_result blocks (not split across separate exchanges)."""
    history = [
        ai.UserMessage(content="look things up"),
        ai.ToolCallMessage(id="t1", name="list_schemas", input={}, result="[]"),
        ai.ToolCallMessage(id="t2", name="list_collections", input={}, result="[]"),
    ]
    anthropic_msgs = ai._history_to_anthropic(history)
    assert (
        len(anthropic_msgs) == 3
    )  # user, one assistant (2 tool_use), one user (2 tool_result)
    assert [b["id"] for b in anthropic_msgs[1]["content"]] == ["t1", "t2"]
    assert [b["tool_use_id"] for b in anthropic_msgs[2]["content"]] == ["t1", "t2"]

    openai_msgs = ai._history_to_openai(history)
    assert [tc["id"] for tc in openai_msgs[1]["tool_calls"]] == ["t1", "t2"]
    assert openai_msgs[2] == {"role": "tool", "tool_call_id": "t1", "content": "[]"}
    assert openai_msgs[3] == {"role": "tool", "tool_call_id": "t2", "content": "[]"}


def test_trailing_unresolved_tool_call_at_end_of_history() -> None:
    """A proposal tool halts the stream right after its result -- history can
    legitimately end on a tool_call with no further user/assistant turn."""
    history = [
        ai.UserMessage(content="create a schema"),
        ai.ToolCallMessage(
            id="t1",
            name="create_schema",
            input={"name": "x"},
            result='{"status": "proposed"}',
        ),
    ]
    anthropic_msgs = ai._history_to_anthropic(history)
    assert anthropic_msgs[-1] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "t1",
                "content": '{"status": "proposed"}',
            }
        ],
    }
