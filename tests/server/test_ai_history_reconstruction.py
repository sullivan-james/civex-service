"""ChatRequest discriminated-union parsing for the AI chat request body.

The pure history->provider-format conversion functions this file used to
also cover (_history_to_anthropic/_history_to_openai) now live in
tests/services/test_ai_history.py, alongside their new home in
civex.services.ai.history.
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
