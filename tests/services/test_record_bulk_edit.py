"""Setting (or clearing) fields on many records at once: the plan says what
would change, what already holds the values and what can't take them, the
edit does exactly that as one event, and a record that can't is skipped and
named rather than stopping the rest."""

from __future__ import annotations

import pytest

from civex.context import AppContext
from civex.domain.exceptions import NotAllowedError, ValidationError
from civex.domain.permissions import Permissions
from civex.domain.query import RecordQuery


@pytest.fixture()
def survey(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("site", fields=[("name", "string"), ("habitat", "string")])
    make_schema("sample", fields=[("code", "string")], parent="site")
    ctx.schema_svc.add_field("sample", "depth", "integer", restrictions={"max": 100})
    ctx.schema_svc.add_field("sample", "status", "string")
    ctx.commit()
    make_collection("survey")
    site = make_record("survey", "site", {"name": "a"})
    samples = [
        make_record(
            "survey",
            "sample",
            {"code": f"s{i}", "status": "new"},
            parent_record_id=str(site.id),
        )
        for i in range(4)
    ]
    return site, samples


def _ids(records) -> list[str]:
    return [str(r.id) for r in records]


def _data(ctx: AppContext, record) -> dict:
    return ctx.record_svc.get(str(record.id)).data


def test_the_plan_counts_what_would_change_and_the_edit_does_it(
    ctx: AppContext, survey
):
    _, samples = survey
    ctx.record_svc.patch(str(samples[0].id), {"status": "checked"})
    ctx.commit()

    plan = ctx.record_svc.plan_bulk_edit({"status": "checked"}, ids=_ids(samples))
    assert (plan.records, plan.changing, plan.unchanged, plan.skipped) == (4, 3, 1, 0)
    assert plan.can_apply
    assert all(_data(ctx, s)["status"] != "checked" for s in samples[1:])  # no writes

    result = ctx.record_svc.bulk_edit({"status": "checked"}, ids=_ids(samples))
    ctx.commit()
    assert (result.changed, result.unchanged, result.skipped) == (3, 1, 0)
    for sample in samples:
        data = _data(ctx, sample)
        assert data["status"] == "checked"
        assert data["code"].startswith("s")  # the other fields are kept


def test_none_clears_a_field(ctx: AppContext, survey):
    _, samples = survey
    ctx.record_svc.bulk_edit({"status": None}, ids=_ids(samples[:2]))
    ctx.commit()
    assert _data(ctx, samples[0]).get("status") is None
    assert _data(ctx, samples[2])["status"] == "new"
    # Clearing what is already empty changes nothing.
    plan = ctx.record_svc.plan_bulk_edit({"status": None}, ids=_ids(samples[:2]))
    assert (plan.changing, plan.unchanged) == (0, 2)
    assert not plan.can_apply


def test_a_query_chooses_everything_it_lists(ctx: AppContext, survey):
    _, samples = survey
    query = RecordQuery(dataset="survey", schema="sample", where=["status=new"])
    plan = ctx.record_svc.plan_bulk_edit({"status": "done"}, query=query)
    assert plan.changing == 4
    ctx.record_svc.bulk_edit({"status": "done"}, query=query)
    ctx.commit()
    assert {_data(ctx, s)["status"] for s in samples} == {"done"}


def test_a_value_its_field_wont_take_skips_the_records_and_says_why(
    ctx: AppContext, survey
):
    _, samples = survey
    plan = ctx.record_svc.plan_bulk_edit({"depth": 500}, ids=_ids(samples))
    assert (plan.changing, plan.skipped) == (0, 4)
    assert "depth" in plan.skipped_records[0].reason
    assert plan.skipped_records[0].name is not None
    result = ctx.record_svc.bulk_edit({"depth": 500}, ids=_ids(samples))
    ctx.commit()
    assert result.skipped == 4 and result.changed == 0
    assert all(_data(ctx, s).get("depth") is None for s in samples)


def test_a_record_takes_every_change_or_none(ctx: AppContext, survey):
    site, samples = survey
    # A selection over two kinds: only the samples have a 'status' of their own.
    ids = _ids(samples[:2]) + [str(site.id)]
    plan = ctx.record_svc.plan_bulk_edit({"status": "x"}, ids=ids)
    assert (plan.records, plan.changing, plan.skipped) == (3, 2, 1)
    assert "no field 'status'" in plan.skipped_records[0].reason
    # An inherited field's value is on the record above: not edited here.
    plan = ctx.record_svc.plan_bulk_edit({"habitat": "reef"}, ids=_ids(samples))
    assert plan.skipped == 4
    assert "edit the site records" in plan.skipped_records[0].reason


def test_unique_keys_are_held_against_the_project_and_the_edit_itself(
    ctx: AppContext, survey, make_record
):
    site, samples = survey
    ctx.schema_svc.set_unique_keys("sample", [["status", "code"]])
    ctx.schema_svc.set_unique_keys("site", [["name"]])
    ctx.commit()
    make_record("survey", "site", {"name": "b"})
    other = make_record("survey", "site", {"name": "c"})
    # Two sites can't both become "b": one is taken already; and two chosen
    # records can't take the same value as each other either.
    plan = ctx.record_svc.plan_bulk_edit({"name": "b"}, ids=[str(site.id)])
    assert plan.skipped == 1 and "already exists" in plan.skipped_records[0].reason
    plan = ctx.record_svc.plan_bulk_edit(
        {"name": "z"}, ids=[str(site.id), str(other.id)]
    )
    assert (plan.changing, plan.skipped) == (1, 1)
    assert "Another of the chosen records" in plan.skipped_records[0].reason
    result = ctx.record_svc.bulk_edit({"name": "z"}, ids=[str(site.id), str(other.id)])
    ctx.commit()
    assert (result.changed, result.skipped) == (1, 1)
    # Keys the change doesn't make equal are fine.
    plan = ctx.record_svc.plan_bulk_edit({"status": "same"}, ids=_ids(samples))
    assert plan.changing == 4


def test_the_edit_is_one_event_of_updates_in_history(ctx: AppContext, survey):
    _, samples = survey
    ctx.record_svc.bulk_edit({"status": "done"}, ids=_ids(samples))
    ctx.commit()
    event = ctx.history_svc.events(limit=5)[0][0]
    assert event.batch is not None and event.batch.kind == "edit"
    assert event.batch.label == "status"
    entries = ctx.history_svc.page(batch_id=event.batch.id, limit=10)
    assert {e.action for e in entries} == {"update"}
    assert {str(e.entity_id) for e in entries} == set(_ids(samples))


def test_editing_needs_write_records_in_every_collection_involved(
    ctx: AppContext, survey, make_collection, make_record
):
    _, samples = survey
    make_collection("archive")
    make_record("archive", "site", {"name": "elsewhere"})
    elsewhere = ctx.record_svc.find("archive", "site")[0]
    survey_id = ctx.dataset_svc.get("survey").id
    svc = ctx.record_svc
    original = svc._permissions
    try:
        svc._permissions = Permissions.of(
            "read", "write_records", collections=[survey_id]
        )
        assert svc.plan_bulk_edit({"status": "x"}, ids=_ids(samples)).changing == 4
        with pytest.raises(NotAllowedError):
            svc.bulk_edit({"name": "x"}, ids=_ids(samples[:1]) + [str(elsewhere.id)])
    finally:
        svc._permissions = original
    assert _data(ctx, samples[0])["status"] == "new"  # nothing was written


def test_the_plan_counts_the_workflow_runs_it_would_start(ctx: AppContext, survey):
    _, samples = survey
    workflows = ctx.job_svc._civex_dir / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "on_status.yaml").write_text(
        """
name: on_status
triggers:
  record_updated:
    schema: sample
    fields: [status]
steps:
  - id: read
    plugin: civex.get_field
    config:
      field: status
"""
    )
    plan = ctx.record_svc.plan_bulk_edit({"status": "done"}, ids=_ids(samples))
    assert (plan.runs, plan.workflows) == (4, ["on_status"])
    assert ctx.job_svc.count_jobs() == 0  # counted, not queued
    # A field the trigger doesn't watch starts nothing.
    assert ctx.record_svc.plan_bulk_edit({"code": "q"}, ids=_ids(samples)).runs == 0

    result = ctx.record_svc.bulk_edit({"status": "done"}, ids=_ids(samples))
    ctx.commit()
    assert result.runs == 4 == ctx.job_svc.count_jobs()

    ctx.job_svc.stop_all()
    plan = ctx.record_svc.plan_bulk_edit({"status": "again"}, ids=_ids(samples))
    assert plan.runs == 0 and plan.automation_paused


