"""Regression tests for the AI agent's mutating "act" tools.

The core guarantee: act tools are **validate-only**. Dispatching one returns a
"proposed" change (or an "error") and must NEVER mutate data — the real change
happens only when the user approves it in the UI, which triggers a separate REST
call. These tests lock that in, plus the destructive flags and reference checks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import civex.server.routers.ai as ai
import civex.services.ai.service as ai_service
from civex.config import load_config
from civex.context import build_local_context
from civex.main import app as cli_app
from civex.services.ai.tools.registry import TOOL_REGISTRY

_ACT_TOOL_NAMES = {
    "create_record",
    "update_record",
    "delete_record",
    "create_schema",
    "update_schema",
    "delete_schema",
    "add_schema_field",
    "update_schema_field",
    "delete_schema_field",
    "create_collection",
    "update_collection",
    "delete_collection",
}

runner = CliRunner()


@pytest.fixture()
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A project seeded with one schema ('trial'), one collection ('study')."""
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(cli_app, ["init", "--sqlite", str(tmp_path)]).exit_code == 0
    c = build_local_context(load_config())
    c.schema_svc.create("trial", description="t")
    c.schema_svc.add_field("trial", "subject", "string")
    c.dataset_svc.create("study")
    c.commit()
    yield c
    c.close()


def _call(name: str, args: dict, ctx) -> dict:
    return json.loads(ctx.ai_svc.dispatch_tool(name, args))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_all_act_tools_registered() -> None:
    names = {t["name"] for t in ai_service.TOOLS}
    assert _ACT_TOOL_NAMES.issubset(names)
    assert len(ai_service.TOOLS_OPENAI) == len(
        ai_service.TOOLS
    )  # OpenAI mirror stays in sync


def test_act_tools_are_flagged_mutating_in_the_registry() -> None:
    for name in _ACT_TOOL_NAMES:
        assert TOOL_REGISTRY[name].mutating is True
    non_act_names = set(TOOL_REGISTRY) - _ACT_TOOL_NAMES
    assert non_act_names  # sanity: there are non-act tools too
    for name in non_act_names:
        assert TOOL_REGISTRY[name].mutating is False


# ---------------------------------------------------------------------------
# Validate-only: proposals never mutate
# ---------------------------------------------------------------------------


def test_create_record_proposes_without_mutating(ctx) -> None:
    before = ctx.record_svc.find_by_schema("trial", limit=1000)
    result = _call(
        "create_record",
        {"collection": "study", "schema": "trial", "data": {"subject": "S1"}},
        ctx,
    )
    assert result["status"] == "proposed"
    assert result["request"]["method"] == "POST"
    assert result["request"]["path"] == "/api/collections/study/records"
    assert result["request"]["body"] == {
        "schema_name": "trial",
        "data": {"subject": "S1"},
    }
    # Nothing was actually created.
    assert len(ctx.record_svc.find_by_schema("trial", limit=1000)) == len(before)


def test_delete_schema_proposes_without_mutating(ctx) -> None:
    result = _call("delete_schema", {"name": "trial"}, ctx)
    assert result["status"] == "proposed"
    assert result["destructive"] is True
    assert result["request"] == {"method": "DELETE", "path": "/api/schemas/trial"}
    # Schema still exists.
    assert "trial" in {s.name for s in ctx.schema_svc.list_all()}


def test_delete_collection_proposes_without_mutating(ctx) -> None:
    result = _call("delete_collection", {"name": "study"}, ctx)
    assert result["status"] == "proposed"
    assert result["destructive"] is True
    assert "study" in {d.name for d in ctx.dataset_svc.list_all()}


# ---------------------------------------------------------------------------
# Destructive flag
# ---------------------------------------------------------------------------


