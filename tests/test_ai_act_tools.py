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
    assert ai_service._ACT_TOOL_NAMES.issubset(names)
    assert len(ai_service.TOOLS_OPENAI) == len(
        ai_service.TOOLS
    )  # OpenAI mirror stays in sync


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


def test_update_schema_rejects_unknown_display_field(ctx) -> None:
    """Regression: update_schema never validated that display_field actually
    names a field on the schema before proposing."""
    result = _call("update_schema", {"name": "trial", "display_field": "ghost"}, ctx)
    assert result["status"] == "error"


def test_update_collection_rejects_rename_to_existing_name(ctx) -> None:
    """Regression: renaming a collection to a name already in use used to be
    proposed successfully and only fail at apply time."""
    ctx.dataset_svc.create("other")
    ctx.commit()
    result = _call("update_collection", {"name": "study", "rename": "other"}, ctx)
    assert result["status"] == "error"


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
                    },
                )()
                return FakeMessageStream(["ok "], final)
            final = type(
                "Final",
                (),
                {"stop_reason": "end_turn", "content": [_text_block("SECOND ROUND")]},
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
