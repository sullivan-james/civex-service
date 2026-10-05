"""Uniqueness policies: which field combinations no two records may share.

A key is checked among live records of the schema in the same place: under the
same parent record, or, at the top level, in the same collection."""

from __future__ import annotations

import pytest

from civex.context import AppContext
from civex.domain.exceptions import (
    DuplicateRecordError,
    NotFoundError,
    ValidationError,
)


@pytest.fixture()
def plots(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema(
        "plot",
        fields=[("site", "string"), ("number", "integer"), ("notes", "string")],
    )
    make_collection("survey")
    make_collection("other")
    ctx.schema_svc.set_unique_keys("plot", [["site", "number"]])
    ctx.commit()
    return make_record


def test_a_second_record_with_the_same_key_is_refused_and_names_the_first(
    ctx: AppContext, plots
):
    first = plots("survey", "plot", {"site": "A", "number": 1})
    with pytest.raises(DuplicateRecordError) as e:
        ctx.record_svc.add("survey", "plot", {"site": "A", "number": 1})
    assert e.value.existing_id == str(first.id)
    assert e.value.fields == ["site", "number"]
    assert "same site and number" in str(e.value)
    assert "within the collection" in str(e.value)


def test_it_takes_the_whole_key_to_clash(ctx: AppContext, plots):
    plots("survey", "plot", {"site": "A", "number": 1})
    plots("survey", "plot", {"site": "A", "number": 2})
    plots("survey", "plot", {"site": "B", "number": 1})


def test_another_collection_is_another_place(ctx: AppContext, plots):
    plots("survey", "plot", {"site": "A", "number": 1})
    plots("other", "plot", {"site": "A", "number": 1})


def test_blank_values_never_clash(ctx: AppContext, plots):
    plots("survey", "plot", {"site": "A"})
    plots("survey", "plot", {"site": "A"})
    plots("survey", "plot", {"site": "A", "number": None})


def test_a_number_matches_however_it_was_written(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("reading", fields=[("value", "float")])
    make_collection("lab")
    ctx.schema_svc.set_unique_keys("reading", [["value"]])
    make_record("lab", "reading", {"value": 1})
    with pytest.raises(DuplicateRecordError):
        ctx.record_svc.add("lab", "reading", {"value": 1.0})


def test_updating_into_a_clash_is_refused_but_other_edits_are_not(
    ctx: AppContext, plots
):
    plots("survey", "plot", {"site": "A", "number": 1})
    second = plots("survey", "plot", {"site": "A", "number": 2})
    with pytest.raises(DuplicateRecordError):
        ctx.record_svc.update(str(second.id), {"site": "A", "number": 1})
    # Saving the record with its own key unchanged is fine.
    ctx.record_svc.update(str(second.id), {"site": "A", "number": 2, "notes": "ok"})


def test_an_old_duplicate_does_not_block_editing_something_else(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("plot", fields=[("site", "string"), ("notes", "string")])
    make_collection("survey")
    a = make_record("survey", "plot", {"site": "A"})
    make_record("survey", "plot", {"site": "A"})
    with pytest.raises(ValidationError):
        ctx.schema_svc.set_unique_keys("plot", [["site"]])
    # Policy was refused, so the records stay editable as before.
    ctx.record_svc.update(str(a.id), {"site": "A", "notes": "x"})


def test_children_are_unique_within_their_parent_only(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("encounter", fields=[("site", "string")])
    make_schema("recording", fields=[("number", "integer")], parent="encounter")
    make_collection("survey")
    ctx.schema_svc.set_unique_keys("recording", [["number"]])
    e1 = make_record("survey", "encounter", {"site": "S"})
    e2 = make_record("survey", "encounter", {"site": "T"})
    make_record("survey", "recording", {"number": 1}, parent_record_id=str(e1.id))
    make_record("survey", "recording", {"number": 1}, parent_record_id=str(e2.id))
    with pytest.raises(DuplicateRecordError) as e:
        ctx.record_svc.add(
            "survey", "recording", {"number": 1}, parent_record_id=str(e1.id)
        )
    assert "within its parent" in str(e.value)


def test_a_deleted_record_frees_its_values(ctx: AppContext, plots):
    first = plots("survey", "plot", {"site": "A", "number": 1})
    ctx.record_svc.delete(str(first.id))
    ctx.commit()
    plots("survey", "plot", {"site": "A", "number": 1})


# --- restoring -------------------------------------------------------------


def test_a_record_whose_values_were_taken_cannot_come_back_and_the_plan_says_so(
    ctx: AppContext, plots
):
    first = plots("survey", "plot", {"site": "A", "number": 1})
    ctx.record_svc.delete(str(first.id))
    ctx.commit()
    taker = plots("survey", "plot", {"site": "A", "number": 1})

    plan = ctx.record_svc.restore_plan(str(first.id))
    assert plan.can_restore is False
    assert plan.blocked_by is None
    assert plan.conflict is not None
    assert plan.conflict.existing_id == str(taker.id)
    assert plan.conflict.fields == ["site", "number"]
    assert "Change or delete" in (plan.blocked_message or "")

    with pytest.raises(DuplicateRecordError) as e:
        ctx.record_svc.restore(str(first.id))
    assert e.value.existing_id == str(taker.id)

    # Once the other record is out of the way it can.
    ctx.record_svc.delete(str(taker.id))
    ctx.commit()
    assert ctx.record_svc.restore_plan(str(first.id)).can_restore is True
    ctx.record_svc.restore(str(first.id))


def test_restore_all_leaves_clashing_records_deleted_and_counts_them_blocked(
    ctx: AppContext, plots
):
    clash = plots("survey", "plot", {"site": "A", "number": 1})
    fine = plots("survey", "plot", {"site": "A", "number": 2})
    ctx.record_svc.delete_many([str(clash.id), str(fine.id)])
    ctx.commit()
    plots("survey", "plot", {"site": "A", "number": 1})

    where = {"and": [{"field": "collection", "op": "eq", "value": "survey"}]}
    plan = ctx.history_svc.plan_restore_all(where)
    assert plan.blocked == 1
    result = ctx.history_svc.restore_all(where)
    assert result.blocked == 1
    live = {r.id for r in ctx.record_svc.find("survey", "plot")}
    assert fine.id in live and clash.id not in live


def test_reverting_a_delete_explains_the_clash(ctx: AppContext, plots):
    first = plots("survey", "plot", {"site": "A", "number": 1})
    ctx.record_svc.delete(str(first.id))
    ctx.commit()
    plots("survey", "plot", {"site": "A", "number": 1})
    entry = next(
        e
        for e in ctx.history_svc.page(entity_id=first.id)
        if e.action == "delete"
    )
    plan = ctx.history_svc.plan_revert(str(entry.id))
    assert plan.can_apply is False
    assert "same site and number" in (plan.blocked or "")


# --- defining a policy ------------------------------------------------------


def test_a_policy_is_refused_while_records_already_break_it(
    ctx: AppContext, make_schema, make_collection, make_record
):
    make_schema("plot", fields=[("site", "string")])
    make_collection("survey")
    make_record("survey", "plot", {"site": "A"})
    make_record("survey", "plot", {"site": "A"})
    with pytest.raises(ValidationError, match="already share"):
        ctx.schema_svc.set_unique_keys("plot", [["site"]])
    assert ctx.schema_svc.get("plot").unique_keys == []


def test_keys_need_the_schemas_own_scalar_fields(
    ctx: AppContext, make_schema, make_collection
):
    make_schema("plot", fields=[("site", "string"), ("photo", "file")])
    make_schema("sub", fields=[("x", "string")], parent="plot")
    with pytest.raises(NotFoundError):
        ctx.schema_svc.set_unique_keys("plot", [["nope"]])
    with pytest.raises(NotFoundError, match="own fields"):
        ctx.schema_svc.set_unique_keys("sub", [["site"]])
    with pytest.raises(ValidationError, match="file field"):
        ctx.schema_svc.set_unique_keys("plot", [["photo"]])
    with pytest.raises(ValidationError, match="at least one"):
        ctx.schema_svc.set_unique_keys("plot", [[]])
    with pytest.raises(ValidationError, match="repeat"):
        ctx.schema_svc.set_unique_keys("plot", [["site", "site"]])


def test_the_same_fields_in_another_order_are_one_key(ctx: AppContext, plots):
    ctx.schema_svc.set_unique_keys("plot", [["site", "number"], ["number", "site"]])
    assert ctx.schema_svc.get("plot").unique_key_names == [["site", "number"]]


def test_deleting_a_field_drops_the_keys_that_use_it(ctx: AppContext, plots):
    ctx.schema_svc.set_unique_keys("plot", [["site", "number"], ["site"]])
    ctx.schema_svc.delete_field("plot", "number")
    assert ctx.schema_svc.get("plot").unique_key_names == [["site"]]


def test_renaming_a_field_keeps_the_key(ctx: AppContext, plots):
    ctx.schema_svc.update_field("plot", "number", new_name="plot_number")
    assert ctx.schema_svc.get("plot").unique_key_names == [["site", "plot_number"]]


def test_a_policy_change_is_in_history(ctx: AppContext, plots):
    entries = ctx.history_svc.page(entity_id=ctx.schema_svc.get("plot").id)
    assert any(e.action == "update" for e in entries)
