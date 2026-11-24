"""Characterization tests for the 11 built-in plugins re-implemented against
Tier0Plugin/invoke() in CIVEX-136. Each locks in the exact behavior the
plugin already had under BasePlugin.run().

create_records_from_files/match_files_to_records/rows_to_records/
upsert_records all catch ValidationError per-row/per-item and count it as
skipped/unmatched rather than aborting the whole run (CIVEX-157) -- and all
go through ctx.create_record()/ctx.update_record() for job_depth propagation
(CIVEX-158).
"""

from __future__ import annotations

import dataclasses
import sys

import pandas as pd
import pytest

from civex.context import AppContext
from civex.plugins.base import WorkflowContext
from civex.plugins.registry import get_plugin


def _wf_ctx(app_ctx: AppContext, record, dataset) -> WorkflowContext:
    return WorkflowContext(record=record, dataset=dataset, _app_ctx=app_ctx)


@pytest.fixture(autouse=True)
def _enforce_declared_contract(monkeypatch):
    """Make every behavior test below double as a contract-conformance test.

    CIVEX-142 validates a workflow's step wiring against declared inputs/
    outputs at save time and refuses anything undeclared, so a built-in whose
    declaration drifts from what invoke() actually accepts and returns
    doesn't produce a wrong plugin listing -- it makes correct workflows
    unsaveable. Wrapping get_plugin() here, rather than adding an assertion
    to each test, means a test added later is covered without remembering to
    opt in.
    """
    real_get_plugin = get_plugin

    def checked_get_plugin(plugin_id: str):
        registration = real_get_plugin(plugin_id)
        if registration is None:
            return None
        inner = registration.invoke

        def invoke(inputs, config, ctx, timeout):
            _assert_names_match(plugin_id, "input", registration.inputs, inputs)
            result = inner(inputs, config, ctx, timeout)
            _assert_names_match(
                plugin_id, "output", registration.outputs, result.outputs
            )
            return result

        return dataclasses.replace(registration, invoke=invoke)

    monkeypatch.setattr(sys.modules[__name__], "get_plugin", checked_get_plugin)


def _assert_names_match(plugin_id: str, kind: str, specs, actual: dict) -> None:
    if specs is None:  # no contract declared in this direction; nothing to check
        return
    declared = {spec.name for spec in specs}
    required = {spec.name for spec in specs if spec.required}
    undeclared = set(actual) - declared
    assert not undeclared, (
        f"{plugin_id} used undeclared {kind}(s): {sorted(undeclared)}"
    )
    missing = required - set(actual)
    assert not missing, f"{plugin_id} omitted required {kind}(s): {sorted(missing)}"


