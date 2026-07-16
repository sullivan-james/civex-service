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
    return json.loads(ai._dispatch_tool(name, args, ctx))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_all_act_tools_registered() -> None:
    names = {t["name"] for t in ai.TOOLS}
    assert ai._ACT_TOOL_NAMES.issubset(names)
    assert len(ai.TOOLS_OPENAI) == len(ai.TOOLS)  # OpenAI mirror stays in sync


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


def test_is_proposal_helper() -> None:
    assert ai._is_proposal('{"status": "proposed", "action": "create_record"}') is True
    assert ai._is_proposal('{"status": "error"}') is False
    assert ai._is_proposal("[]") is False
    assert ai._is_proposal("not json") is False


def test_openai_stream_halts_after_a_proposed_tool(ctx, monkeypatch) -> None:
    """When a tool proposes a change, the loop must stop that round — it must not
    feed the result back to the model or stream any further text."""
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
        async for sse in ai._stream_chat_openai(history, ctx, cfg):
            out.append(_json.loads(sse[len("data: ") :]))
        return out

    events = asyncio.run(collect())
    types = [e["type"] for e in events]

    assert served["rounds"] == 1  # never asked the model a 2nd time
    assert types[-1] == "done"  # cleanly ended
    assert not any("SECOND ROUND" in _json.dumps(e) for e in events)
    tr = next(e for e in events if e["type"] == "tool_result")
    assert _json.loads(tr["content"])["status"] == "proposed"
