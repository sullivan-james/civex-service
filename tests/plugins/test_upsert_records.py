"""`civex.upsert_records` must never erase what the table doesn't mention.

A run once reduced records with 58 fields (a file and 49 computed statistics
among them) to the 9 columns of the table, because the update replaced the whole
record with the row. These tests are that run."""

from __future__ import annotations

import pandas as pd
import pytest

from civex.plugins.base import WorkflowContext
from civex.plugins.registry import get_plugin


@pytest.fixture()
def setup(ctx, make_collection, make_schema, make_record):
    dataset = make_collection("study")
    make_schema("recording", fields=[])
    parent = make_record("study", "recording", {})
    ctx.schema_svc.create("selection", parent="recording")
    for name, dtype in (
        ("selection_number", "integer"),
        ("channel", "integer"),
        ("annotation", "string"),
        ("duration", "float"),
        ("contour_file", "file"),
    ):
        ctx.schema_svc.add_field("selection", name, dtype)
    ctx.commit()
    wf_ctx = WorkflowContext(record=parent, dataset=dataset, _app_ctx=ctx)
    return wf_ctx, parent


def _upsert(wf_ctx, rows: list[dict]):
    registration = get_plugin("civex.upsert_records")
    config = registration.config_model(schema="selection", key_field="selection_number")
    # The table as the previous step hands it on.
    df = pd.DataFrame(rows)
    registration.invoke({"table": df}, config, wf_ctx, 60.0)
    return df


def _only(ctx, parent_id, number):
    found = ctx.record_svc.find(
        "study",
        schema_name="selection",
        parent_record_id=str(parent_id),
        filters=[f"selection_number={number}"],
        limit=1,
    )
    assert found, f"no selection {number}"
    return found[0]


FILE = {"sha256": "a" * 64, "filename": "contour.csv", "size": 10}


def _existing(ctx, parent) -> str:
    rec = ctx.record_svc.add(
        "study",
        "selection",
        {
            "selection_number": 1,
            "channel": 1,
            "annotation": "orca",
            "duration": 0.341,
            "contour_file": FILE,
        },
        parent_record_id=str(parent.id),
    )
    ctx.commit()
    return str(rec.id)


def test_updating_from_a_table_keeps_the_fields_the_table_does_not_have(
    ctx, setup
) -> None:
    wf_ctx, parent = setup
    rid = _existing(ctx, parent)

    # The table has only these columns; the record also has a file and a duration.
    _upsert(wf_ctx, [{"selection_number": 1, "channel": 2}])
    ctx.commit()

    after = ctx.record_svc.get(rid).data
    assert after["channel"] == 2  # what the table says is applied
    assert after["annotation"] == "orca"  # what it doesn't mention is kept
    assert after["duration"] == 0.341
    assert after["contour_file"]["sha256"] == "a" * 64  # including the file


def test_an_empty_cell_leaves_the_existing_value_alone(ctx, setup) -> None:
    wf_ctx, parent = setup
    rid = _existing(ctx, parent)

    _upsert(
        wf_ctx,
        [{"selection_number": 1, "channel": float("nan"), "annotation": None}],
    )
    ctx.commit()

    after = ctx.record_svc.get(rid).data
    assert after["channel"] == 1 and after["annotation"] == "orca"  # not cleared
    assert not any(v is None for v in after.values())  # and nothing set to null


def test_new_rows_still_create_records_with_only_the_values_given(ctx, setup) -> None:
    wf_ctx, parent = setup

    _upsert(wf_ctx, [{"selection_number": 5, "channel": 3, "annotation": None}])
    ctx.commit()

    data = _only(ctx, parent.id, 5).data
    assert data["channel"] == 3 and "annotation" not in data


def test_a_run_that_changes_nothing_leaves_no_history(ctx, setup) -> None:
    wf_ctx, parent = setup
    rid = _existing(ctx, parent)
    before = len(ctx.audit_svc.list_audit(entity_id=_uuid(rid)))

    _upsert(wf_ctx, [{"selection_number": 1, "channel": 1, "annotation": "orca"}])
    ctx.commit()

    assert len(ctx.audit_svc.list_audit(entity_id=_uuid(rid))) == before
    assert wf_ctx.affected_records == []  # not touched, so not listed


def test_only_what_actually_changed_is_recorded_as_touched(ctx, setup) -> None:
    wf_ctx, parent = setup
    _existing(ctx, parent)

    _upsert(wf_ctx, [{"selection_number": 1, "channel": 9}])

    assert [a["action"] for a in wf_ctx.affected_records] == ["updated"]


def _uuid(s: str):
    import uuid

    return uuid.UUID(s)


def test_patch_record_reads_the_record_as_it_is_now(ctx, setup) -> None:
    wf_ctx, parent = setup
    rid = _existing(ctx, parent)
    # Something else changes the record after the workflow began.
    ctx.record_svc.update(
        rid, {**ctx.record_svc.get(rid).data, "annotation": "dolphin"}
    )
    ctx.commit()

    wf_ctx.patch_record(rid, {"channel": 4})
    ctx.commit()

    after = ctx.record_svc.get(rid).data
    assert after["channel"] == 4
    assert after["annotation"] == "dolphin"  # the newer value, not a stale copy


def test_save_fields_keeps_everything_else_too(ctx, setup) -> None:
    wf_ctx, parent = setup
    rid = _existing(ctx, parent)
    registration = get_plugin("civex.save_fields")
    ctx_for_record = WorkflowContext(
        record=ctx.record_svc.get(rid), dataset=wf_ctx.dataset, _app_ctx=ctx
    )

    registration.invoke(
        {"updates": {"duration": 0.9, "annotation": None}},
        registration.config_model(),
        ctx_for_record,
        60.0,
    )
    ctx.commit()

    after = ctx.record_svc.get(rid).data
    assert after["duration"] == 0.9
    assert after["annotation"] == "orca"  # a null update is skipped
    assert after["contour_file"]["sha256"] == "a" * 64