def test_destructive_flag_set_for_deletes(ctx) -> None:
    rec = ctx.record_svc.add("study", "trial", {"subject": "S1"})
    ctx.commit()
    assert (
        _call("delete_record", {"record_id": str(rec.id)}, ctx)["destructive"] is True
    )
    assert (
        _call("delete_schema_field", {"schema": "trial", "field": "subject"}, ctx)[
            "destructive"
        ]
        is True
    )


def test_non_destructive_flag_for_edits(ctx) -> None:
    rec = ctx.record_svc.add("study", "trial", {"subject": "S1"})
    ctx.commit()
    assert (
        _call(
            "create_record", {"collection": "study", "schema": "trial", "data": {}}, ctx
        )["destructive"]
        is False
    )
    assert (
        _call(
            "update_record", {"record_id": str(rec.id), "data": {"subject": "S2"}}, ctx
        )["destructive"]
        is False
    )
    assert _call("create_collection", {"name": "other"}, ctx)["destructive"] is False


# ---------------------------------------------------------------------------
# Reference validation
# ---------------------------------------------------------------------------


def test_create_record_rejects_unknown_collection(ctx) -> None:
    assert (
        _call(
            "create_record", {"collection": "ghost", "schema": "trial", "data": {}}, ctx
        )["status"]
        == "error"
    )


def test_create_record_rejects_unknown_schema(ctx) -> None:
    assert (
        _call(
            "create_record", {"collection": "study", "schema": "ghost", "data": {}}, ctx
        )["status"]
        == "error"
    )


def test_update_and_delete_reject_unknown_record(ctx) -> None:
    assert (
        _call("update_record", {"record_id": "nope", "data": {"subject": "x"}}, ctx)[
            "status"
        ]
        == "error"
    )
    assert _call("delete_record", {"record_id": "nope"}, ctx)["status"] == "error"


def test_create_rejects_duplicates(ctx) -> None:
    assert _call("create_collection", {"name": "study"}, ctx)["status"] == "error"
    assert _call("create_schema", {"name": "trial"}, ctx)["status"] == "error"


def test_update_with_no_changes_is_error(ctx) -> None:
    rec = ctx.record_svc.add("study", "trial", {"subject": "S1"})
    ctx.commit()
    assert (
        _call("update_record", {"record_id": str(rec.id), "data": {}}, ctx)["status"]
        == "error"
    )
    assert _call("update_collection", {"name": "study"}, ctx)["status"] == "error"


# ---------------------------------------------------------------------------
# Streaming halts on a proposal (so the approval prompt stays chronological)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# list_records — server-side narrowing so the agent never sees the whole table
# ---------------------------------------------------------------------------


def _seed_records(ctx) -> None:
    ctx.schema_svc.add_field("trial", "n", "integer")
    for sub, n in [("S01", 10), ("S02", 30), ("S03", 30)]:
        ctx.record_svc.add("study", "trial", {"subject": sub, "n": n})
    ctx.commit()


def test_list_records_returns_ids_and_data(ctx) -> None:
    _seed_records(ctx)
    r = _call("list_records", {"collection": "study"}, ctx)
    assert r["total"] == 3
    assert len(r["records"]) == 3
    assert all("id" in rec and "data" in rec for rec in r["records"])


def test_list_records_free_text_search(ctx) -> None:
    _seed_records(ctx)
    r = _call("list_records", {"collection": "study", "search": "S02"}, ctx)
    assert [rec["data"]["subject"] for rec in r["records"]] == ["S02"]


def test_list_records_field_filter_string(ctx) -> None:
    _seed_records(ctx)
    r = _call(
        "list_records",
        {"collection": "study", "schema": "trial", "filters": ["subject=S02"]},
        ctx,
    )
    assert r["total"] == 1
    assert r["records"][0]["data"]["subject"] == "S02"


def test_list_records_field_filter_integer(ctx) -> None:
    # Regression: numeric-field filters used to silently return nothing on SQLite.
    _seed_records(ctx)
    r = _call(
        "list_records",
        {"collection": "study", "schema": "trial", "filters": ["n=30"]},
        ctx,
    )
    assert r["total"] == 2
    assert sorted(rec["data"]["subject"] for rec in r["records"]) == ["S02", "S03"]


