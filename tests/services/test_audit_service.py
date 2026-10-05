"""History as AuditService serves it: entries with their changes, and revert."""

from __future__ import annotations

import pytest

from civex.context import AppContext
from civex.domain.dtos import REVERT_APPLY, REVERT_CONFLICT, REVERT_SAME, REVERT_SKIPPED
from civex.domain.exceptions import ValidationError


@pytest.fixture()
def thing(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema(
        "thing", fields=[("title", "string"), ("count", "integer"), ("note", "string")]
    )
    make_collection("study")
    return make_record("study", "thing", {"title": "a", "count": 1})


def _update(ctx: AppContext, record, **values):
    current = ctx.record_svc.get(str(record.id)).data
    ctx.record_svc.update(str(record.id), {**current, **values})
    ctx.commit()


def _entries(ctx: AppContext, record, action: str):
    return [
        e
        for e in ctx.history_svc.page(entity_id=record.id, limit=100)
        if e.action == action
    ]


def _changes(entry):
    return {c["field"]: (c["before"], c["after"]) for c in entry.changes}


# --- reading ----------------------------------------------------------------


def test_an_update_lists_what_changed_with_labels_in_schema_order(
    ctx: AppContext, thing
):
    _update(ctx, thing, note="n", count=2)
    entry = _entries(ctx, thing, "update")[0]
    assert [c["field"] for c in entry.changes] == ["count", "note"]  # schema order
    assert _changes(entry) == {"count": (1, 2), "note": (None, "n")}
    assert entry.changes[0]["dtype"] == "integer"
    assert entry.changes[0]["label"]


def test_a_delete_shows_the_values_that_were_lost_by_name(ctx: AppContext, thing):
    ctx.record_svc.delete(str(thing.id))
    ctx.commit()
    entry = _entries(ctx, thing, "delete")[0]
    ids = {f.name: str(f.id) for f in ctx.schema_svc.get("thing").fields}
    # Stored by field id, shown by name.
    assert set(entry.old_data["data"]) == {ids["title"], ids["count"]}
    assert _changes(entry) == {"title": ("a", None), "count": (1, None)}


def test_a_restore_has_no_changes(ctx: AppContext, thing):
    ctx.record_svc.delete(str(thing.id))
    ctx.record_svc.restore(str(thing.id))
    ctx.commit()
    entry = _entries(ctx, thing, "restore")[0]
    assert entry.changes == []
    ids = {f.name: str(f.id) for f in ctx.schema_svc.get("thing").fields}
    assert set(entry.old_data["data"]) == {ids["title"], ids["count"]}


def test_a_snapshot_keyed_by_field_id_is_read_by_name(ctx: AppContext, thing):
    shape = ctx.schema_svc.resolver()(thing.schema_id)
    by_id = {shape.name_to_id["title"]: "a", shape.name_to_id["count"]: 1}
    old = {"id": str(thing.id), "schema_id": str(thing.schema_id), "data": by_id}
    ctx.audit_svc.log_change("delete", "record", thing.id, old, None)
    ctx.commit()
    entry = _entries(ctx, thing, "delete")[-1]
    assert _changes(entry) == {"title": ("a", None), "count": (1, None)}


def test_a_schema_change_shows_real_values(ctx: AppContext, thing):
    ctx.schema_svc.update("thing", description="about things")
    ctx.commit()
    schema = ctx.schema_svc.get("thing")
    entry = ctx.history_svc.page(entity_id=schema.id, limit=100)[0]
    assert _changes(entry)["description"] == (None, "about things")


def test_get_unknown_entry_is_not_found(ctx: AppContext):
    import uuid

    from civex.domain.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        ctx.history_svc.get(uuid.uuid4())


# --- reverting an update -------------------------------------------------------


def test_revert_puts_changed_fields_back(ctx: AppContext, thing):
    _update(ctx, thing, count=5, note="n")
    entry = _entries(ctx, thing, "update")[0]

    plan = ctx.history_svc.plan_revert(entry.id)
    assert plan.kind == "update"
    assert {f.field: f.status for f in plan.fields} == {
        "count": REVERT_APPLY,
        "note": REVERT_APPLY,
    }

    result = ctx.history_svc.revert(entry.id)
    ctx.commit()
    assert sorted(result.applied) == ["count", "note"]
    data = ctx.record_svc.get(str(thing.id)).data
    assert data["count"] == 1
    assert "note" not in data  # it was unset before, so it is unset again
    assert data["title"] == "a"


def test_a_revert_is_itself_recorded_and_can_be_reverted(ctx: AppContext, thing):
    _update(ctx, thing, count=5)
    first = _entries(ctx, thing, "update")[0]
    ctx.history_svc.revert(first.id)
    ctx.commit()
    undo = _entries(ctx, thing, "update")[0]
    assert undo.id != first.id
    assert _changes(undo) == {"count": (5, 1)}

    ctx.history_svc.revert(undo.id)
    ctx.commit()
    assert ctx.record_svc.get(str(thing.id)).data["count"] == 5


def test_only_the_chosen_fields_are_reverted(ctx: AppContext, thing):
    _update(ctx, thing, count=5, note="n")
    entry = _entries(ctx, thing, "update")[0]
    ctx.history_svc.revert(entry.id, fields=["note"])
    ctx.commit()
    data = ctx.record_svc.get(str(thing.id)).data
    assert data["count"] == 5
    assert "note" not in data


def test_a_field_not_in_the_entry_is_refused(ctx: AppContext, thing):
    _update(ctx, thing, count=5)
    entry = _entries(ctx, thing, "update")[0]
    with pytest.raises(ValidationError, match="did not change"):
        ctx.history_svc.plan_revert(entry.id, fields=["title"])


def test_a_field_edited_since_is_a_conflict_until_forced(ctx: AppContext, thing):
    _update(ctx, thing, count=5)
    entry = _entries(ctx, thing, "update")[0]
    _update(ctx, thing, count=9)

    plan = ctx.history_svc.plan_revert(entry.id)
    assert plan.has_conflicts
    assert plan.fields[0].status == REVERT_CONFLICT
    assert (plan.fields[0].current, plan.fields[0].target) == (9, 1)

    with pytest.raises(ValidationError, match="edited since"):
        ctx.history_svc.revert(entry.id)
    assert ctx.record_svc.get(str(thing.id)).data["count"] == 9

    ctx.history_svc.revert(entry.id, force=True)
    ctx.commit()
    assert ctx.record_svc.get(str(thing.id)).data["count"] == 1


def test_a_field_already_back_to_the_old_value_is_nothing_to_do(ctx: AppContext, thing):
    _update(ctx, thing, count=5)
    entry = _entries(ctx, thing, "update")[0]
    _update(ctx, thing, count=1)
    plan = ctx.history_svc.plan_revert(entry.id)
    assert plan.fields[0].status == REVERT_SAME
    assert not plan.can_apply
    with pytest.raises(ValidationError, match="Nothing to revert"):
        ctx.history_svc.revert(entry.id)


def test_a_field_since_deleted_is_skipped(ctx: AppContext, thing):
    _update(ctx, thing, note="n")
    entry = _entries(ctx, thing, "update")[0]
    ctx.schema_svc.delete_field("thing", "note")
    ctx.commit()
    plan = ctx.history_svc.plan_revert(entry.id)
    assert plan.fields[0].status == REVERT_SKIPPED
    assert "no longer exists" in plan.fields[0].reason


def test_a_file_whose_content_is_gone_is_skipped(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("doc", fields=[("scan", "file"), ("title", "string")])
    make_collection("study")
    gone = {"sha256": "b" * 64, "filename": "old.pdf", "size": 10}
    record = make_record("study", "doc", {"scan": gone, "title": "t"})
    _update(ctx, record, scan=None, title="u")
    entry = _entries(ctx, record, "update")[0]

    plan = ctx.history_svc.plan_revert(entry.id)
    by_field = {f.field: f for f in plan.fields}
    assert by_field["scan"].status == REVERT_SKIPPED
    assert "old.pdf" in by_field["scan"].reason
    assert by_field["title"].status == REVERT_APPLY

    ctx.history_svc.revert(entry.id)
    ctx.commit()
    data = ctx.record_svc.get(str(record.id)).data
    assert data["title"] == "t"
    assert not data.get("scan")


def test_a_deleted_record_must_be_restored_before_an_update_is_reverted(
    ctx: AppContext, thing
):
    _update(ctx, thing, count=5)
    entry = _entries(ctx, thing, "update")[0]
    ctx.record_svc.delete(str(thing.id))
    ctx.commit()
    plan = ctx.history_svc.plan_revert(entry.id)
    assert plan.blocked and "Restore" in plan.blocked
    with pytest.raises(ValidationError):
        ctx.history_svc.revert(entry.id)


# --- reverting a delete and a create -------------------------------------------


def test_reverting_a_delete_restores_the_record(ctx: AppContext, thing):
    ctx.record_svc.delete(str(thing.id))
    ctx.commit()
    entry = _entries(ctx, thing, "delete")[0]
    assert ctx.history_svc.plan_revert(entry.id).kind == "restore"
    ctx.history_svc.revert(entry.id)
    ctx.commit()
    assert ctx.record_svc.get(str(thing.id)).data["title"] == "a"


def test_reverting_a_delete_twice_is_blocked(ctx: AppContext, thing):
    ctx.record_svc.delete(str(thing.id))
    ctx.commit()
    entry = _entries(ctx, thing, "delete")[0]
    ctx.history_svc.revert(entry.id)
    ctx.commit()
    assert (
        ctx.history_svc.plan_revert(entry.id).blocked == "This record is not deleted."
    )


def test_reverting_a_create_deletes_the_record(ctx: AppContext, thing):
    entry = _entries(ctx, thing, "create")[0]
    assert ctx.history_svc.plan_revert(entry.id).kind == "delete"
    ctx.history_svc.revert(entry.id)
    ctx.commit()
    assert [r.id for r in ctx.record_svc.list_deleted("study")] == [thing.id]


def test_only_record_changes_can_be_reverted(ctx: AppContext, thing):
    schema = ctx.schema_svc.get("thing")
    entry = ctx.history_svc.page(entity_id=schema.id, limit=100)[0]
    plan = ctx.history_svc.plan_revert(entry.id)
    assert plan.blocked and not plan.can_apply


def test_a_restore_and_a_purge_cannot_be_reverted(ctx: AppContext, thing):
    ctx.record_svc.delete(str(thing.id))
    ctx.record_svc.restore(str(thing.id))
    ctx.commit()
    entry = _entries(ctx, thing, "restore")[0]
    assert ctx.history_svc.plan_revert(entry.id).blocked
