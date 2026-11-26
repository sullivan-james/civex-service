"""Two writers delete (or restore) the same records at once: only the one whose
UPDATE really changed a record puts it in history. Otherwise undoing one
writer's batch would also bring back what the other deleted.

The race is made deterministic by giving the second writer a stale look at
which records are live (what it read before the first one committed)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from civex.context import AppContext, build_local_context
from civex.db.models import AuditLog, Record
from civex.domain.dtos import RecordChangesDTO


@pytest.fixture()
def two(ctx: AppContext, make_schema, make_collection):
    make_schema("site", fields=[("name", "string")])
    make_collection("c")
    other = build_local_context(ctx.config)
    yield ctx, other
    other.close()


def _make(ctx: AppContext, n: int) -> list[str]:
    ids = [ctx.record_svc.add("c", "site", {"name": f"r{i}"}).id for i in range(n)]
    ctx.commit()
    return [str(i) for i in ids]


def _stale(ctx: AppContext, monkeypatch) -> None:
    """The writer still believes every record is live (it looked before the
    other writer committed)."""
    real = ctx.record_svc._records
    monkeypatch.setattr(
        real, "deleted_at_of", lambda ids: {i: None for i in ids}, raising=True
    )
    monkeypatch.setattr(
        real,
        "subtree_levels",
        lambda ids, deleted=False: [list(dict.fromkeys(ids))],
        raising=True,
    )


def _entries(ctx: AppContext, change: str, rid: str) -> int:
    ctx._session.expire_all()
    rows = ctx._session.scalars(
        select(AuditLog).where(AuditLog.entity_id == uuid.UUID(rid))
    ).all()
    return sum(1 for r in rows if r.action == change)


def _live(ctx: AppContext) -> int:
    ctx._session.expire_all()
    return len(
        ctx._session.scalars(select(Record.id).where(Record.deleted_at.is_(None))).all()
    )


def test_a_record_deleted_by_two_writers_has_one_delete_entry(two, monkeypatch):
    first, second = two
    ids = _make(first, 6)
    # first deletes 0-3 (a push), second (a stale web bulk delete) 2-5.
    first.record_svc.delete_many(ids[:4])
    first.commit()
    _stale(second, monkeypatch)
    second.record_svc.apply_changes(
        RecordChangesDTO(delete=[uuid.UUID(i) for i in ids[2:]])
    )
    second.commit()
    for rid in ids:
        assert _entries(first, "delete", rid) == 1
    assert _live(first) == 0


def test_undoing_one_batch_restores_only_its_own_records(two, monkeypatch):
    first, second = two
    ids = _make(first, 6)
    first.record_svc.delete_many(ids[:4])
    first.commit()
    _stale(second, monkeypatch)
    second.record_svc.apply_changes(
        RecordChangesDTO(delete=[uuid.UUID(i) for i in ids[2:]])
    )
    second.commit()
    events, _ = second.history_svc.events(
        where={"and": [{"field": "change", "op": "eq", "value": "delete"}]}
    )
    batches = {e.batch.id for e in events if e.batch}
    assert len(batches) == 2
    # The newest batch is the second writer's: it deleted only 4 and 5.
    newest = events[0].batch.id
    second.history_svc.revert_batch(newest, dry_run=False)
    second.commit()
    first._session.expire_all()
    back = {
        str(r)
        for r in first._session.scalars(
            select(Record.id).where(Record.deleted_at.is_(None))
        )
    }
    assert back == set(ids[4:])


def test_a_record_restored_by_two_writers_has_one_restore_entry(two):
    first, second = two
    ids = _make(first, 3)
    first.record_svc.delete_many(ids)
    first.commit()
    rows = {
        r.id: r
        for r in first.record_svc._records.restore_rows([uuid.UUID(i) for i in ids])
    }
    wanted = list(rows)
    assert first.record_svc._records.restore_many(wanted) == set(wanted)
    first.commit()
    assert second.record_svc._records.restore_many(wanted) == set()
    assert _live(first) == 3


def test_restore_set_under_the_race_counts_and_audits_what_it_changed(two, monkeypatch):
    first, second = two
    ids = _make(first, 4)
    first.record_svc.delete_many(ids)
    first.commit()
    # The second writer plans (it saw them deleted), then the first restores.
    plan = second.record_svc.plan_restore_set(ids)
    assert len(plan.coming) == 4
    done = first.record_svc.restore_set(ids)
    first.commit()
    assert (done.restored, done.came_back) == (4, 4)
    monkeypatch.setattr(
        second.record_svc, "plan_restore_set", lambda *a, **k: plan, raising=True
    )
    late = second.record_svc.restore_set(ids)
    second.commit()
    assert (late.restored, late.came_back) == (0, 0)
    for rid in ids:
        assert _entries(first, "restore", rid) == 1
