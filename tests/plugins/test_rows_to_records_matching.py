"""`civex.rows_to_records` matches rows to the records already there.

Running the same table twice once made every record twice: the step only ever
inserted. With a key (Match rows by, else the kind's unique key) a row updates
the record holding its key's values, a second run changes nothing, and rows it
can't place (no key value, a key repeated in the table) are skipped and named.
"""

from __future__ import annotations

import pandas as pd
import pytest

from civex.plugins.base import WorkflowContext
from civex.plugins.registry import get_plugin


@pytest.fixture()
def place(ctx, make_collection, make_schema, make_record):
    dataset = make_collection("study")
    make_schema("recording", fields=[])
    parent = make_record("study", "recording", {})
    ctx.schema_svc.create("selection", parent="recording")
    for name, dtype in (
        ("number", "integer"),
        ("channel", "integer"),
        ("label", "string"),
        ("note", "string"),
    ):
        ctx.schema_svc.add_field("selection", name, dtype)
    ctx.commit()
    return WorkflowContext(record=parent, dataset=dataset, _app_ctx=ctx), parent


def _run(wf_ctx, rows, plugin="civex.rows_to_records", **config):
    registration = get_plugin(plugin)
    model = registration.config_model(schema="selection", **config)
    return registration.invoke({"table": pd.DataFrame(rows)}, model, wf_ctx, 60.0)


def _selections(ctx, parent):
    return ctx.record_svc.find(
        "study", schema_name="selection", parent_record_id=str(parent.id)
    )


def _history(ctx) -> int:
    return len(ctx.audit_svc.list_audit(limit=10_000))


TABLE = [
    {"number": 1, "channel": 1, "note": "a"},
    {"number": 2, "channel": 1, "note": "b"},
    {"number": 3, "channel": 2, "note": "c"},
]


def test_running_the_same_table_again_changes_nothing(ctx, place):
    wf_ctx, parent = place
    first = _run(wf_ctx, TABLE, match_on=["number"])
    ctx.commit()
    assert first.outputs["created"] == 3
    entries = _history(ctx)
    wf_ctx.affected_records.clear()

    again = _run(wf_ctx, TABLE, match_on=["number"])
    ctx.commit()

    assert again.outputs == {
        "created": 0,
        "updated": 0,
        "unchanged": 3,
        "skipped": 0,
        "skipped_rows": [],
    }
    assert len(_selections(ctx, parent)) == 3
    assert _history(ctx) == entries  # no history, so nothing triggered either
    assert wf_ctx.affected_records == []


def test_a_changed_row_updates_only_its_columns(ctx, place):
    wf_ctx, parent = place
    _run(wf_ctx, TABLE, match_on=["number"])
    (two,) = [r for r in _selections(ctx, parent) if r.data["number"] == 2]
    ctx.record_svc.patch(str(two.id), {"label": "kept"})

    result = _run(wf_ctx, [{"number": 2, "channel": 7}], match_on=["number"])

    assert result.outputs["updated"] == 1 and result.outputs["created"] == 0
    after = ctx.record_svc.get(str(two.id)).data
    assert after["channel"] == 7 and after["note"] == "b" and after["label"] == "kept"


def test_without_a_key_the_kinds_unique_key_is_used(ctx, place):
    wf_ctx, parent = place
    ctx.schema_svc.set_unique_keys("selection", [["number", "channel"]])
    ctx.commit()
    _run(wf_ctx, TABLE)

    result = _run(wf_ctx, [{"number": 1, "channel": 1, "note": "changed"}])

    assert result.outputs["updated"] == 1 and result.outputs["created"] == 0
    assert len(_selections(ctx, parent)) == 3


def test_without_a_key_or_a_unique_key_every_row_is_new(ctx, place):
    wf_ctx, parent = place
    _run(wf_ctx, TABLE)
    result = _run(wf_ctx, TABLE)

    assert result.outputs["created"] == 3
    assert len(_selections(ctx, parent)) == 6


def test_a_key_of_several_fields_needs_all_of_them_to_agree(ctx, place):
    wf_ctx, parent = place
    _run(wf_ctx, TABLE, match_on=["number", "channel"])

    result = _run(
        wf_ctx,
        [{"number": 1, "channel": 1, "note": "x"}, {"number": 1, "channel": 2}],
        match_on=["number", "channel"],
    )

    assert result.outputs["updated"] == 1 and result.outputs["created"] == 1
    assert len(_selections(ctx, parent)) == 4


