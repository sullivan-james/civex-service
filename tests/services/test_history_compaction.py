"""History written before deltas is converted to them after the project opens:
everything reads the same afterwards, an entry that wouldn't is kept whole, and
stopping part way loses nothing."""

from __future__ import annotations

import pytest

import civex.services.history_compaction as compaction
from civex.context import AppContext
from civex.db.models import AuditLog


@pytest.fixture()
def old_history(
    ctx: AppContext, make_schema, make_collection, make_record, monkeypatch
):
    """A project whose history was written as v1.2.0 wrote it: whole snapshots."""
    import civex.repositories.local.audit_repo as audit_repo

    # Only this patch is undone (`monkeypatch.undo()` would also undo the
    # fixture's chdir, leaving the test to find a project above its folder).
    with monkeypatch.context() as patched:
        patched.setattr(audit_repo, "stored_form", lambda o, n: (o, n, None, 1))
        make_schema(
            "site", fields=[("name", "string"), ("depth", "float"), ("notes", "string")]
        )
        make_collection("survey")
        records = [
            make_record(
                "survey", "site", {"name": f"s{i}", "depth": 1.0, "notes": "x" * 3000}
            )
            for i in range(12)
        ]
        for i, r in enumerate(records):
            for n in range(3):
                ctx.record_svc.update(
                    str(r.id),
                    {"name": f"s{i}-{n}", "depth": float(n), "notes": "x" * 3000},
                )
        ctx.record_svc.delete(str(records[0].id))
        ctx.record_svc.restore(str(records[0].id))
        ctx.commit()
    return records


def _read(ctx: AppContext) -> dict:
    return {
        e.id: (e.action, e.entity_type, e.changes, e.now)
        for e in ctx.history_svc.page(limit=1000)
    }


def _convert_all(ctx: AppContext, limit: int = 7) -> tuple[int, int]:
    converted = kept = 0
    while True:
        step = ctx.compaction_svc.step(limit)
        ctx.commit()
        converted += step.converted
        kept += step.kept
        if step.remaining == 0:
            return converted, kept


def test_everything_reads_the_same_after_conversion(ctx: AppContext, old_history):
    before = _read(ctx)
    whole = ctx.compaction_svc.remaining()
    assert whole >= 37  # 36 edits and a restore

    converted, kept = _convert_all(ctx)

    assert (converted, kept) == (whole, 0)
    assert ctx.compaction_svc.remaining() == 0
    assert _read(ctx) == before
    rows = ctx._session.query(AuditLog).filter(AuditLog.action == "update").all()
    assert rows and all(r.format == 2 and r.old_data is None for r in rows)


def test_a_converted_edit_reverts_the_same_way(ctx: AppContext, old_history):
    entry = next(
        e
        for e in ctx.history_svc.page(entity_id=old_history[3].id, limit=20)
        if e.action == "update"
    )
    plan = ctx.history_svc.plan_revert(entry.id)
    _convert_all(ctx)
    assert ctx.history_svc.plan_revert(entry.id) == plan


def test_an_entry_that_would_read_differently_is_kept_whole_and_not_retried(
    ctx: AppContext, old_history, monkeypatch
):
    target = ctx.compaction_svc._audit.whole_edits(1)[0]
    real = compaction.diff_entry
    calls = {"n": 0}

    def differs_for_one(kind, action, old, new):
        result = real(kind, action, old, new)
        # The delta's side holds only identity (no `created_at`).
        delta_side = new is not None and "created_at" not in new
        if delta_side and new.get("id") == str(target.entity_id):
            calls["n"] += 1
            return [*result, "pretend it differs"]
        return result

    monkeypatch.setattr(compaction, "diff_entry", differs_for_one)
    converted, kept = _convert_all(ctx)

    assert kept >= 1
    row = ctx._session.get(AuditLog, target.id)
    assert row.format == 3 and row.old_data is not None and row.delta is None
    assert ctx.compaction_svc.remaining() == 0  # not looked at again


def test_stopping_part_way_loses_nothing(ctx: AppContext, old_history):
    before = _read(ctx)
    total = ctx.compaction_svc.remaining()
    ctx.compaction_svc.step(10)
    ctx.commit()
    assert ctx.compaction_svc.remaining() == total - 10
    assert _read(ctx) == before  # half converted reads the same
    _convert_all(ctx)
    assert _read(ctx) == before


def test_reclaiming_gives_the_room_back(ctx: AppContext, old_history):
    _convert_all(ctx)
    before = ctx.compaction_svc.space()
    assert before is not None and before.free_bytes > 0
    ctx.compaction_svc.reclaim()
    after = ctx.compaction_svc.space()
    assert after.size_bytes < before.size_bytes
    assert after.free_bytes == 0
