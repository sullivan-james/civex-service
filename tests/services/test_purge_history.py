"""Permanently deleting a record deletes all history about it and leaves one
tombstone: that it happened, which record, and when. Never what it held."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from civex.context import AppContext
from civex.db.models import AuditBatch
from civex.domain.dtos import RetentionCutoffs


@pytest.fixture()
def survey(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("encounter", fields=[("site", "string")])
    make_schema("recording", fields=[("label", "string")], parent="encounter")
    make_collection("humpback")
    enc = make_record("humpback", "encounter", {"site": "Secret-Site"})
    rec = make_record(
        "humpback", "recording", {"label": "Secret-Label"}, parent_record_id=str(enc.id)
    )
    keep = make_record("humpback", "encounter", {"site": "Kept-Site"})
    ctx.record_svc.update(str(rec.id), {"label": "Secret-Label-2"})
    ctx.commit()
    return {"enc": enc, "rec": rec, "keep": keep}


def _history(ctx: AppContext, record_id):
    return ctx.history_svc.page(entity_id=record_id, limit=100)


def _holds(ctx: AppContext, text: str) -> bool:
    return ctx.history_svc.events(search=text, limit=5)[1] > 0


def _assert_only_a_tombstone(entries):
    assert len(entries) == 1, [e.action for e in entries]
    stone = entries[0]
    assert (stone.action, stone.new_data) == ("purge", None)
    assert stone.old_data["tombstone"] is True
    assert "data" not in stone.old_data  # nothing it held
    assert stone.changes == []
    return stone


def test_purging_a_record_leaves_one_tombstone_and_nothing_it_held(
    ctx: AppContext, survey
):
    assert len(_history(ctx, survey["rec"].id)) == 2  # create, update
    assert _holds(ctx, "Secret-Label")
    ctx.record_svc.delete(str(survey["rec"].id))
    ctx.record_svc.purge(str(survey["rec"].id))
    ctx.commit()

    stone = _assert_only_a_tombstone(_history(ctx, survey["rec"].id))
    assert not _holds(ctx, "Secret-Label") and not _holds(ctx, "Secret-Label-2")
    # Who it was and where it sat survive; what it held does not.
    assert stone.old_data["id"] == str(survey["rec"].id)
    assert stone.old_data["schema_id"] and stone.old_data["dataset_id"]
    assert stone.now == {"kind": "record", "status": "gone", "schema_name": "recording"}


def test_other_records_history_is_untouched(ctx: AppContext, survey):
    ctx.record_svc.delete(str(survey["rec"].id))
    ctx.record_svc.purge(str(survey["rec"].id))
    ctx.commit()
    assert _holds(ctx, "Kept-Site")
    kept = _history(ctx, survey["keep"].id)
    assert kept[0].new_data["data"] and "tombstone" not in kept[0].new_data


def test_purging_a_tree_leaves_a_tombstone_for_each_record(ctx: AppContext, survey):
    ctx.record_svc.delete(str(survey["enc"].id))
    ctx.record_svc.purge(str(survey["enc"].id))
    ctx.commit()
    _assert_only_a_tombstone(_history(ctx, survey["enc"].id))
    _assert_only_a_tombstone(_history(ctx, survey["rec"].id))
    assert not _holds(ctx, "Secret-Site")
    # The tombstones are one event, and the batch that deleted them is gone.
    purges, _ = ctx.history_svc.events(
        where={"and": [{"field": "change", "op": "eq", "value": "purge"}]}
    )
    assert [e.count for e in purges] == [2]
    assert (
        ctx._session.query(AuditBatch).filter(AuditBatch.kind == "delete").count() == 0
    )


def test_purging_a_collection_removes_its_records_history_and_it_is_the_tombstone(
    ctx: AppContext, survey
):
    ctx.dataset_svc.delete("humpback")
    ctx.dataset_svc.purge("humpback")
    ctx.commit()
    for key in ("enc", "rec", "keep"):
        assert _history(ctx, survey[key].id) == []  # nothing: the collection says it
    assert not _holds(ctx, "Kept-Site")
    stones = [
        e
        for e in ctx.history_svc.page(entity_type="dataset", limit=50)
        if e.action == "purge"
    ]
    assert [s.old_data["name"] for s in stones] == ["humpback"]


def test_purging_a_schema_removes_its_records_history_but_not_other_schemas(
    ctx: AppContext, survey
):
    ctx.schema_svc.delete("recording")
    ctx.schema_svc.purge("recording")
    ctx.commit()
    assert _history(ctx, survey["rec"].id) == []
    assert _history(ctx, survey["enc"].id)[0].new_data["data"]  # a different schema


def test_a_clean_up_by_age_leaves_tombstones_as_it_purges(ctx: AppContext, survey):
    ctx.record_svc.delete(str(survey["rec"].id))
    ctx.commit()
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    ctx.retention_svc.run(RetentionCutoffs(deleted_before=tomorrow), dry_run=False)
    ctx.commit()
    _assert_only_a_tombstone(_history(ctx, survey["rec"].id))
    assert not _holds(ctx, "Secret-Label")


def test_history_left_by_an_earlier_purge_is_deleted_down_to_a_tombstone(
    ctx: AppContext, survey
):
    # What purging used to leave: entries about a record that no longer exists,
    # still holding its values.
    ghost = uuid.uuid4()
    snapshot = {
        "id": str(ghost),
        "schema_id": str(survey["rec"].schema_id),
        "dataset_id": str(survey["rec"].dataset_id),
        "data": {"label": "Old-Secret"},
    }
    ctx.audit_svc.log_change("create", "record", ghost, None, snapshot)
    ctx.audit_svc.log_change("update", "record", ghost, snapshot, snapshot)
    ctx.audit_svc.log_change("purge", "record", ghost, snapshot, None)
    # A record with no purge entry at all (its row went some other way).
    stray = uuid.uuid4()
    ctx.audit_svc.log_change(
        "update",
        "record",
        stray,
        {**snapshot, "id": str(stray)},
        {**snapshot, "id": str(stray)},
    )
    ctx.commit()
    assert _holds(ctx, "Old-Secret")

    assert ctx.retention_svc.forget_purged(dry_run=True) == 4
    assert _holds(ctx, "Old-Secret")  # counting changes nothing
    assert ctx.retention_svc.forget_purged(dry_run=False) == 4
    ctx.commit()
    _assert_only_a_tombstone(_history(ctx, ghost))
    stone = _assert_only_a_tombstone(_history(ctx, stray))
    assert stone.old_data["schema_id"] == snapshot["schema_id"]
    assert not _holds(ctx, "Old-Secret")
    # Done once is done: nothing left, and no second tombstone.
    assert ctx.retention_svc.forget_purged(dry_run=False) == 0
    assert len(_history(ctx, ghost)) == 1
    # A record that exists is never touched.
    assert _history(ctx, survey["keep"].id)[0].new_data["data"]
