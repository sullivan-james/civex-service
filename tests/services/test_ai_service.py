"""Direct unit tests for AiService itself (CIVEX-60): the system-prompt
builder, the validation_scope() escape hatch it exposes, and the
provider-agnostic tool-round loop in _run_stream(). dispatch_tool() is
already exercised end-to-end via tests/test_ai_act_tools.py -- these tests
cover the parts of service.py that file doesn't: _build_system_prompt()
actually building schema entries from real fields/restrictions and its
8000-char truncation branch (both untested before -- the golden test in
test_ai_system_prompt_tool_names.py only ever passes an empty schema list),
AiService.validation_scope() as a public method on the service itself, and
the _run_stream() round loop driven through a hand-rolled ChatProvider
(_ScriptedProvider below) instead of a monkeypatched anthropic/openai SDK --
this exercises the exact same provider-agnostic loop the existing
pytest.importorskip("openai"/"anthropic") tests in test_ai_act_tools.py do,
but without depending on either optional SDK being installed (the `ai`
extra isn't part of this repo's standard dev install, so those tests are
routinely skipped -- these aren't).
"""

from __future__ import annotations

import asyncio
import json

import pytest

import civex.services.ai.service as ai_service
from civex.config import AIConfig
from civex.context import AppContext
from civex.services.ai.providers.base import (
    ChatProvider,
    ErrorEvent,
    RoundEnd,
    TextDelta,
    TokenUsage,
    ToolCallRequest,
)
from civex.services.ai.service import _build_system_prompt


def test_build_system_prompt_includes_real_schema_fields_and_restrictions(
    ctx: AppContext,
) -> None:
    ctx.schema_svc.create("trial", description="t")
    ctx.schema_svc.add_field("trial", "subject", "string")
    ctx.schema_svc.add_field(
        "trial", "age", "integer", restrictions={"min": 0, "max": 120}
    )
    ctx.commit()

    prompt = _build_system_prompt(ctx)
    start = prompt.index("## Current project schemas")
    end = prompt.index("Available collections:")
    schema_compact = json.loads(
        prompt[start + len("## Current project schemas") : end].strip()
    )

    assert schema_compact == [
        {
            "name": "trial",
            "fields": [
                {"name": "subject", "type": "string"},
                {
                    "name": "age",
                    "type": "integer",
                    "restrictions": {"min": 0, "max": 120},
                },
            ],
        }
    ]


def test_build_system_prompt_truncates_past_the_char_budget(ctx: AppContext) -> None:
    """A field name/restriction blob long enough to blow the 8000-char budget
    on its own must stop further schemas from being embedded and leave a
    "use list_schemas tool" breadcrumb instead of silently growing forever."""
    ctx.schema_svc.create("big", description="t")
    choices = [f"choice_{i}" for i in range(2000)]
    ctx.schema_svc.add_field(
        "big", "wide", "string", restrictions={"choices": choices}
    )
    ctx.schema_svc.create("second", description="t")
    ctx.commit()

    prompt = _build_system_prompt(ctx)

    assert "additional schemas truncated" in prompt
    assert "use list_schemas tool" in prompt
    # The schema past the truncation point is not embedded verbatim.
    assert '"name": "second"' not in prompt


def test_build_system_prompt_lists_collections_or_says_none_yet(
    ctx: AppContext,
) -> None:
    assert "(none yet)" in _build_system_prompt(ctx)

    ctx.dataset_svc.create("study")
    ctx.dataset_svc.create("cohort")
    ctx.commit()

    prompt = _build_system_prompt(ctx)
    assert "Available collections: study, cohort" in prompt


def test_ai_service_validation_scope_rolls_back_on_success(ctx: AppContext) -> None:
    """AiService.validation_scope() (used by callers holding an AiService
    reference rather than an AiToolContext) must roll back just like
    AppContext.validation_scope() does -- same guarantee, different entry
    point onto the same underlying SAVEPOINT."""
    before = {s.name for s in ctx.schema_svc.list_all()}

    with ctx.ai_svc.validation_scope():
        ctx.schema_svc.create("temp", description="t")
        assert "temp" in {s.name for s in ctx.schema_svc.list_all()}

    assert {s.name for s in ctx.schema_svc.list_all()} == before


def test_ai_service_validation_scope_rolls_back_on_exception(ctx: AppContext) -> None:
    before = {s.name for s in ctx.schema_svc.list_all()}

    try:
        with ctx.ai_svc.validation_scope():
            ctx.schema_svc.create("temp", description="t")
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert {s.name for s in ctx.schema_svc.list_all()} == before


# ---------------------------------------------------------------------------
# _run_stream()'s round loop, driven by a hand-rolled ChatProvider so these
# tests need neither the anthropic nor the openai package installed.
# ---------------------------------------------------------------------------


class _ScriptedProvider(ChatProvider):
    """Replays a fixed list of RoundEnd scripts, one per stream_round() call."""

    def __init__(self, ai_cfg, rounds: list[dict]) -> None:
        super().__init__(ai_cfg)
        self._rounds = rounds
        self._calls = 0

    def parse_history(self, history: list) -> list:
        return []

    def render_system(self, prompt: str):
        return prompt

    def render_tools(self, tools):
        return list(tools)

    async def stream_round(self, *, system, tools, messages):
        script = self._rounds[self._calls]
        self._calls += 1
        for text in script.get("text", []):
            yield TextDelta(text)
        if "error" in script:
            yield ErrorEvent(script["error"])
            return
        yield script["end"]

    def append_tool_results(self, messages, round_end, results) -> None:
        messages.append(("assistant", round_end.raw))
        for tc, result_str in results:
            messages.append(("tool", tc.id, result_str))