def test_list_records_filter_requires_schema(ctx) -> None:
    _seed_records(ctx)
    r = _call("list_records", {"collection": "study", "filters": ["subject=S02"]}, ctx)
    assert r["status"] == "error"  # silent-wrong-result guard


def test_list_records_respects_limit(ctx) -> None:
    _seed_records(ctx)
    r = _call("list_records", {"collection": "study", "limit": 1}, ctx)
    assert r["total"] == 3  # true total still reported
    assert len(r["records"]) == 1  # but payload is bounded


def test_list_records_unknown_collection(ctx) -> None:
    assert _call("list_records", {"collection": "ghost"}, ctx)["status"] == "error"


# ---------------------------------------------------------------------------
# get_job_log -- no prior test coverage existed for this tool at all. Also
# covers a real bug caught by mypy during the CIVEX-54 tool-registry
# migration: job_svc.get_job() returns None (not a raised NotFoundError) for
# an unknown UUID, so the old code (job.status on a None job) would have
# raised AttributeError instead of returning the intended "job not found".
# ---------------------------------------------------------------------------


def test_get_job_log_unknown_uuid_returns_not_found(ctx) -> None:
    import uuid

    result = _call("get_job_log", {"job_id": str(uuid.uuid4())}, ctx)
    assert result == {"error": "job not found"}


def test_get_job_log_malformed_uuid_returns_not_found(ctx) -> None:
    result = _call("get_job_log", {"job_id": "not-a-uuid"}, ctx)
    assert result == {"error": "job not found"}


def test_get_job_log_returns_real_job_status(ctx) -> None:
    rec = ctx.record_svc.add("study", "trial", {"subject": "S1"})
    ctx.commit()
    job = ctx.job_svc.enqueue_manual("some-workflow", rec)
    ctx.commit()
    result = _call("get_job_log", {"job_id": str(job.id)}, ctx)
    assert result == {"status": "pending", "error": None, "log": None}


# ---------------------------------------------------------------------------
# Restriction-key validation (regression: the model used to be able to invent
# keys like "format" on a file field, which _check_restrictions silently
# ignores at write time -- the restriction would look set but enforce nothing)
# ---------------------------------------------------------------------------


def test_create_schema_rejects_unknown_restriction_key(ctx) -> None:
    result = _call(
        "create_schema",
        {
            "name": "recording",
            "fields": [
                {
                    "name": "recording_file",
                    "type": "file",
                    "restrictions": {"format": ".wav"},
                }
            ],
        },
        ctx,
    )
    assert result["status"] == "error"
    assert "format" in result["message"]
    assert "recording" not in {s.name for s in ctx.schema_svc.list_all()}


def test_create_schema_accepts_correct_accept_key(ctx) -> None:
    result = _call(
        "create_schema",
        {
            "name": "recording",
            "fields": [
                {
                    "name": "recording_file",
                    "type": "file",
                    "restrictions": {"accept": ".wav"},
                }
            ],
        },
        ctx,
    )
    assert result["status"] == "proposed"


def test_add_schema_field_rejects_unknown_restriction_key(ctx) -> None:
    result = _call(
        "add_schema_field",
        {
            "schema": "trial",
            "name": "audio",
            "type": "file",
            "restrictions": {"format": ".wav"},
        },
        ctx,
    )
    assert result["status"] == "error"
    assert "format" in result["message"]


def test_update_schema_field_rejects_unknown_restriction_key(ctx) -> None:
    result = _call(
        "update_schema_field",
        {
            "schema": "trial",
            "field": "subject",
            "restrictions": {"choices": ["a"], "bogus": 1},
        },
        ctx,
    )
    assert result["status"] == "error"
    assert "bogus" in result["message"]