def test_numbers_match_as_a_unique_key_compares_them(ctx, place):
    """A column with a blank cell reaches the step as floats: 12.0 is the
    record holding 12."""
    wf_ctx, parent = place
    _run(wf_ctx, [{"number": 12, "label": "12"}], match_on=["number"])

    floats = _run(
        wf_ctx,
        [{"number": 12.0, "note": "x"}, {"number": float("nan"), "note": "y"}],
        match_on=["number"],
    )
    assert floats.outputs["updated"] == 1 and floats.outputs["created"] == 0

    # A number given for a text field is its text: 12 (or 12.0, from a
    # column with a blank) is the record whose label is "12", and is
    # written as "12".
    by_text = _run(
        wf_ctx,
        [{"label": 12.0, "note": "z"}, {"label": 7, "note": "new"}],
        match_on=["label"],
    )
    assert by_text.outputs["updated"] == 1 and by_text.outputs["created"] == 1
    labels = sorted(r.data["label"] for r in _selections(ctx, parent))
    assert labels == ["12", "7"]


def test_blank_and_repeated_keys_are_skipped_and_named(ctx, place):
    wf_ctx, parent = place
    result = _run(
        wf_ctx,
        [
            {"number": 1, "note": "first"},
            {"number": None, "note": "no key"},
            {"number": 1.0, "note": "again"},
        ],
        match_on=["number"],
    )

    assert result.outputs["created"] == 1 and result.outputs["skipped"] == 2
    assert result.outputs["skipped_rows"] == [
        "Row 2: no number to match it by",
        "Row 3: number 1.0 is also row 1, which was saved",
    ]
    (only,) = _selections(ctx, parent)
    assert only.data["note"] == "first"  # the repeat didn't overwrite it


def test_columns_to_fields_applies_before_matching(ctx, place):
    wf_ctx, parent = place
    mapping = {"Selection": "number", "Ch": "channel"}
    rows = [{"Selection": 1, "Ch": 1}, {"Selection": 2, "Ch": 3}]
    _run(wf_ctx, rows, match_on=["number"], field_mapping=mapping)

    result = _run(
        wf_ctx,
        [{"Selection": 2, "Ch": 4}],
        match_on=["number"],
        field_mapping=mapping,
    )

    assert result.outputs["updated"] == 1
    assert sorted(r.data["channel"] for r in _selections(ctx, parent)) == [1, 4]


def test_matching_stays_inside_the_record(ctx, place, make_record):
    wf_ctx, parent = place
    _run(wf_ctx, TABLE, match_on=["number"])
    other = make_record("study", "recording", {})

    result = _run(wf_ctx, TABLE, match_on=["number"], context_record_id=str(other.id))

    assert result.outputs["created"] == 3  # the same numbers in another recording


def test_an_unknown_or_unmatchable_field_stops_the_step(ctx, place):
    wf_ctx, _ = place
    with pytest.raises(Exception, match="has no such field"):
        _run(wf_ctx, TABLE, match_on=["nope"])


def test_upsert_records_is_the_same_step_under_its_old_name(ctx, place):
    wf_ctx, parent = place
    first = _run(wf_ctx, TABLE, plugin="civex.upsert_records", key_field="number")
    again = _run(wf_ctx, TABLE, plugin="civex.upsert_records", key_field="number")

    assert first.outputs["created"] == 3
    assert again.outputs["unchanged"] == 3 and again.outputs["created"] == 0
    assert len(_selections(ctx, parent)) == 3


def test_several_records_with_the_key_are_not_guessed_between(ctx, place):
    wf_ctx, parent = place
    for _ in range(2):
        ctx.record_svc.add(
            "study", "selection", {"number": 5}, parent_record_id=str(parent.id)
        )

    result = _run(wf_ctx, [{"number": 5, "note": "?"}], match_on=["number"])

    assert result.outputs["skipped_rows"] == [
        "Row 1: several records already have number 5"
    ]
    assert all("note" not in r.data for r in _selections(ctx, parent))
