"""A push and a person's bulk delete meet on the same records, in either order:
each record has the one delete a person would expect, and undoing a delete
(whole batch or single entry) never brings back what another change deleted
too."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from civex.db.models import Record
from civex.domain.exceptions import ValidationError

from .test_bulk_changes import Flow
from .test_bulk_push import send
from .test_delete_race_helpers import deletes, live_ids


def start(project, n: int):
    ctx = project("authority")
    f = Flow(project)
    ids = f.many(n)
    send(ctx, f.structure + f.take())
    return ctx, f, ids


def web_delete(ctx, ids):
    ctx.record_svc.delete_many([str(i) for i in ids], force=True)
    ctx.commit()


def batches(ctx) -> list[uuid.UUID]:
    events, _ = ctx.history_svc.events(
        where={"and": [{"field": "change", "op": "eq", "value": "delete"}]}
    )
    seen: list[uuid.UUID] = []
    for e in events:
        if e.batch and e.batch.id not in seen:
            seen.append(e.batch.id)
    return seen


def trees(f, ctx, n: int) -> list[uuid.UUID]:
    """n parents each with a child, on the authority; returns every id."""
    out: list[uuid.UUID] = []
    for i in range(n):
        parent = f.make("mine", "encounter", {"site": f"p{i}", "depth": 1.0})
        child = f.make(
            "mine", "recording", {"label": f"c{i}", "must": "x"}, str(parent)
        )
        out += [parent, child]
    send(ctx, f.take())
    return out


def test_a_single_record_push_after_a_web_delete_writes_no_second_entry(project):
    ctx, f, ids = start(project, 1)
    pushed = f.deleted(ids)
    web_delete(ctx, ids)
    send(ctx, pushed)
    assert len(deletes(ctx, ids[0])) == 1
    [entry] = deletes(ctx, ids[0])
    ctx.history_svc.revert(str(entry))
    ctx.commit()
    assert live_ids(ctx) == set(ids)  # the one delete there is undoes as ever


@pytest.mark.parametrize("web_first", [True, False])
def test_undo_never_restores_what_another_change_deleted(project, web_first):
    """A pushed action (a parent and its child) meets a web delete of the same
    trees: in one order the push writes a second delete for each record."""
    ctx, f, _ = start(project, 0)
    ids = trees(f, ctx, 3)
    roots = ids[::2]
    pushed = f.deleted(roots)
    if web_first:
        web_delete(ctx, roots)
        send(ctx, pushed)
    else:
        send(ctx, pushed)
        web_delete(ctx, roots)  # a no-op: already deleted
    assert live_ids(ctx) == set()
    expected = 2 if web_first else 1
    assert all(len(deletes(ctx, i)) == expected for i in ids)
    lefts: list[int] = []
    for batch in batches(ctx):
        done = ctx.history_svc.revert_batch(batch, dry_run=False)
        ctx.commit()
        if web_first:  # neither undoes what the other also deleted
            assert live_ids(ctx) == set(), (done.applied, done.reasons)
            assert done.applied == 0
            lefts.append(done.left)
            assert all("another" in r["reason"] for r in done.reasons)
    if web_first:
        assert max(lefts) == len(ids)  # the web batch names every record it left
        for rid in ids:
            for entry in deletes(ctx, rid):
                with pytest.raises(ValidationError):
                    ctx.history_svc.revert(str(entry))
        assert live_ids(ctx) == set()
    else:
        assert live_ids(ctx) == set(ids)


def test_a_delete_with_no_other_still_undoes(project):
    ctx, f, ids = start(project, 4)
    web_delete(ctx, ids)
    [batch] = batches(ctx)
    done = ctx.history_svc.revert_batch(batch, dry_run=False)
    ctx.commit()
    assert done.left == 0 and live_ids(ctx) == set(ids)


def test_a_parent_undone_leaves_a_child_deleted_first(project):
    ctx, f, _ = start(project, 0)
    parent = f.make("mine", "encounter", {"site": "p", "depth": 1.0})
    child = f.make("mine", "recording", {"label": "c", "must": "x"}, parent=str(parent))
    send(ctx, f.take())
    ctx.record_svc.delete_many([str(child)], force=True)
    ctx.commit()
    ctx.record_svc.delete_many([str(parent)], force=True)
    ctx.commit()
    [entry] = deletes(ctx, parent)
    ctx.history_svc.revert(str(entry))
    ctx.commit()
    assert live_ids(ctx) == {parent}
    assert ctx._session.scalar(select(func.count()).select_from(Record)) == 2
