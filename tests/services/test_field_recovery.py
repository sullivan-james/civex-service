"""Fields can be deleted and brought back, and history refers to them by id.

A deleted field keeps its row and every record keeps the value it held, so
restoring it is complete, not a re-creation. History entries store values by
field id, so they stay correct when a field is renamed."""

from __future__ import annotations

import uuid

import pytest

from civex.domain.audit_diff import entry_snapshots
from civex.context import AppContext
from civex.domain.exceptions import ValidationError


@pytest.fixture()
def thing(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("thing", fields=[("title", "string"), ("note", "string")])
    make_collection("study")
    return make_record("study", "thing", {"title": "a", "note": "keep me"})


def _field(ctx: AppContext, name: str):
    return next(f for f in ctx.schema_svc.get("thing").fields if f.name == name)


def _data(ctx: AppContext, record) -> dict:
    return ctx.record_svc.get(str(record.id)).data


def test_a_deleted_field_leaves_the_record_but_keeps_its_value(ctx, thing):
    ctx.schema_svc.delete_field("thing", "note")
    ctx.commit()

    record = ctx.record_svc.get(str(thing.id))
    assert "note" not in record.data
    assert record.deleted_fields and len(record.deleted_fields) == 1
    held = record.deleted_fields[0]
    assert held["name"] == "note" and held["value"] == "keep me"
    assert held["schema_name"] == "thing" and held["deleted_at"]


def test_saving_the_record_does_not_lose_a_deleted_fields_value(ctx, thing):
    ctx.schema_svc.delete_field("thing", "note")
    ctx.commit()
    ctx.record_svc.update(str(thing.id), {"title": "b"})
    ctx.commit()

    schema = ctx.schema_svc.get("thing")
    note_id = next(f.id for f in schema.deleted_fields if f.name == "note")
    ctx.schema_svc.restore_field("thing", note_id)
    ctx.commit()

    assert _data(ctx, thing) == {"title": "b", "note": "keep me"}


def test_a_new_field_can_take_the_name_of_a_deleted_one(ctx, thing):
    old = _field(ctx, "note")
    ctx.schema_svc.delete_field("thing", "note")
    ctx.schema_svc.add_field("thing", "note", "string")
    ctx.commit()

    plan = ctx.schema_svc.restore_field_plan("thing", old.id)
    assert plan.blocked_by is None
    assert plan.reason and "'note' now exists" in plan.reason
    with pytest.raises(ValidationError):
        ctx.schema_svc.restore_field("thing", old.id)

    # Once the new one is out of the way, the old one comes back.
    ctx.schema_svc.delete_field("thing", "note")
    ctx.commit()
    restored = ctx.schema_svc.restore_field("thing", old.id)
    ctx.commit()
    assert restored.id == old.id
    assert _data(ctx, thing)["note"] == "keep me"


def test_a_field_of_a_deleted_schema_waits_for_the_schema(ctx, thing):
    note = _field(ctx, "note")
    ctx.schema_svc.delete_field("thing", "note")
    ctx.schema_svc.delete("thing")
    ctx.commit()

    plan = ctx.schema_svc.restore_field_plan("thing", note.id)
    assert plan.blocked_by is not None and plan.blocked_by.kind == "schema"
    assert plan.blocked_by.name == "thing"
    assert "Restore that first" in (plan.blocked_message or "")
    with pytest.raises(ValidationError):
        ctx.schema_svc.restore_field("thing", note.id)

    ctx.schema_svc.restore("thing")
    ctx.schema_svc.restore_field("thing", note.id)
    ctx.commit()
    assert _field(ctx, "note").id == note.id


def test_restoring_a_live_or_unknown_field_is_refused(ctx, thing):
    with pytest.raises(ValidationError):
        ctx.schema_svc.restore_field("thing", _field(ctx, "note").id)
    with pytest.raises(Exception):
        ctx.schema_svc.restore_field("thing", uuid.uuid4())


def test_history_follows_a_field_through_a_rename(ctx, thing):
    ctx.record_svc.update(str(thing.id), {"title": "b", "note": "keep me"})
    ctx.schema_svc.update_field("thing", "title", new_name="heading")
    ctx.commit()

    entries = ctx.history_svc.page(entity_id=thing.id, limit=10)
    update = next(e for e in entries if e.action == "update")
    (change,) = update.changes
    assert change["field"] == "heading" and change["label"] == "Heading"
    assert (change["before"], change["after"]) == ("a", "b")
    assert change["deleted"] is None


def test_history_marks_a_value_of_a_deleted_field_and_says_where_to_restore(ctx, thing):
    ctx.record_svc.update(str(thing.id), {"title": "a", "note": "changed"})
    note = _field(ctx, "note")
    ctx.schema_svc.delete_field("thing", "note")
    ctx.commit()

    update = next(
        e
        for e in ctx.history_svc.page(entity_id=thing.id, limit=10)
        if e.action == "update"
    )
    (change,) = update.changes
    assert change["field"] == str(note.id)  # an id: a live field may reuse the name
    assert change["label"] == "Note"
    assert change["deleted"]["status"] == "deleted"
    assert change["deleted"]["schema_name"] == "thing"
    assert change["deleted"]["deleted_at"]

    ctx.schema_svc.restore_field("thing", note.id)
    ctx.commit()
    update = next(
        e
        for e in ctx.history_svc.page(entity_id=thing.id, limit=10)
        if e.action == "update"
    )
    assert update.changes[0]["field"] == "note"
    assert update.changes[0]["deleted"] is None


def test_the_field_entry_says_where_the_field_is_now(ctx, thing):
    note = _field(ctx, "note")
    ctx.schema_svc.delete_field("thing", "note")
    ctx.commit()

    def now():
        entry = next(
            e
            for e in ctx.history_svc.page(entity_id=note.id, limit=10)
            if e.action == "delete"
        )
        return entry.now

    assert now()["status"] == "deleted"
    assert now()["kind"] == "field" and now()["ref"] == str(note.id)
    assert now()["schema_name"] == "thing" and now()["name"] == "note"

    ctx.schema_svc.restore_field("thing", note.id)
    ctx.commit()
    assert now()["status"] == "live"


def test_restore_all_brings_back_deleted_fields_after_their_schema(ctx, thing):
    ctx.schema_svc.delete_field("thing", "note")
    ctx.schema_svc.delete("thing")
    ctx.commit()

    plan = ctx.history_svc.plan_restore_all()
    assert plan.fields == 1 and plan.schemas == 1 and plan.blocked == 0

    result = ctx.history_svc.restore_all()
    ctx.commit()
    assert result.blocked == 0
    assert "note" in {f.name for f in ctx.schema_svc.get("thing").fields}
    assert _data(ctx, thing)["note"] == "keep me"


def test_a_field_whose_name_was_taken_is_left_and_counted(ctx, thing):
    ctx.schema_svc.delete_field("thing", "note")
    ctx.schema_svc.add_field("thing", "note", "string")
    ctx.commit()

    plan = ctx.history_svc.plan_restore_all()
    assert plan.fields == 1 and plan.blocked == 1
    assert ctx.history_svc.restore_all().blocked == 1


def test_a_collection_entry_names_its_schemas_by_id(ctx, thing):
    ctx.dataset_svc.update("study", schemas=["thing"])
    ctx.commit()
    collection = ctx.dataset_svc.get("study")
    schema = ctx.schema_svc.get("thing")
    entries = ctx.history_svc.page(entity_id=collection.id, limit=10)
    latest = max(entries, key=lambda e: e.timestamp)
    _, new = entry_snapshots(latest.old_data, latest.new_data, latest.delta)
    assert new["schemas"] == ["thing"]
    assert new["schema_ids"] == [str(schema.id)]
