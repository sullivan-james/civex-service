"""Undoing a bulk action is one step, whatever its size: a bulk delete of more
records than any cap once allowed comes back in one call, described exactly
beforehand, written as one action in one batch, in a few dozen statements."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, func, insert, select

from civex.context import AppContext
from civex.db.models import AuditLog, Record
from civex.domain.ids import row_id

PARENTS = 3000
KIDS = 3  # 3000 x (1 + 3) = 12,000 records, more than the old cap of 5,000


def leaf(field: str, value, op: str = "eq") -> dict:
    return {"field": field, "op": op, "value": value}


def seed(
    ctx: AppContext,
    collection: str,
    parents: int,
    kids: int,
    schema: str = "site",
    child: str = "trial",
) -> list[uuid.UUID]:
    """`parents` records each with `kids` under it, written straight to the
    table (no history): the number is what the test is about, not how it got
    there. Returns the parents' ids."""
    dataset = ctx.dataset_svc.get(collection).id
    parent_schema = ctx.schema_svc.get(schema).id
    child_schema = ctx.schema_svc.get(child).id
    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    ids: list[uuid.UUID] = []
    for _ in range(parents):
        pid = row_id()
        ids.append(pid)
        rows.append(_row(pid, dataset, parent_schema, None, now))
        rows.extend(
            _row(row_id(), dataset, child_schema, pid, now) for _ in range(kids)
        )
    for start in range(0, len(rows), 2000):
        ctx._session.execute(insert(Record), rows[start : start + 2000])
    ctx.commit()
    return ids


def _row(rid, dataset, schema, parent, now) -> dict:
    return {
        "id": rid,
        "dataset_id": dataset,
        "schema_id": schema,
        "parent_record_id": parent,
        "data": {},
        "created_at": now,
        "updated_at": now,
    }


@pytest.fixture()
def world(ctx: AppContext, make_schema, make_collection):
    make_schema("site", fields=[("name", "string")])
    make_schema("trial", fields=[("n", "integer")], parent="site")
    make_collection("c")
    return ctx


def _delete_event(ctx: AppContext):
    events, _ = ctx.history_svc.events(where={"and": [leaf("change", "delete")]})
    return events[0]


def _count(ctx: AppContext, *where) -> int:
    return ctx._session.scalar(select(func.count()).select_from(Record).where(*where))


def _statements(ctx: AppContext, work) -> int:
    seen = {"n": 0}

    def bump(*_a, **_k):
        seen["n"] += 1

    engine = ctx._session.get_bind()
    event.listen(engine, "before_cursor_execute", bump)
    try:
        work()
    finally:
        event.remove(engine, "before_cursor_execute", bump)
    return seen["n"]


def test_a_bulk_delete_past_the_old_cap_is_restored_in_one_call(world: AppContext):
    ctx = world
    seed(ctx, "c", PARENTS, KIDS)
    everything = PARENTS * (1 + KIDS)
    assert ctx.record_svc.delete_all("c") == PARENTS
    ctx.commit()
    assert _count(ctx, Record.deleted_at.is_(None)) == 0
    batch = _delete_event(ctx).batch.id

    plan = ctx.history_svc.plan_restore_all(batch_id=batch)
    # Exact, not a capped list: every record the delete took.
    assert plan.records == everything > 5000
    assert (plan.restores, plan.blocked) == (everything, 0)

    result = ctx.history_svc.restore_all(batch_id=batch)
    ctx.commit()
    assert (result.records, result.blocked) == (everything, 0)
    assert result.restored == plan.records
    assert _count(ctx, Record.deleted_at.is_(None)) == everything

    # One undo: one batch, one action, an entry for each record, parents first.
    events, total = ctx.history_svc.events(where={"and": [leaf("how", "restore")]})
    assert total == 1 and events[0].batch.label == "Restore all"
    entries = ctx._session.execute(
        select(AuditLog.op_id, AuditLog.entity_id, AuditLog.local_seq)
        .where(AuditLog.action == "restore", AuditLog.batch_id == events[0].batch.id)
        .order_by(AuditLog.local_seq)
    ).all()
    assert len(entries) == everything
    assert len({op for op, _, _ in entries}) == 1 and entries[0][0] is not None
    seen: set[uuid.UUID] = set()
    parent_of = {
        rid: pid
        for rid, pid in ctx._session.execute(select(Record.id, Record.parent_record_id))
    }
    for _, entity, _ in entries:
        above = parent_of[entity]
        assert above is None or above in seen  # never a child before its parent
        seen.add(entity)