# ---------------------------------------------------------------------------
# CIVEX-49: act tools now validate by calling the real service method inside
# a rolled-back SAVEPOINT (AppContext.validation_scope()), instead of a
# hand-maintained duplicate of a subset of the real validation rules. This
# closes real gaps that existed before -- value-level restrictions were never
# checked at propose time, and several existence/uniqueness checks were
# either missing or only ran conditionally.
# ---------------------------------------------------------------------------


def test_create_record_validates_field_restrictions_at_propose_time(ctx) -> None:
    """Regression: create_record's proposal used to check only collection/schema
    existence -- an out-of-range value would show status "proposed" and only
    fail later when the user clicked Approve."""
    ctx.schema_svc.add_field(
        "trial", "age", "integer", restrictions={"min": 0, "max": 120}
    )
    ctx.commit()
    result = _call(
        "create_record",
        {"collection": "study", "schema": "trial", "data": {"age": 999}},
        ctx,
    )
    assert result["status"] == "error"
    assert "999" in result["message"]
    assert "maximum" in result["message"]


def test_create_record_rollback_is_immediate_within_the_same_turn(ctx) -> None:
    """The SAVEPOINT used to validate an invalid create_record must be rolled
    back before dispatch_tool() returns, not deferred to end-of-request:
    /ai/chat allows up to MAX_TOOL_ROUNDS calls on one session, so a later
    list_records call in the SAME turn must not see the rejected record."""
    ctx.schema_svc.add_field(
        "trial", "age", "integer", restrictions={"min": 0, "max": 120}
    )
    ctx.commit()
    before_total = _call("list_records", {"collection": "study"}, ctx)["total"]

    result = _call(
        "create_record",
        {"collection": "study", "schema": "trial", "data": {"age": 999}},
        ctx,
    )
    assert result["status"] == "error"

    after_total = _call("list_records", {"collection": "study"}, ctx)["total"]
    assert after_total == before_total  # proves the rollback actually happened


def test_update_record_validates_field_restrictions_at_propose_time(ctx) -> None:
    ctx.schema_svc.add_field(
        "trial", "age", "integer", restrictions={"min": 0, "max": 120}
    )
    ctx.commit()
    rec = ctx.record_svc.add("study", "trial", {"subject": "S1", "age": 30})
    ctx.commit()
    result = _call(
        "update_record", {"record_id": str(rec.id), "data": {"age": -5}}, ctx
    )
    assert result["status"] == "error"
    assert "minimum" in result["message"]
    assert ctx.record_svc.get(str(rec.id)).data["age"] == 30  # untouched


def test_add_schema_field_rejects_duplicate_field_name(ctx) -> None:
    """Regression: add_schema_field never checked whether the field name
    already existed on the schema before proposing -- only apply-time did."""
    result = _call(
        "add_schema_field",
        {"schema": "trial", "name": "subject", "type": "string"},
        ctx,
    )
    assert result["status"] == "error"
    assert "subject" in result["message"]


def test_update_schema_field_rejects_rename_to_existing_name(ctx) -> None:
    """Regression: renaming a field to a name already used by another field on
    the same schema used to be proposed successfully."""
    ctx.schema_svc.add_field("trial", "email", "string")
    ctx.commit()
    result = _call(
        "update_schema_field",
        {"schema": "trial", "field": "email", "rename": "subject"},
        ctx,
    )
    assert result["status"] == "error"


def test_update_schema_field_rejects_unknown_field_without_restrictions(ctx) -> None:
    """Regression: field existence used to be checked only when restrictions
    were also being changed -- renaming a nonexistent field (with no
    restrictions in the call) used to be proposed successfully."""
    result = _call(
        "update_schema_field", {"schema": "trial", "field": "ghost", "rename": "x"}, ctx
    )
    assert result["status"] == "error"


