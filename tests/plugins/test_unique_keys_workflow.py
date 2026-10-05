"""A workflow that writes a record a uniqueness policy refuses must carry on
with the other rows and say which record each refused one collided with."""

from __future__ import annotations

import pandas as pd
import pytest

from civex.plugins.base import WorkflowContext
from civex.plugins.registry import get_plugin


@pytest.fixture()
def run(ctx, make_collection, make_schema, make_record):
    dataset = make_collection("study")
    make_schema("recording", fields=[])
    parent = make_record("study", "recording", {})
    ctx.schema_svc.create("selection", parent="recording")
    ctx.schema_svc.add_field("selection", "number", "integer")
    ctx.schema_svc.add_field("selection", "label", "string")
    ctx.schema_svc.set_unique_keys("selection", [["label"]])
    ctx.commit()
    wf_ctx = WorkflowContext(record=parent, dataset=dataset, _app_ctx=ctx)
    return wf_ctx, parent


def test_upsert_skips_a_refused_row_and_notes_what_it_collided_with(ctx, run):
    wf_ctx, parent = run
    first = ctx.record_svc.add(
        "study",
        "selection",
        {"number": 1, "label": "A"},
        parent_record_id=str(parent.id),
    )
    registration = get_plugin("civex.upsert_records")
    config = registration.config_model(schema="selection", key_field="number")
    df = pd.DataFrame([{"number": 2, "label": "A"}, {"number": 3, "label": "B"}])

    result = registration.invoke({"table": df}, config, wf_ctx, 60.0)

    assert result.outputs["created"] == 1 and result.outputs["skipped"] == 1
    (noted,) = wf_ctx.take_duplicates()
    assert noted["existing_record_id"] == str(first.id)
    assert noted["fields"] == ["label"]
    assert wf_ctx.take_duplicates() == []  # taking clears the list