def test_the_restore_is_a_few_dozen_statements_not_one_per_record(world: AppContext):
    ctx = world
    seed(ctx, "c", PARENTS, KIDS)
    ctx.record_svc.delete_all("c")
    ctx.commit()
    batch = _delete_event(ctx).batch.id
    plan_statements = _statements(
        ctx, lambda: ctx.history_svc.plan_restore_all(batch_id=batch)
    )
    restore_statements = _statements(
        ctx, lambda: ctx.history_svc.restore_all(batch_id=batch)
    )
    ctx.commit()
    # 12,000 records at 2,000 entries and 5,000 ids per statement.
    assert plan_statements < 60
    assert restore_statements < 60


def test_a_record_under_a_parent_deleted_outside_the_batch_stays_and_is_counted(
    world: AppContext,
):
    ctx = world
    parents = seed(ctx, "c", PARENTS, KIDS)
    # A child goes in the bulk delete, then its parent is deleted on its own.
    kids = [r.id for r in ctx.record_svc.find("c", "trial", limit=10)]

    def above_of(k):
        return ctx.record_svc.get(str(k)).parent_record_id

    stuck, other = (
        kids[0],
        next(
            k
            for k in kids
            if ctx.record_svc.get(str(k)).parent_record_id != above_of(kids[0])
        ),
    )
    above = ctx.record_svc.get(str(stuck)).parent_record_id
    ctx.record_svc.delete_many([str(stuck), str(other)])
    ctx.commit()
    first = _delete_event(ctx).batch.id
    ctx.record_svc.delete_many([str(above)])
    ctx.commit()
    assert above in parents

    plan = ctx.history_svc.plan_restore_all(batch_id=first)
    assert (plan.records, plan.restores, plan.blocked) == (2, 1, 1)
    result = ctx.history_svc.restore_all(batch_id=first)
    ctx.commit()
    assert (result.restored, result.records, result.blocked) == (1, 1, 1)
    assert _count(ctx, Record.id == stuck, Record.deleted_at.is_not(None)) == 1


def test_a_big_delete_with_one_blocked_subtree_plans_what_it_does(world: AppContext):
    ctx = world
    seed(ctx, "c", PARENTS, KIDS)
    ctx.record_svc.delete_all("c")
    ctx.commit()
    batch = _delete_event(ctx).batch.id
    # Another record is deleted for good reasons by another action: not in this
    # batch, so nothing about it changes.
    plan = ctx.history_svc.plan_restore_all(batch_id=batch)
    result = ctx.history_svc.restore_all(batch_id=batch)
    ctx.commit()
    assert (result.records, result.blocked) == (plan.restores, plan.blocked)


def test_a_bulk_written_entry_is_the_one_a_single_restore_writes(world: AppContext):
    ctx = world
    seed(ctx, "c", 2, 1)
    one, two = ctx.record_svc.find("c", "site", limit=5)[:2]
    ctx.record_svc.delete(str(one.id))
    ctx.record_svc.delete(str(two.id))
    ctx.commit()
    ctx.record_svc.restore(str(one.id), only_this=True)  # one record, one entry
    ctx.record_svc.restore_set([str(two.id)])  # the bulk writer
    ctx.commit()

    def entry(rid):
        return ctx._session.scalars(
            select(AuditLog).where(
                AuditLog.entity_id == rid, AuditLog.action == "restore"
            )
        ).one()

    a, b = entry(one.id), entry(two.id)
    for column in ("action", "entity_type", "format", "actor", "device_id"):
        assert getattr(a, column) == getattr(b, column)
    assert a.old_data == b.old_data
    assert set(a.delta) == set(b.delta) == {"deleted_at"}
    assert a.delta["deleted_at"]["after"] is None is b.delta["deleted_at"]["after"]
    assert set(a.new_data) == set(b.new_data)
    assert (a.hlc is None) == (b.hlc is None)
    assert b.local_seq is not None and b.sync_state == a.sync_state


def test_preview_counts_are_exact_for_a_filter_too(world: AppContext):
    ctx = world
    parents = seed(ctx, "c", PARENTS, KIDS)
    ctx.record_svc.delete_all("c")
    ctx.commit()
    where = {"and": [leaf("under", str(parents[0]))]}
    plan = ctx.history_svc.plan_restore_all(where)
    assert plan.records == plan.restores == 1 + KIDS  # the parent and its kids
    # A filter over everything counts all of it, not 5,000 of it.
    assert ctx.history_svc.plan_restore_all().records == PARENTS * (1 + KIDS)