def test_update_schema_rejects_unknown_template_variable(ctx) -> None:
    """Regression: update_schema never validated that display_template only
    uses fields on the schema before proposing."""
    result = _call(
        "update_schema", {"name": "trial", "display_template": "{ghost}"}, ctx
    )
    assert result["status"] == "error"


def test_update_collection_rejects_rename_to_existing_name(ctx) -> None:
    """Regression: renaming a collection to a name already in use used to be
    proposed successfully and only fail at apply time."""
    ctx.dataset_svc.create("other")
    ctx.commit()
    result = _call("update_collection", {"name": "study", "rename": "other"}, ctx)
    assert result["status"] == "error"


def test_cli_ai_usage_shows_totals_and_per_model_breakdown(ctx) -> None:
    ctx.ai_usage_svc.record("anthropic", "claude-sonnet-5", 100, 50)
    ctx.ai_usage_svc.record("openai-compat", "qwen2.5:7b", 20, 5)

    result = runner.invoke(cli_app, ["ai", "usage"])
    assert result.exit_code == 0
    assert "120" in result.output  # total input tokens (100 + 20)
    assert "55" in result.output  # total output tokens (50 + 5)
    assert "claude-sonnet-5" in result.output
    assert "qwen2.5:7b" in result.output


def test_cli_ai_usage_with_no_events_prints_a_friendly_message(ctx) -> None:
    result = runner.invoke(cli_app, ["ai", "usage"])
    assert result.exit_code == 0
    assert "No AI usage recorded" in result.output


def test_is_proposal_helper() -> None:
    assert (
        ai_service._is_proposal('{"status": "proposed", "action": "create_record"}')
        is True
    )
    assert ai_service._is_proposal('{"status": "error"}') is False
    assert ai_service._is_proposal("[]") is False
    assert ai_service._is_proposal("not json") is False


def test_openai_stream_halts_after_a_proposed_tool(ctx, monkeypatch) -> None:
    """When a tool proposes a change, the loop must stop that round — it must not
    feed the result back to the model or stream any further text."""
    pytest.importorskip("openai")
    import asyncio
    import json as _json

    from civex.config import AIConfig

    served = {"rounds": 0}

    def _chunk(*, content=None, tool_calls=None, finish=None):
        delta = type("D", (), {"content": content, "tool_calls": tool_calls})()
        choice = type("C", (), {"delta": delta, "finish_reason": finish})()
        return type("Chunk", (), {"choices": [choice]})()

    class FakeStream:
        def __init__(self, chunks):
            self._chunks = chunks

        def __aiter__(self):
            async def gen():
                for c in self._chunks:
                    yield c

            return gen()

    class FakeCompletions:
        async def create(self, **_kw):
            served["rounds"] += 1
            if served["rounds"] == 1:
                tc = type(
                    "TC",
                    (),
                    {
                        "index": 0,
                        "id": "call_1",
                        "function": type(
                            "F",
                            (),
                            {
                                "name": "create_record",
                                "arguments": _json.dumps(
                                    {
                                        "collection": "study",
                                        "schema": "trial",
                                        "data": {},
                                    }
                                ),
                            },
                        )(),
                    },
                )()
                return FakeStream(
                    [
                        _chunk(content="ok "),
                        _chunk(tool_calls=[tc], finish="tool_calls"),
                    ]
                )
            return FakeStream([_chunk(content="SECOND ROUND", finish="stop")])

    class FakeClient:
        def __init__(self, *a, **k):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)

    cfg = AIConfig(
        api_key="x",
        model="m",
        provider="openai-compat",
        base_url="http://localhost:1/v1",
    )

    async def collect():
        out = []
        history = [ai.UserMessage(content="add a record")]
        async for sse in ctx.ai_svc.stream_chat(history, cfg):
            out.append(_json.loads(sse[len("data: ") :]))
        return out

    events = asyncio.run(collect())
    types = [e["type"] for e in events]

    assert served["rounds"] == 1  # never asked the model a 2nd time
    assert types[-1] == "done"  # cleanly ended
    assert not any("SECOND ROUND" in _json.dumps(e) for e in events)
    tr = next(e for e in events if e["type"] == "tool_result")
    assert _json.loads(tr["content"])["status"] == "proposed"


