"""Soft-delete/restore/purge behaviour for schemas, collections and records,
including the cascades documented on SchemaRepository.delete/restore and
DatasetRepository.delete/restore.
"""

from __future__ import annotations

import pytest

from civex.context import AppContext
from civex.domain.exceptions import NotFoundError, ValidationError


# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------


def test_schema_delete_is_soft_and_excluded_from_list_all(ctx: AppContext, make_schema):
    make_schema("animal")
    ctx.schema_svc.delete("animal")
    ctx.commit()

    assert "animal" not in {s.name for s in ctx.schema_svc.list_all()}
    with pytest.raises(NotFoundError):
        ctx.schema_svc.get("animal")


def test_schema_delete_cascades_soft_delete_to_its_records(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("animal")
    make_collection("zoo")
    record = make_record("zoo", "animal", {})

    ctx.schema_svc.delete("animal")
    ctx.commit()

    assert ctx.record_svc.find("zoo") == []
    deleted = ctx.record_svc.list_deleted()
    assert [r.id for r in deleted] == [record.id]


def test_schema_restore_brings_back_schema_and_cascaded_records(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("animal")
    make_collection("zoo")
    record = make_record("zoo", "animal", {})
    ctx.schema_svc.delete("animal")
    ctx.commit()

    restored = ctx.schema_svc.restore("animal")
    ctx.commit()

    assert restored.deleted_at is None
    assert {r.id for r in ctx.record_svc.find("zoo")} == {record.id}


def test_schema_restore_requires_a_deleted_schema(ctx: AppContext, make_schema):
    make_schema("animal")
    with pytest.raises(ValidationError):
        ctx.schema_svc.restore("animal")


def test_schema_purge_requires_deleted_first(ctx: AppContext, make_schema):
    make_schema("animal")
    with pytest.raises(ValidationError):
        ctx.schema_svc.purge("animal")


def test_schema_purge_removes_permanently_and_cascades_records(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("animal")
    make_collection("zoo")
    make_record("zoo", "animal", {})
    ctx.schema_svc.delete("animal")
    ctx.commit()

    ctx.schema_svc.purge("animal")
    ctx.commit()

    assert ctx.schema_svc.list_deleted() == []
    assert ctx.record_svc.list_deleted() == []
    with pytest.raises(NotFoundError):
        ctx.schema_svc.restore("animal")


def test_schema_purge_blocked_by_live_child_schema(ctx: AppContext, make_schema):
    make_schema("animal")
    ctx.schema_svc.create("mammal", parent="animal")
    ctx.commit()
    ctx.schema_svc.delete("animal")
    ctx.commit()

    with pytest.raises(ValidationError, match="mammal"):
        ctx.schema_svc.purge("animal")


def test_schema_inheritance_survives_parent_soft_delete(ctx: AppContext, make_schema):
    """A live child schema keeps resolving its parent's fields even while the
    parent is sitting in Recently Deleted (restorable, not gone)."""
    make_schema("animal", fields=[("species", "string")])
    ctx.schema_svc.create("mammal", parent="animal")
    ctx.commit()
    ctx.schema_svc.delete("animal")
    ctx.commit()

    child = ctx.schema_svc.get("mammal")
    resolved = ctx.schema_svc.collect_fields(child)
    assert [rf.field.name for rf in resolved] == ["species"]


# ------------------------------------------------------------------
# Collections (datasets)
# ------------------------------------------------------------------


def test_dataset_delete_is_soft_and_cascades_to_records(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("animal")
    make_collection("zoo")
    record = make_record("zoo", "animal", {})

    ctx.dataset_svc.delete("zoo")
    ctx.commit()

    assert "zoo" not in {d.name for d in ctx.dataset_svc.list_all()}
    deleted = ctx.record_svc.list_deleted()
    assert [r.id for r in deleted] == [record.id]


def test_dataset_restore_brings_back_dataset_and_records(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("animal")
    make_collection("zoo")
    record = make_record("zoo", "animal", {})
    ctx.dataset_svc.delete("zoo")
    ctx.commit()

    restored = ctx.dataset_svc.restore("zoo")
    ctx.commit()

    assert restored.deleted_at is None
    assert restored.record_count == 1
    assert {r.id for r in ctx.record_svc.find("zoo")} == {record.id}


def test_dataset_purge_requires_deleted_first(ctx: AppContext, make_collection):
    make_collection("zoo")
    with pytest.raises(ValidationError):
        ctx.dataset_svc.purge("zoo")


def test_dataset_purge_removes_permanently(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("animal")
    make_collection("zoo")
    make_record("zoo", "animal", {})
    ctx.dataset_svc.delete("zoo")
    ctx.commit()

    ctx.dataset_svc.purge("zoo")
    ctx.commit()

    assert ctx.dataset_svc.list_deleted() == []
    assert ctx.record_svc.list_deleted() == []


# ------------------------------------------------------------------
# Records
# ------------------------------------------------------------------


def test_record_delete_is_soft_and_excluded_from_find(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("animal")
    make_collection("zoo")
    record = make_record("zoo", "animal", {})

    ctx.record_svc.delete(str(record.id))
    ctx.commit()

    assert ctx.record_svc.find("zoo") == []
    with pytest.raises(NotFoundError):
        ctx.record_svc.get(str(record.id))


def test_record_delete_cascades_to_children(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("encounter")
    make_schema("recording", parent="encounter")
    make_collection("study")
    parent = make_record("study", "encounter", {})
    child = ctx.record_svc.add(
        "study", "recording", {}, parent_record_id=str(parent.id)
    )
    ctx.commit()

    ctx.record_svc.delete(str(parent.id))
    ctx.commit()

    deleted_ids = {r.id for r in ctx.record_svc.list_deleted()}
    assert deleted_ids == {parent.id, child.id}


def test_record_restore_cascades_to_children(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("encounter")
    make_schema("recording", parent="encounter")
    make_collection("study")
    parent = make_record("study", "encounter", {})
    child = ctx.record_svc.add(
        "study", "recording", {}, parent_record_id=str(parent.id)
    )
    ctx.commit()
    ctx.record_svc.delete(str(parent.id))
    ctx.commit()

    ctx.record_svc.restore(str(parent.id))
    ctx.commit()

    live_ids = {r.id for r in ctx.record_svc.find("study")}
    assert live_ids == {parent.id, child.id}


def test_record_restore_requires_a_deleted_record(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("animal")
    make_collection("zoo")
    record = make_record("zoo", "animal", {})
    with pytest.raises(ValidationError):
        ctx.record_svc.restore(str(record.id))


def test_record_purge_requires_deleted_first(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("animal")
    make_collection("zoo")
    record = make_record("zoo", "animal", {})
    with pytest.raises(ValidationError):
        ctx.record_svc.purge(str(record.id))


def test_record_purge_removes_permanently(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("animal")
    make_collection("zoo")
    record = make_record("zoo", "animal", {})
    ctx.record_svc.delete(str(record.id))
    ctx.commit()

    ctx.record_svc.purge(str(record.id))
    ctx.commit()

    assert ctx.record_svc.list_deleted() == []
    with pytest.raises(NotFoundError):
        ctx.record_svc.restore(str(record.id))


def test_list_deleted_can_be_scoped_to_a_dataset(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("animal")
    make_collection("zoo")
    make_collection("aquarium")
    zoo_record = make_record("zoo", "animal", {})
    aquarium_record = make_record("aquarium", "animal", {})
    ctx.record_svc.delete(str(zoo_record.id))
    ctx.record_svc.delete(str(aquarium_record.id))
    ctx.commit()

    assert {r.id for r in ctx.record_svc.list_deleted("zoo")} == {zoo_record.id}
    assert {r.id for r in ctx.record_svc.list_deleted()} == {
        zoo_record.id,
        aquarium_record.id,
    }