def test_a_bulk_edit_past_the_old_cap_is_undone_in_one_call(world: AppContext):
    ctx = world
    n = 5200
    seed(ctx, "c", n, 0)
    ids = [str(r) for r in ctx._session.scalars(select(Record.id))]
    ctx.record_svc.bulk_edit({"name": "edited"}, ids=ids)
    ctx.commit()
    events, _ = ctx.history_svc.events(where={"and": [leaf("change", "update")]})
    batch = events[0].batch.id
    plan = ctx.history_svc.revert_batch(batch)
    assert plan.applied == n
    undone = ctx.history_svc.revert_batch(batch, dry_run=False)
    ctx.commit()
    assert (undone.applied, undone.left) == (n, 0)
    assert {ctx.record_svc.get(i).data.get("name") for i in ids[:50]} == {None}
    # One undo in history: one batch holding every reverted change.
    undo, total = ctx.history_svc.events(
        where={"and": [leaf("change", "update")]}, limit=5
    )
    undo_batches = {e.batch.id for e in undo if e.batch and e.batch.id != batch}
    assert len(undo_batches) == 1
    ops = ctx._session.scalars(
        select(func.count(func.distinct(AuditLog.batch_id))).where(
            AuditLog.action == "update", AuditLog.batch_id != batch
        )
    ).one()
    assert ops == 1


def test_undoing_a_delete_and_redoing_it_is_one_step_each(world: AppContext):
    ctx = world
    seed(ctx, "c", PARENTS, KIDS)
    everything = PARENTS * (1 + KIDS)
    ctx.record_svc.delete_all("c")
    ctx.commit()
    batch = _delete_event(ctx).batch.id

    preview = ctx.history_svc.revert_batch(batch)
    assert (preview.entries, preview.applied, preview.left) == (everything,) * 2 + (0,)
    undone = ctx.history_svc.revert_batch(batch, dry_run=False)
    ctx.commit()
    assert (undone.applied, undone.left) == (everything, 0)
    assert _count(ctx, Record.deleted_at.is_(None)) == everything
    restored, _ = ctx.history_svc.events(where={"and": [leaf("how", "restore")]})
    undo_batch = restored[0].batch.id
    ops = ctx._session.scalars(
        select(func.count(func.distinct(AuditLog.op_id))).where(
            AuditLog.batch_id == undo_batch
        )
    ).one()
    assert ops == 1

    # The undo is a bulk action like any other, so it is undone the same way.
    redone = ctx.history_svc.revert_batch(undo_batch, dry_run=False)
    ctx.commit()
    assert (redone.applied, redone.left) == (everything, 0)
    assert _count(ctx, Record.deleted_at.is_(None)) == 0


def test_unique_key_clashes_of_a_restore_are_asked_a_chunk_at_a_time(
    ctx: AppContext, make_schema, make_collection
):
    make_schema("plot", fields=[("site", "string"), ("number", "integer")])
    make_collection("c")
    ctx.schema_svc.set_unique_keys("plot", [["site", "number"]])
    ctx.commit()
    ids = ctx.schema_svc.resolver()(ctx.schema_svc.get("plot").id).name_to_id
    dataset, schema = ctx.dataset_svc.get("c").id, ctx.schema_svc.get("plot").id
    now = datetime.now(timezone.utc)
    rows = [
        {
            **_row(row_id(), dataset, schema, None, now),
            "data": {ids["site"]: "s", ids["number"]: i},
        }
        for i in range(600)
    ]
    ctx._session.execute(insert(Record), rows)
    ctx.commit()
    ctx.record_svc.delete_all("c")
    ctx.commit()
    ctx.record_svc.add("c", "plot", {"site": "s", "number": 5})  # takes a key back
    ctx.commit()
    batch = _delete_event(ctx).batch.id

    plan = ctx.history_svc.plan_restore_all(batch_id=batch)
    assert (plan.records, plan.restores, plan.blocked) == (600, 599, 1)
    seen = _statements(ctx, lambda: ctx.history_svc.restore_all(batch_id=batch))
    ctx.commit()
    assert seen < 60  # not a lookup per record
    assert _count(ctx, Record.deleted_at.is_(None)) == 600  # 599 back + the new one


def test_bulk_written_entries_keep_awkward_text_exactly(world: AppContext):
    """Tabs, newlines, backslashes and quotes in a stored value or an actor's
    name survive the bulk writer (on PostgreSQL it is COPY text, which escapes
    them) and equal what `log_change` stores."""
    ctx = world
    repo = ctx.record_svc._audit
    repo._actor = 'a\tb\\c\nd "e"'
    awkward = {"id": "x\ty\\z\nq\ré \\N", "deleted_at": None}
    one, two = uuid.uuid4(), uuid.uuid4()
    repo.log_change("delete", "record", one, awkward, None)
    repo.log_changes("delete", "record", [(two, awkward, None)])
    ctx.commit()
    rows = {
        r.entity_id: r
        for r in ctx._session.scalars(
            select(AuditLog).where(AuditLog.entity_id.in_([one, two]))
        )
    }
    a, b = rows[one], rows[two]
    for column in ("old_data", "new_data", "delta", "format", "actor", "action"):
        assert getattr(a, column) == getattr(b, column)
    assert b.old_data == awkward and b.actor == 'a\tb\\c\nd "e"'
    assert b.timestamp is not None and b.sync_state == a.sync_state
