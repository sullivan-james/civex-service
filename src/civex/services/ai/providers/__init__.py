"""ChatProvider abstraction: one adapter per LLM API shape (CIVEX-51).

get_chat_provider(ai_cfg) picks the adapter the same way _stream_chat's
if/else used to. AiService.stream_chat drives a single MAX_TOOL_ROUNDS loop
against whichever provider it gets back, instead of running two
near-duplicate ~140-line streaming functions.
"""

from __future__ import annotations

from civex.config import AIConfig
from civex.services.ai.providers.anthropic_provider import AnthropicProvider
from civex.services.ai.providers.base import (
    ChatProvider,
    ErrorEvent,
    ProviderEvent,
    RoundEnd,
    TextDelta,
    ToolCallRequest,
)
from civex.services.ai.providers.openai_provider import OpenAIProvider

__all__ = [
    "ChatProvider",
    "ErrorEvent",
    "ProviderEvent",
    "RoundEnd",
    "TextDelta",
    "ToolCallRequest",
    "AnthropicProvider",
    "OpenAIProvider",
    "get_chat_provider",
]


def get_chat_provider(ai_cfg: AIConfig) -> ChatProvider:
    if ai_cfg.provider == "openai-compat":
        return OpenAIProvider(ai_cfg)
    return AnthropicProvider(ai_cfg)
