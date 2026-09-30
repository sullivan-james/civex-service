"""WorkflowJobService's affected_records plumbing: mark_completed/mark_failed
persist the records a run touched, and list_jobs/count_jobs can filter by
affected_record_id -- the reverse direction of the run/record audit trail
(record_id filters by trigger; affected_record_id filters by what the run
wrote), so a record's detail page can show the runs that touched it, not
just the run it triggered.
"""

from __future__ import annotations

from civex.context import AppContext
from civex.domain.dtos import ErrorEnvelope


def test_mark_completed_persists_affected_records(
    ctx: AppContext, make_collection, make_schema, make_record
) -> None:
    make_collection("study")
    make_schema("subject", fields=[])
    record = make_record("study", "subject", {})
    job = ctx.job_svc.enqueue_manual("noop", record)
    ctx.commit()

    affected = [
        {
            "record_id": "11111111-1111-1111-1111-111111111111",
            "schema_name": "sample",
            "natural_name": "S01",
            "action": "created",
        }
    ]
    ctx.job_svc.mark_completed(job.id, affected_records=affected)
    ctx.commit()

    fetched = ctx.job_svc.get_job(job.id)
    assert fetched.affected_records == affected


def test_mark_failed_persists_partial_affected_records(
    ctx: AppContext, make_collection, make_schema, make_record
) -> None:
    make_collection("study")
    make_schema("subject", fields=[])
    record = make_record("study", "subject", {})
    job = ctx.job_svc.enqueue_manual("noop", record)
    ctx.commit()

    affected = [
        {
            "record_id": "22222222-2222-2222-2222-222222222222",
            "schema_name": "sample",
            "natural_name": "S02",
            "action": "created",
        }
    ]
    ctx.job_svc.mark_failed(
        job.id,
        ErrorEnvelope(kind="plugin_error", message="boom"),
        affected_records=affected,
    )
    ctx.commit()

    fetched = ctx.job_svc.get_job(job.id)
    assert fetched.affected_records == affected


def test_list_and_count_jobs_filter_by_affected_record_id(
    ctx: AppContext, make_collection, make_schema, make_record
) -> None:
    make_collection("study")
    make_schema("subject", fields=[])
    trigger_a = make_record("study", "subject", {})
    trigger_b = make_record("study", "subject", {})
    touched_id = "33333333-3333-3333-3333-333333333333"

    job_a = ctx.job_svc.enqueue_manual("noop", trigger_a)
    job_b = ctx.job_svc.enqueue_manual("noop", trigger_b)
    ctx.commit()

    ctx.job_svc.mark_completed(
        job_a.id,
        affected_records=[
            {
                "record_id": touched_id,
                "schema_name": "sample",
                "natural_name": "S03",
                "action": "created",
            }
        ],
    )
    ctx.job_svc.mark_completed(job_b.id, affected_records=None)
    ctx.commit()

    matching = ctx.job_svc.list_jobs(affected_record_id=touched_id)
    assert [j.id for j in matching] == [job_a.id]
    assert ctx.job_svc.count_jobs(affected_record_id=touched_id) == 1

    assert ctx.job_svc.count_jobs(affected_record_id="does-not-exist") == 0


def test_jobs_are_filterable_by_affected_schema(
    ctx: AppContext, make_schema, make_collection, make_record
) -> None:
    """mark_completed/mark_failed mirror the schema names in affected_records
    into job_affected_schemas (real FKs, indexed), so "jobs that wrote to
    schema X" is a join instead of a JSON scan."""
    make_schema("doc")
    make_schema("other")
    make_collection("study")
    record = make_record("study", "doc")

    touched = ctx.job_svc.enqueue_manual("wf", record)
    untouched = ctx.job_svc.enqueue_manual("wf", record)
    failed = ctx.job_svc.enqueue_manual("wf", record)
    ctx.commit()
    entry = {"record_id": "x", "schema_name": "other", "natural_name": "n", "action": "created"}
    ctx.job_svc.mark_completed(touched.id, affected_records=[entry])
    ctx.job_svc.mark_completed(untouched.id, affected_records=[])
    ctx.job_svc.mark_failed(
        failed.id,
        ErrorEnvelope(kind="plugin_error", message="boom"),
        affected_records=[entry],
    )
    ctx.commit()

    found = ctx.job_svc.list_jobs(affected_schema="other")
    assert {j.id for j in found} == {touched.id, failed.id}  # partial work counts
    assert ctx.job_svc.count_jobs(affected_schema="other") == 2
    assert ctx.job_svc.count_jobs(affected_schema="doc") == 0
