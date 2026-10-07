"""A live record under a deleted one is out of sight. It can be found (the
record page, `orphans`, `civex doctor`) and put back in place by bringing back
only what it sits under."""

from __future__ import annotations

import pytest
from sqlalchemy import update

from civex.db.models import Record
from civex.domain.exceptions import ValidationError


@pytest.fixture()
def tree(ctx, make_schema, make_collection, make_record):
    make_schema("encounter", fields=[("site", "string")])
    make_schema("recording", fields=[("label", "string")], parent="encounter")
    make_schema("selection", fields=[("n", "integer")], parent="recording")
    make_collection("survey")
    enc = make_record("survey", "encounter", {"site": "S"})
    rec = make_record(
        "survey", "recording", {"label": "R"}, parent_record_id=str(enc.id)
    )
    sels = [
        make_record("survey", "selection", {"n": i}, parent_record_id=str(rec.id))
        for i in range(3)
    ]
    ctx.commit()
    return enc, rec, sels


def _orphan(ctx, rec, sel):
    """What once happened: the recording deleted with its selections, then one
    selection brought back by itself (before that was refused)."""
    ctx.record_svc.delete(str(rec.id))
    ctx.commit()
    ctx._session.execute(
        update(Record).where(Record.id == sel.id).values(deleted_at=None)
    )
    ctx.commit()


def test_a_record_under_a_deleted_one_is_found(ctx, tree):
    _, rec, sels = tree
    assert ctx.record_svc.orphans() == ([], 0)
    _orphan(ctx, rec, sels[0])

    (found,), total = ctx.record_svc.orphans()
    assert total == 1 and found.record.id == sels[0].id
    assert [a.id for a in found.above] == [rec.id]
    assert [a.id for a in ctx.record_svc.deleted_above(str(sels[0].id))] == [rec.id]
    assert ctx.record_svc.deleted_above(str(sels[1].id)) == []  # itself deleted


def test_bringing_back_what_it_sits_under_leaves_the_rest_deleted(ctx, tree):
    _, rec, sels = tree
    _orphan(ctx, rec, sels[0])

    restored = ctx.record_svc.restore_above(str(sels[0].id))
    ctx.commit()

    assert [r.id for r in restored] == [rec.id]
    assert ctx.record_svc.orphans() == ([], 0)
    # Its siblings were deleted with the recording and stay deleted.
    sibling = ctx._session.get(Record, sels[1].id)
    assert sibling.deleted_at is not None
    entry = ctx.history_svc.page(entity_id=rec.id, limit=1)[0]
    assert entry.action == "restore"


def test_nothing_to_bring_back_is_refused(ctx, tree):
    _, _, sels = tree
    with pytest.raises(ValidationError, match="Nothing it sits under is deleted"):
        ctx.record_svc.restore_above(str(sels[0].id))