def test_load_file_list_returns_raw_file_refs(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("doc", fields=[("attachments", "file_list")])
    ref1 = ctx.file_svc.store_bytes(b"a", "a.txt")
    ref2 = ctx.file_svc.store_bytes(b"b", "b.txt")
    record = make_record(
        "study", "doc", {"attachments": [ref1.to_dict(), ref2.to_dict()]}
    )
    wf_ctx = _wf_ctx(ctx, record, dataset)

    registration = get_plugin("civex.files@1")
    config = registration.config_model(source="field", field="attachments")
    result = registration.invoke({}, config, wf_ctx, 60.0)

    # Record reads stamp `resolved_filename` onto every file/file_list value
    # (see RecordService._apply_filename_templates) -- with no
    # filename_template restriction set, it just echoes the original name.
    assert result.outputs == {
        "files": [
            {**ref1.to_dict(), "resolved_filename": ref1.filename},
            {**ref2.to_dict(), "resolved_filename": ref2.filename},
        ]
    }


def test_load_file_list_returns_empty_list_when_field_missing_no_raise(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("doc", fields=[("attachments", "file_list")])
    record = make_record("study", "doc", {})
    wf_ctx = _wf_ctx(ctx, record, dataset)

    registration = get_plugin("civex.files@1")
    config = registration.config_model(source="field", field="attachments")
    result = registration.invoke({}, config, wf_ctx, 60.0)

    assert result.outputs == {"files": []}


def test_extract_from_filename_uses_capture_group(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("doc", fields=[("attachment", "file")])
    ref = ctx.file_svc.store_bytes(b"x", "sample_20240102.txt")
    record = make_record("study", "doc", {"attachment": ref.to_dict()})
    wf_ctx = _wf_ctx(ctx, record, dataset)

    registration = get_plugin("civex.value_from_filename@1")
    config = registration.config_model(field="attachment", pattern=r"sample_(\d+)")
    result = registration.invoke({}, config, wf_ctx, 60.0)

    assert result.outputs == {
        "value": "20240102",
        "filename": "sample_20240102.txt",
        "extracted": "20240102",
    }


def test_extract_from_filename_converts_to_date_via_token_format(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("doc", fields=[("attachment", "file")])
    ref = ctx.file_svc.store_bytes(b"x", "sample_20240102.txt")
    record = make_record("study", "doc", {"attachment": ref.to_dict()})
    wf_ctx = _wf_ctx(ctx, record, dataset)

    registration = get_plugin("civex.value_from_filename@1")
    config = registration.config_model(
        field="attachment",
        pattern=r"sample_(\d+)",
        output_type="date",
        date_format="YYYYMMDD",
    )
    result = registration.invoke({}, config, wf_ctx, 60.0)

    assert result.outputs["value"] == "2024-01-02"


def test_extract_from_filename_datetime_is_naive_wall_time(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("doc", fields=[("attachment", "file")])
    ref = ctx.file_svc.store_bytes(b"x", "rec_20210218_075000.wav")
    record = make_record("study", "doc", {"attachment": ref.to_dict()})
    wf_ctx = _wf_ctx(ctx, record, dataset)

    registration = get_plugin("civex.value_from_filename@1")
    config = registration.config_model(
        field="attachment",
        pattern=r"rec_(\d{8}_\d{6})",
        output_type="datetime",
        date_format="YYYYMMDD_HHmmSS",
    )
    result = registration.invoke({}, config, wf_ctx, 60.0)

    # No offset: the record service decides which zone this is wall time in.
    assert result.outputs["value"] == "2021-02-18T07:50:00"


def test_extracted_datetime_is_read_in_the_collection_timezone_when_saved(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    ctx.dataset_svc.update("study", timezone="America/Chicago")
    make_schema("doc", fields=[("attachment", "file"), ("recorded_at", "datetime")])
    ref = ctx.file_svc.store_bytes(b"x", "rec_20210218_075000.wav")
    record = make_record("study", "doc", {"attachment": ref.to_dict()})
    wf_ctx = _wf_ctx(ctx, record, dataset)

    registration = get_plugin("civex.value_from_filename@1")
    config = registration.config_model(
        field="attachment",
        pattern=r"rec_(\d{8}_\d{6})",
        output_type="datetime",
        date_format="YYYYMMDD_HHmmSS",
    )
    value = registration.invoke({}, config, wf_ctx, 60.0).outputs["value"]
    updated = ctx.record_svc.update(
        str(record.id), {**record.data, "recorded_at": value}
    )

    assert updated.data["recorded_at"] == "2021-02-18T13:50:00+00:00"  # CST, UTC-6


def test_rows_to_records_creates_one_record_per_row(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("trigger", fields=[])
    trigger = make_record("study", "trigger", {})
    make_schema("item", fields=[("name", "string"), ("age", "integer")])
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    registration = get_plugin("civex.save_records@1")
    config = registration.config_model(schema="item")
    df = pd.DataFrame([{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}])
    result = registration.invoke({"rows": df}, config, wf_ctx, 60.0)

    assert result.outputs == {
        "created": 2,
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "skipped_rows": [],
    }
    created = ctx.record_svc.find("study", schema_name="item")
    assert {r.data["name"] for r in created} == {"Alice", "Bob"}


def test_rows_to_records_counts_validation_failures_as_skipped_and_continues(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("trigger", fields=[])
    trigger = make_record("study", "trigger", {})
    ctx.schema_svc.create("item")
    ctx.schema_svc.add_field("item", "name", "string")
    ctx.schema_svc.add_field("item", "required_note", "string", required=True)
    ctx.commit()
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    registration = get_plugin("civex.save_records@1")
    config = registration.config_model(schema="item")
    df = pd.DataFrame(
        [
            {"name": "Alice", "required_note": "ok"},
            {"name": "Bob"},  # missing required_note -> fails validation
        ]
    )
    result = registration.invoke({"rows": df}, config, wf_ctx, 60.0)

    assert result.outputs["created"] == 1 and result.outputs["skipped"] == 1
    assert result.outputs["skipped_rows"][0].startswith("Row 2: ")
    created = ctx.record_svc.find("study", schema_name="item")
    assert [r.data["name"] for r in created] == ["Alice"]


def test_create_records_from_files_creates_one_per_file(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("trigger", fields=[])
    trigger = make_record("study", "trigger", {})
    make_schema("attachment", fields=[("file_field", "file")])
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    registration = get_plugin("civex.save_records@1")
    config = registration.config_model(
        schema="attachment", file_field="file_field", if_exists="add_new"
    )
    ref = ctx.file_svc.store_bytes(b"x", "a.txt")
    result = registration.invoke({"files": [ref.to_dict()]}, config, wf_ctx, 60.0)

    assert result.outputs["created"] == 1 and result.outputs["skipped"] == 0
    created = ctx.record_svc.find("study", schema_name="attachment")
    assert len(created) == 1
    assert created[0].data["file_field"]["filename"] == "a.txt"


def test_create_records_from_files_counts_validation_failures_as_skipped(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("trigger", fields=[])
    trigger = make_record("study", "trigger", {})
    ctx.schema_svc.create("attachment")
    ctx.schema_svc.add_field("attachment", "file_field", "file")
    ctx.schema_svc.add_field("attachment", "required_note", "string", required=True)
    ctx.commit()
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    registration = get_plugin("civex.save_records@1")
    config = registration.config_model(
        schema="attachment", file_field="file_field", if_exists="add_new"
    )
    ref = ctx.file_svc.store_bytes(b"x", "a.txt")
    result = registration.invoke({"files": [ref.to_dict()]}, config, wf_ctx, 60.0)

    assert result.outputs["created"] == 0 and result.outputs["skipped"] == 1


def _files(result):
    out = result.outputs
    return out["created"], out["updated"], out["unmatched"], out["ambiguous"]


def test_match_files_to_records_creates_then_updates_by_key(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("trigger", fields=[])
    trigger = make_record("study", "trigger", {})
    ctx.schema_svc.create("selection", parent="trigger")
    ctx.schema_svc.add_field("selection", "selection_number", "integer")
    ctx.schema_svc.add_field("selection", "contour_file", "file")
    ctx.commit()
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    registration = get_plugin("civex.save_records@1")
    config = registration.config_model(
        schema="selection",
        match_on=["selection_number"],
        file_field="contour_file",
        filename_pattern=r"sel_(\d+)",
    )

    ref1 = ctx.file_svc.store_bytes(b"x", "sel_01.txt")
    result1 = registration.invoke({"files": [ref1.to_dict()]}, config, wf_ctx, 60.0)
    assert _files(result1) == (1, 0, [], [])

    ref2 = ctx.file_svc.store_bytes(b"y", "sel_01_v2.txt")
    result2 = registration.invoke({"files": [ref2.to_dict()]}, config, wf_ctx, 60.0)
    assert _files(result2) == (0, 1, [], [])

    ref3 = ctx.file_svc.store_bytes(b"z", "nope.txt")
    result3 = registration.invoke({"files": [ref3.to_dict()]}, config, wf_ctx, 60.0)
    assert _files(result3) == (0, 0, ["nope.txt"], [])


def test_upsert_records_creates_then_updates_by_key(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("trigger", fields=[])
    trigger = make_record("study", "trigger", {})
    make_schema(
        "item", parent="trigger", fields=[("sku", "string"), ("qty", "integer")]
    )
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    registration = get_plugin("civex.save_records@1")
    config = registration.config_model(schema="item", match_on=["sku"])

    result1 = registration.invoke(
        {"rows": pd.DataFrame([{"sku": "A1", "qty": 5}])}, config, wf_ctx, 60.0
    )
    assert result1.outputs == {
        "created": 1,
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "skipped_rows": [],
    }

    result2 = registration.invoke(
        {"rows": pd.DataFrame([{"sku": "A1", "qty": 9}])}, config, wf_ctx, 60.0
    )
    assert result2.outputs == {
        "created": 0,
        "updated": 1,
        "unchanged": 0,
        "skipped": 0,
        "skipped_rows": [],
    }

    existing = ctx.record_svc.find("study", schema_name="item")
    assert len(existing) == 1
    assert existing[0].data["qty"] == 9


def test_upsert_records_skips_and_names_rows_with_missing_key_value(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("trigger", fields=[])
    trigger = make_record("study", "trigger", {})
    make_schema("item", fields=[("sku", "string"), ("qty", "integer")])
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    registration = get_plugin("civex.save_records@1")
    config = registration.config_model(schema="item", match_on=["sku"])
    result = registration.invoke(
        {"rows": pd.DataFrame([{"sku": None, "qty": 1}])}, config, wf_ctx, 60.0
    )

    # Counted and named now, not dropped without a word.
    assert result.outputs == {
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped": 1,
        "skipped_rows": ["Row 1: no sku to match it by"],
    }


def test_upsert_records_counts_validation_failures_as_skipped_and_continues(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("trigger", fields=[])
    trigger = make_record("study", "trigger", {})
    ctx.schema_svc.create("item")
    ctx.schema_svc.add_field("item", "sku", "string")
    ctx.schema_svc.add_field("item", "qty", "integer")
    ctx.schema_svc.add_field("item", "required_note", "string", required=True)
    ctx.commit()
    wf_ctx = _wf_ctx(ctx, trigger, dataset)

    registration = get_plugin("civex.save_records@1")
    config = registration.config_model(schema="item", match_on=["sku"])
    df = pd.DataFrame(
        [
            {"sku": "A1", "qty": 5, "required_note": "ok"},
            {"sku": "A2", "qty": 6},  # missing required_note -> fails validation
        ]
    )
    result = registration.invoke({"rows": df}, config, wf_ctx, 60.0)

    assert result.outputs["created"] == 1 and result.outputs["skipped"] == 1
    existing = ctx.record_svc.find("study", schema_name="item")
    assert [r.data["sku"] for r in existing] == ["A1"]


def test_set_fields_sets_values_updates_and_a_single_value(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("subject", fields=[("a", "string"), ("b", "string"), ("c", "string")])
    record = make_record("study", "subject", {"a": "1", "b": "orig", "c": "x"})
    wf_ctx = _wf_ctx(ctx, record, dataset)

    registration = get_plugin("civex.set_fields@1")
    result = registration.invoke(
        {"updates": {"a": "2", "b": None}, "value": "z"},
        registration.config_model(field="c"),
        wf_ctx,
        60.0,
    )

    assert result.outputs == {}
    updated = ctx.record_svc.get(str(record.id))
    assert updated.data["a"] == "2"
    assert updated.data["b"] == "orig"  # an empty update never clears a field
    assert updated.data["c"] == "z"


def test_files_from_a_field_lists_the_files(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("doc", fields=[("attachment", "file")])
    file_ref = ctx.file_svc.store_bytes(b"hello world", "hello.txt")
    record = make_record("study", "doc", {"attachment": file_ref.to_dict()})
    wf_ctx = _wf_ctx(ctx, record, dataset)

    registration = get_plugin("civex.files@1")
    result = registration.invoke(
        {}, registration.config_model(source="field", field="attachment"), wf_ctx, 60.0
    )
    assert [f["filename"] for f in result.outputs["files"]] == ["hello.txt"]
