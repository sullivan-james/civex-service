"""ChatProvider ABC + the provider-agnostic event types stream_round() yields.

Mirrors plugins/registry.get_plugin() and sync/transport.get_transport():
a plain-class-plus-factory, not a Protocol -- lets AnthropicProvider/
OpenAIProvider share state (self.ai_cfg) and any future helper logic on the
base class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncIterator, Iterable

if TYPE_CHECKING:
    from civex.config import AIConfig
    from civex.services.ai.tools.base import AiTool


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolCallRequest:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class RoundEnd:
    """Terminal event for one stream_round() call.

    is_final mirrors each provider's own native "no more tool calls" signal
    (Anthropic's stop_reason == "end_turn"; OpenAI's finish_reason !=
    "tool_calls") rather than being derived from `tool_calls` being empty --
    the two aren't quite guaranteed identical in every edge case, and the
    round loop needs to replicate the original per-provider branching
    exactly. `raw` is the provider-native representation of this round's
    assistant turn (an Anthropic Message / an OpenAI-shaped dict), opaque to
    the caller, and is threaded back into append_tool_results() unchanged.
    """

    tool_calls: list[ToolCallRequest]
    is_final: bool
    raw: Any


@dataclass
class ErrorEvent:
    message: str


ProviderEvent = TextDelta | RoundEnd | ErrorEvent


class ChatProvider(ABC):
    def __init__(self, ai_cfg: AIConfig | None = None) -> None:
        # Optional: TOOLS/TOOLS_OPENAI-style module constants build a
        # provider just to call render_tools(), which never touches ai_cfg.
        # Only stream_round() requires a real one.
        self.ai_cfg = ai_cfg

    @abstractmethod
    def parse_history(self, history: list) -> list[Any]:
        """Reconstruct prior chat-turns (incl. tool calls/results) into this
        provider's native multi-turn message shape."""
        ...

    @abstractmethod
    def render_system(self, prompt: str) -> Any:
        """Wrap the shared system prompt for this provider's API shape."""
        ...

    @abstractmethod
    def render_tools(self, tools: Iterable[type[AiTool]]) -> Any:
        """Shape TOOL_REGISTRY's AiTool classes into this provider's tool
        schema, reading name/description/input_schema straight off each
        class -- no intermediate ToolSchema object."""
        ...

    def prompt_fragment(self) -> str:
        """Optional provider/backend-specific text appended to the shared
        system prompt (e.g. OpenRouter's free-tier budget warning, a
        small-local-model note) -- request-shaping like extra_body/
        extra_headers stays inside stream_round() as an implementation
        detail, not surfaced here. Defaults to no fragment; only
        OpenAIProvider overrides this today, since neither existing note is
        reachable on the Anthropic path (both gate on base_url, which that
        path never sets)."""
        return ""

    @abstractmethod
    def stream_round(
        self, *, system: Any, tools: Any, messages: list[Any]
    ) -> AsyncIterator[ProviderEvent]:
        """Stream one model turn: zero or more TextDelta events, an optional
        ErrorEvent (which ends the whole chat, not just this round), then
        exactly one RoundEnd."""
        ...

    @abstractmethod
    def append_tool_results(
        self,
        messages: list[Any],
        round_end: RoundEnd,
        results: list[tuple[ToolCallRequest, str]],
    ) -> None:
        """Mutate `messages` in place: append the assistant's turn (from
        round_end.raw) followed by the tool results, in this provider's
        native shape, so the next stream_round() call sees them."""
        ...