def test_nothing_to_change_is_refused(ctx: AppContext, survey):
    _, samples = survey
    with pytest.raises(ValidationError):
        ctx.record_svc.plan_bulk_edit({}, ids=_ids(samples))
    with pytest.raises(ValidationError):
        ctx.record_svc.plan_bulk_edit({"status": "x"})


def _queries(ctx: AppContext, fn) -> int:
    from sqlalchemy import event

    count = {"n": 0}
    engine = ctx._session.get_bind()

    def bump(*_args, **_kwargs):
        count["n"] += 1

    event.listen(engine, "before_cursor_execute", bump)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", bump)
    return count["n"]


def test_planning_a_bulk_edit_costs_the_same_however_many_records(
    ctx: AppContext, make_schema, make_collection, make_record
):
    """The plan reads the records a page at a time and resolves each schema
    once; checking a record's values costs nothing more per record unless a
    rule needs the database (a reference, a unique key). Saving costs a fixed
    few queries per record: the save itself, its history and its triggers."""
    make_schema("trial", fields=[("subject", "string"), ("status", "string")])
    make_collection("study")

    def ids(n: int) -> list[str]:
        made = [make_record("study", "trial", {"subject": f"t{i}"}) for i in range(n)]
        return [str(r.id) for r in made]

    small, big = ids(3), ids(30)
    small_plan = _queries(
        ctx, lambda: ctx.record_svc.plan_bulk_edit({"status": "a"}, ids=small)
    )
    big_plan = _queries(
        ctx, lambda: ctx.record_svc.plan_bulk_edit({"status": "a"}, ids=big)
    )
    assert big_plan == small_plan <= 6

    small_edit = _queries(
        ctx, lambda: ctx.record_svc.bulk_edit({"status": "a"}, ids=small)
    )
    big_edit = _queries(ctx, lambda: ctx.record_svc.bulk_edit({"status": "a"}, ids=big))
    ctx.commit()
    per_record = (big_edit - small_edit) / (len(big) - len(small))
    # The save (a read, the write, its file and reference catalogs) and its
    # history entry: five, as for any one edit.
    assert per_record <= 5.5