def test_repeated_identical_tool_call_is_short_circuited(ctx, monkeypatch) -> None:
    """Regression: a weak model that responds to an error by blindly repeating
    the exact same tool call (same name, same args) instead of fixing it used
    to burn every remaining round re-dispatching an identical, deterministically
    -failing call. The 2nd+ identical call must be short-circuited with a
    distinct "stop repeating" message rather than re-invoking the real tool."""
    pytest.importorskip("openai")
    import asyncio
    import json as _json

    from civex.config import AIConfig

    served = {"rounds": 0}
    dispatch_calls = {"count": 0}
    real_dispatch = ai_service._dispatch_tool

    def counting_dispatch(name, tool_input, ctx_):
        dispatch_calls["count"] += 1
        return real_dispatch(name, tool_input, ctx_)

    monkeypatch.setattr(ai_service, "_dispatch_tool", counting_dispatch)

    def _chunk(*, content=None, tool_calls=None, finish=None):
        delta = type("D", (), {"content": content, "tool_calls": tool_calls})()
        choice = type("C", (), {"delta": delta, "finish_reason": finish})()
        return type("Chunk", (), {"choices": [choice]})()

    class FakeStream:
        def __init__(self, chunks):
            self._chunks = chunks

        def __aiter__(self):
            async def gen():
                for c in self._chunks:
                    yield c

            return gen()

    def _tc(call_id):
        return type(
            "TC",
            (),
            {
                "index": 0,
                "id": call_id,
                "function": type(
                    "F",
                    (),
                    {
                        "name": "list_records",
                        "arguments": _json.dumps({"collection": "ghost"}),
                    },
                )(),
            },
        )()

    class FakeCompletions:
        async def create(self, **_kw):
            served["rounds"] += 1
            if served["rounds"] <= 3:
                return FakeStream(
                    [
                        _chunk(
                            tool_calls=[_tc(f"call_{served['rounds']}")],
                            finish="tool_calls",
                        )
                    ]
                )
            return FakeStream([_chunk(content="done", finish="stop")])

    class FakeClient:
        def __init__(self, *a, **k):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)

    cfg = AIConfig(
        api_key="x",
        model="m",
        provider="openai-compat",
        base_url="http://localhost:1/v1",
    )

    async def collect():
        out = []
        history = [ai.UserMessage(content="find something in ghost")]
        async for sse in ctx.ai_svc.stream_chat(history, cfg):
            out.append(_json.loads(sse[len("data: ") :]))
        return out

    events = asyncio.run(collect())
    tool_results = [
        _json.loads(e["content"]) for e in events if e["type"] == "tool_result"
    ]

    assert len(tool_results) == 3
    assert dispatch_calls["count"] == 1  # only the first identical call actually ran
    assert tool_results[0]["status"] == "error"
    assert "does not exist" in tool_results[0]["message"]
    for repeat in tool_results[1:]:
        assert repeat["status"] == "error"
        assert "already called" in repeat["message"]