def _run_scripted_stream(ctx: AppContext, monkeypatch, rounds: list[dict]) -> list[dict]:
    provider = _ScriptedProvider(
        AIConfig(api_key="x", model="m", provider="anthropic"), rounds
    )
    monkeypatch.setattr(ai_service, "get_chat_provider", lambda ai_cfg: provider)

    async def collect():
        out = []
        async for sse in ctx.ai_svc.stream_chat(
            [], AIConfig(api_key="x", model="m", provider="anthropic")
        ):
            out.append(json.loads(sse[len("data: ") :]))
        return out

    return asyncio.run(collect())


def test_run_stream_plain_text_response_ends_with_done(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    rounds = [
        {
            "text": ["hello "],
            "end": RoundEnd(tool_calls=[], is_final=True, raw=None, usage=None),
        }
    ]
    events = _run_scripted_stream(ctx, monkeypatch, rounds)
    assert [e["type"] for e in events] == ["text_delta", "done"]
    assert events[0]["delta"] == "hello "


def test_run_stream_dispatches_a_real_non_mutating_tool_and_continues(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx.dataset_svc.create("study")
    ctx.commit()
    rounds = [
        {
            "end": RoundEnd(
                tool_calls=[ToolCallRequest(id="1", name="list_collections", input={})],
                is_final=False,
                raw="r1",
            )
        },
        {
            "text": ["done talking"],
            "end": RoundEnd(tool_calls=[], is_final=True, raw=None),
        },
    ]
    events = _run_scripted_stream(ctx, monkeypatch, rounds)
    types = [e["type"] for e in events]
    assert types == [
        "tool_use_start",
        "tool_result",
        "text_delta",
        "done",
    ]
    tool_result = next(e for e in events if e["type"] == "tool_result")
    assert json.loads(tool_result["content"]) == [
        {"name": "study", "record_count": 0}
    ]


def test_run_stream_halts_immediately_after_a_proposed_tool(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only one round script -- if the loop asked the model again after the
    # proposal, _ScriptedProvider would raise IndexError.
    rounds = [
        {
            "end": RoundEnd(
                tool_calls=[
                    ToolCallRequest(
                        id="1", name="create_collection", input={"name": "study"}
                    )
                ],
                is_final=False,
                raw="r1",
            )
        }
    ]
    events = _run_scripted_stream(ctx, monkeypatch, rounds)
    assert events[-1]["type"] == "done"
    tool_result = next(e for e in events if e["type"] == "tool_result")
    assert json.loads(tool_result["content"])["status"] == "proposed"


def test_run_stream_short_circuits_a_repeated_identical_tool_call(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    same_call = ToolCallRequest(id="dup", name="list_collections", input={})
    rounds = [
        {"end": RoundEnd(tool_calls=[same_call], is_final=False, raw="r1")},
        {"end": RoundEnd(tool_calls=[same_call], is_final=False, raw="r2")},
        {"text": ["ok"], "end": RoundEnd(tool_calls=[], is_final=True, raw=None)},
    ]
    events = _run_scripted_stream(ctx, monkeypatch, rounds)
    tool_results = [json.loads(e["content"]) for e in events if e["type"] == "tool_result"]
    assert len(tool_results) == 2
    assert tool_results[0] == []  # the real dispatch result
    assert tool_results[1]["status"] == "error"
    assert "already called" in tool_results[1]["message"]


def test_run_stream_records_and_emits_token_usage(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    rounds = [
        {
            "text": ["hi"],
            "end": RoundEnd(
                tool_calls=[],
                is_final=True,
                raw=None,
                usage=TokenUsage(input_tokens=111, output_tokens=22),
            ),
        }
    ]
    events = _run_scripted_stream(ctx, monkeypatch, rounds)
    usage_events = [e for e in events if e["type"] == "usage"]
    assert usage_events == [{"type": "usage", "input_tokens": 111, "output_tokens": 22}]

    totals = ctx.ai_usage_svc.totals()
    assert totals.requests == 1
    assert totals.input_tokens == 111
    assert totals.output_tokens == 22


def test_run_stream_stops_on_mid_stream_provider_error(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    rounds = [{"text": ["partial"], "error": "provider exploded"}]
    events = _run_scripted_stream(ctx, monkeypatch, rounds)
    assert events == [
        {"type": "text_delta", "delta": "partial"},
        {"type": "error", "message": "provider exploded"},
    ]


def test_run_stream_errors_out_past_max_tool_rounds(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    rounds = [
        {
            "end": RoundEnd(
                tool_calls=[
                    ToolCallRequest(id=str(i), name="list_collections", input={"i": i})
                ],
                is_final=False,
                raw=f"r{i}",
            )
        }
        for i in range(ai_service.MAX_TOOL_ROUNDS)
    ]
    events = _run_scripted_stream(ctx, monkeypatch, rounds)
    assert events[-1]["type"] == "error"
    assert "Maximum tool rounds exceeded" in events[-1]["message"]
