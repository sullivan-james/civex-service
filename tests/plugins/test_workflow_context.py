"""WorkflowContext's CRUD-shaped capability surface: get_record/find_records/
delete_record/store_file/get_schema/list_schemas/get_collection/
list_collections/get_context_record/get_context_dataset, plus the
standardized (explicit-target) update_record and create_record's
context-record-defaulted context_record_id. All of it gives plugins direct,
validated access to the non-administrative data areas (records, files) plus
read access to the structural ones (schemas, collections) instead of
reaching into `ctx._app_ctx.<service>` directly.
"""

from __future__ import annotations

import pytest

from civex.domain.exceptions import NotFoundError
from civex.plugins.base import WorkflowContext


def _wf_ctx(app_ctx, record, dataset) -> WorkflowContext:
    return WorkflowContext(record=record, dataset=dataset, _app_ctx=app_ctx)


def test_get_record_fetches_by_id(ctx, make_collection, make_schema, make_record):
    dataset = make_collection("study")
    make_schema("subject", fields=[("name", "string")])
    record = make_record("study", "subject", {"name": "S01"})
    wf_ctx = _wf_ctx(ctx, record, dataset)

    fetched = wf_ctx.get_record(str(record.id))

    assert fetched.id == record.id
    assert fetched.data["name"] == "S01"


def test_get_record_raises_not_found_for_unknown_id(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("subject", fields=[])
    record = make_record("study", "subject", {})
    wf_ctx = _wf_ctx(ctx, record, dataset)

    with pytest.raises(NotFoundError):
        wf_ctx.get_record("00000000-0000-0000-0000-000000000000")


def test_find_records_filters_by_schema_and_field(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("subject", fields=[("name", "string"), ("status", "string")])
    make_record("study", "subject", {"name": "S01", "status": "active"})
    make_record("study", "subject", {"name": "S02", "status": "inactive"})
    trigger = make_record("study", "subject", {"name": "S03", "status": "active"})
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    active = wf_ctx.find_records(
        "study", schema_name="subject", filters=["status=active"]
    )

    assert {r.data["name"] for r in active} == {"S01", "S03"}


def test_delete_record_removes_it(ctx, make_collection, make_schema, make_record):
    dataset = make_collection("study")
    make_schema("subject", fields=[("name", "string")])
    trigger = make_record("study", "subject", {"name": "trigger"})
    target = make_record("study", "subject", {"name": "target"})
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    wf_ctx.delete_record(str(target.id))

    with pytest.raises(NotFoundError):
        ctx.record_svc.get(str(target.id))


def test_update_record_targets_an_explicit_record_not_implicitly_the_trigger(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("subject", fields=[("status", "string")])
    trigger = make_record("study", "subject", {"status": "pending"})
    other = make_record("study", "subject", {"status": "pending"})
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    updated = wf_ctx.update_record(str(other.id), {"status": "done"})

    assert updated.data["status"] == "done"
    assert ctx.record_svc.get(str(trigger.id)).data["status"] == "pending"
    assert ctx.record_svc.get(str(other.id)).data["status"] == "done"


def test_update_record_can_still_target_the_trigger_via_get_context_record(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("subject", fields=[("status", "string")])
    trigger = make_record("study", "subject", {"status": "pending"})
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    context_record = wf_ctx.get_context_record()
    assert context_record.id == trigger.id
    wf_ctx.update_record(str(context_record.id), {"status": "done"})

    assert ctx.record_svc.get(str(trigger.id)).data["status"] == "done"


def test_get_context_dataset_returns_the_trigger_dataset(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("subject", fields=[])
    trigger = make_record("study", "subject", {})
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    assert wf_ctx.get_context_dataset().name == "study"


def test_create_record_defaults_context_record_id_to_the_trigger_record(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("trigger", fields=[])
    trigger = make_record("study", "trigger", {})
    ctx.schema_svc.create("child", parent="trigger")
    ctx.schema_svc.add_field("child", "name", "string")
    ctx.commit()
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    created = wf_ctx.create_record("study", "child", {"name": "auto-parented"})

    assert created.parent_record_id == trigger.id


def test_create_record_explicit_context_record_id_overrides_the_default(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("trigger", fields=[])
    trigger = make_record("study", "trigger", {})
    ctx.schema_svc.create("child", parent="trigger")
    ctx.schema_svc.add_field("child", "name", "string")
    ctx.commit()
    other_trigger = make_record("study", "trigger", {})
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    created = wf_ctx.create_record(
        "study", "child", {"name": "x"}, context_record_id=str(other_trigger.id)
    )

    assert created.parent_record_id == other_trigger.id


def test_create_record_appends_to_affected_records(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("trigger", fields=[])
    trigger = make_record("study", "trigger", {})
    ctx.schema_svc.create("child", parent="trigger")
    ctx.schema_svc.add_field("child", "name", "string")
    ctx.commit()
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    created = wf_ctx.create_record("study", "child", {"name": "auto-parented"})

    assert wf_ctx.affected_records == [
        {
            "record_id": str(created.id),
            "schema_name": "child",
            "natural_name": created.natural_name,
            "action": "created",
        }
    ]


def test_update_record_appends_to_affected_records(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("subject", fields=[("status", "string")])
    trigger = make_record("study", "subject", {"status": "pending"})
    other = make_record("study", "subject", {"status": "pending"})
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    updated = wf_ctx.update_record(str(other.id), {"status": "done"})

    assert wf_ctx.affected_records == [
        {
            "record_id": str(other.id),
            "schema_name": "subject",
            "natural_name": updated.natural_name,
            "action": "updated",
        }
    ]


def test_affected_records_upgrades_created_to_updated_on_later_touch(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("trigger", fields=[])
    trigger = make_record("study", "trigger", {})
    ctx.schema_svc.create("child", parent="trigger")
    ctx.schema_svc.add_field("child", "name", "string")
    ctx.commit()
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    created = wf_ctx.create_record("study", "child", {"name": "first"})
    updated = wf_ctx.update_record(str(created.id), {"name": "corrected"})

    # One entry, not two -- and it reflects the more recent action.
    assert wf_ctx.affected_records == [
        {
            "record_id": str(created.id),
            "schema_name": "child",
            "natural_name": updated.natural_name,
            "action": "updated",
        }
    ]


def test_store_file_then_get_file_round_trips_bytes(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("trigger", fields=[])
    trigger = make_record("study", "trigger", {})
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    ref = wf_ctx.store_file(b"hello world", "hello.txt")

    assert ref.filename == "hello.txt"
    assert ref.size == len(b"hello world")
    assert wf_ctx.get_file(ref.sha256) == b"hello world"


def test_get_schema_and_list_schemas_include_fields(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("subject", fields=[("name", "string"), ("age", "integer")])
    trigger = make_record("study", "subject", {})
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    schema = wf_ctx.get_schema("subject")
    assert {f.name for f in schema.fields} == {"name", "age"}

    all_schemas = wf_ctx.list_schemas()
    assert "subject" in {s.name for s in all_schemas}


def test_get_collection_and_list_collections(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_collection("other_study")
    make_schema("trigger", fields=[])
    trigger = make_record("study", "trigger", {})
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    fetched = wf_ctx.get_collection("study")
    assert fetched.name == "study"

    names = {d.name for d in wf_ctx.list_collections()}
    assert names == {"study", "other_study"}