def test_stream_chat_records_and_emits_token_usage(ctx, monkeypatch) -> None:
    """Every round's token usage must both be persisted via ai_usage_svc and
    streamed as a 'usage' SSE event, regardless of provider (CIVEX token
    usage tracking)."""
    pytest.importorskip("openai")
    import asyncio
    import json as _json

    from civex.config import AIConfig

    def _text_chunk(content, finish=None):
        delta = type("D", (), {"content": content, "tool_calls": None})()
        choice = type("C", (), {"delta": delta, "finish_reason": finish})()
        return type("Chunk", (), {"choices": [choice], "usage": None})()

    def _usage_chunk():
        usage = type("Usage", (), {"prompt_tokens": 111, "completion_tokens": 22})()
        return type("Chunk", (), {"choices": [], "usage": usage})()

    class FakeStream:
        def __aiter__(self):
            async def gen():
                yield _text_chunk("hi", finish="stop")
                yield _usage_chunk()

            return gen()

    class FakeCompletions:
        async def create(self, **_kw):
            return FakeStream()

    class FakeClient:
        def __init__(self, *a, **k):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)

    cfg = AIConfig(
        api_key="x",
        model="my-model",
        provider="openai-compat",
        base_url="http://localhost:1/v1",
    )

    async def collect():
        out = []
        history = [ai.UserMessage(content="hi")]
        async for sse in ctx.ai_svc.stream_chat(history, cfg):
            out.append(_json.loads(sse[len("data: ") :]))
        return out

    events = asyncio.run(collect())
    usage_events = [e for e in events if e["type"] == "usage"]
    assert usage_events == [{"type": "usage", "input_tokens": 111, "output_tokens": 22}]

    totals = ctx.ai_usage_svc.totals()
    assert totals.requests == 1
    assert totals.input_tokens == 111
    assert totals.output_tokens == 22

    by_model = ctx.ai_usage_svc.by_model()
    assert len(by_model) == 1
    assert by_model[0].provider == "openai-compat"
    assert by_model[0].model == "my-model"


def test_anthropic_stream_halts_after_a_proposed_tool(ctx, monkeypatch) -> None:
    """Anthropic-provider mirror of test_openai_stream_halts_after_a_proposed_tool
    above -- same guarantee (the round-loop stops immediately after a proposed
    tool, never asks the model again), pinned before the CIVEX-51 ChatProvider
    unification so the merge can be checked against this exact event sequence."""
    pytest.importorskip("anthropic")
    import asyncio
    import json as _json

    from civex.config import AIConfig

    served = {"rounds": 0}

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

    class FakeMessageStream:
        def __init__(self, deltas, final):
            self._deltas = deltas
            self._final = final

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        @property
        def text_stream(self):
            async def gen():
                for d in self._deltas:
                    yield d

            return gen()

        async def get_final_message(self):
            return self._final

    class FakeMessages:
        def stream(self, **_kw):
            served["rounds"] += 1
            fake_usage = type("Usage", (), {"input_tokens": 12, "output_tokens": 34})()
            if served["rounds"] == 1:
                final = type(
                    "Final",
                    (),
                    {
                        "stop_reason": "tool_use",
                        "content": [
                            _text_block("ok "),
                            _tool_block(
                                "call_1",
                                "create_record",
                                {"collection": "study", "schema": "trial", "data": {}},
                            ),
                        ],
                        "usage": fake_usage,
                    },
                )()
                return FakeMessageStream(["ok "], final)
            final = type(
                "Final",
                (),
                {
                    "stop_reason": "end_turn",
                    "content": [_text_block("SECOND ROUND")],
                    "usage": fake_usage,
                },
            )()
            return FakeMessageStream(["SECOND ROUND"], final)

    class FakeClient:
        def __init__(self, *a, **k):
            self.messages = FakeMessages()

    import anthropic

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeClient)

    cfg = AIConfig(api_key="x", model="m", provider="anthropic")

    async def collect():
        out = []
        history = [ai.UserMessage(content="add a record")]
        async for sse in ctx.ai_svc.stream_chat(history, cfg):
            out.append(_json.loads(sse[len("data: ") :]))
        return out

    events = asyncio.run(collect())
    types = [e["type"] for e in events]

    assert served["rounds"] == 1  # never asked the model a 2nd time
    assert types[-1] == "done"  # cleanly ended
    assert not any("SECOND ROUND" in _json.dumps(e) for e in events)
    tr = next(e for e in events if e["type"] == "tool_result")
    assert _json.loads(tr["content"])["status"] == "proposed"
