"""Restoring from Recently Deleted: a record can't come back while something
above it is still deleted, and only what was deleted *with* a thing returns."""

from __future__ import annotations

import pytest

from civex.context import AppContext
from civex.domain.exceptions import ValidationError


@pytest.fixture()
def tree(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("encounter", fields=[("site", "string")])
    make_schema("recording", fields=[("rate", "integer")], parent="encounter")
    make_collection("humpback")
    enc = make_record("humpback", "encounter", {"site": "Stellwagen"})
    rec1 = make_record(
        "humpback", "recording", {"rate": 96}, parent_record_id=str(enc.id)
    )
    rec2 = make_record(
        "humpback", "recording", {"rate": 48}, parent_record_id=str(enc.id)
    )
    return {"enc": enc, "rec1": rec1, "rec2": rec2}


def _live(ctx: AppContext, record) -> bool:
    return any(r.id == record.id for r in ctx.record_svc.list_deleted()) is False


# --- a record can't come back inside something deleted ----------------------


def test_a_record_in_a_deleted_collection_is_blocked_by_the_collection(
    ctx: AppContext, tree
):
    ctx.dataset_svc.delete("humpback")
    ctx.commit()

    plan = ctx.record_svc.restore_plan(str(tree["rec1"].id))
    assert plan.blocked_by is not None
    assert (plan.blocked_by.kind, plan.blocked_by.name) == ("collection", "humpback")
    assert "collection 'humpback', which is deleted" in plan.blocked_message
    with pytest.raises(ValidationError, match="Restore that first"):
        ctx.record_svc.restore(str(tree["rec1"].id))
    assert not _live(ctx, tree["rec1"])


def test_a_record_of_a_deleted_schema_is_blocked_by_the_schema(ctx: AppContext, tree):
    ctx.schema_svc.delete("recording")
    ctx.commit()
    plan = ctx.record_svc.restore_plan(str(tree["rec1"].id))
    assert (plan.blocked_by.kind, plan.blocked_by.name) == ("schema", "recording")


def test_a_child_of_a_deleted_parent_is_blocked_by_the_topmost_deleted_parent(
    ctx: AppContext, tree
):
    ctx.record_svc.delete(str(tree["enc"].id))  # takes both recordings with it
    ctx.commit()

    plan = ctx.record_svc.restore_plan(str(tree["rec1"].id))
    assert plan.blocked_by is not None
    assert plan.blocked_by.kind == "record"
    assert plan.blocked_by.id == tree["enc"].id
    assert plan.blocked_by.name == "Stellwagen"
    with pytest.raises(ValidationError, match="is under the record 'Stellwagen'"):
        ctx.record_svc.restore(str(tree["rec1"].id))


def test_restoring_the_blocker_unblocks_and_brings_the_group_back(
    ctx: AppContext, tree
):
    ctx.dataset_svc.delete("humpback")
    ctx.commit()
    ctx.dataset_svc.restore("humpback")
    ctx.commit()
    # The whole group came back with the collection; nothing is left to restore.
    assert ctx.record_svc.list_deleted() == []
    assert ctx.record_svc.get(str(tree["rec1"].id)).data["rate"] == 96


def test_a_free_record_plan_says_where_it_will_be(ctx: AppContext, tree):
    ctx.record_svc.delete(str(tree["rec1"].id))
    ctx.commit()
    plan = ctx.record_svc.restore_plan(str(tree["rec1"].id))
    assert plan.can_restore
    assert (plan.records, plan.collection) == (1, "humpback")
    ctx.record_svc.restore(str(tree["rec1"].id))
    ctx.commit()
    assert ctx.record_svc.get(str(tree["rec1"].id)).dataset_name == "humpback"


# --- only what was deleted with a thing comes back --------------------------


def test_restoring_a_collection_leaves_records_deleted_earlier_deleted(
    ctx: AppContext, tree
):
    ctx.record_svc.delete(str(tree["rec2"].id))  # on its own, first
    ctx.commit()
    ctx.dataset_svc.delete("humpback")
    ctx.commit()

    plan = ctx.dataset_svc.restore_plan("humpback")
    assert plan.records == 2  # the encounter and rec1, not rec2

    ctx.dataset_svc.restore("humpback")
    ctx.commit()
    assert [r.id for r in ctx.record_svc.list_deleted()] == [tree["rec2"].id]
    # ...and it can now be restored by itself.
    assert ctx.record_svc.restore_plan(str(tree["rec2"].id)).can_restore


def test_restoring_a_schema_leaves_records_deleted_earlier_deleted(
    ctx: AppContext, tree
):
    ctx.record_svc.delete(str(tree["rec2"].id))
    ctx.commit()
    ctx.schema_svc.delete("recording")
    ctx.commit()

    assert ctx.schema_svc.restore_plan("recording").records == 1  # rec1 only
    ctx.schema_svc.restore("recording")
    ctx.commit()
    assert [r.id for r in ctx.record_svc.list_deleted()] == [tree["rec2"].id]


def test_restoring_a_record_leaves_a_child_deleted_earlier_deleted(
    ctx: AppContext, tree
):
    ctx.record_svc.delete(str(tree["rec1"].id))  # the child, on its own
    ctx.commit()
    ctx.record_svc.delete(str(tree["enc"].id))  # then the parent (and rec2)
    ctx.commit()

    plan = ctx.record_svc.restore_plan(str(tree["enc"].id))
    assert plan.records == 2  # the encounter and rec2

    ctx.record_svc.restore(str(tree["enc"].id))
    ctx.commit()
    assert [r.id for r in ctx.record_svc.list_deleted()] == [tree["rec1"].id]


# --- undoing a delete from history follows the same rules -------------------


def test_reverting_a_delete_is_blocked_the_same_way_and_names_the_blocker(
    ctx: AppContext, tree
):
    ctx.record_svc.delete(str(tree["rec1"].id))
    ctx.commit()
    entry = ctx.history_svc.page(entity_id=tree["rec1"].id, action="delete")[0]
    ctx.dataset_svc.delete("humpback")
    ctx.commit()

    plan = ctx.history_svc.plan_revert(entry.id)
    assert plan.blocked and "collection 'humpback'" in plan.blocked
    assert plan.blocker is not None and plan.blocker.kind == "collection"
    assert not plan.can_apply
    with pytest.raises(ValidationError):
        ctx.history_svc.revert(entry.id)
