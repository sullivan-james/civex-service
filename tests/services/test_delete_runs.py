"""Deleting runs: a waiting one never starts, a running one stops before its
next step, a finished one goes with its step log."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from civex.context import AppContext


def _record(ctx: AppContext, make_schema, make_collection):
    make_schema("doc", fields=[("subject", "string")])
    make_collection("study")
    ctx.dataset_svc.update("study", schemas=["doc"])
    return ctx.record_svc.add("study", "doc", {"subject": "x"})


def test_a_deleted_waiting_run_never_starts(ctx: AppContext, make_schema, make_collection):
    record = _record(ctx, make_schema, make_collection)
    first = ctx.job_svc.enqueue_manual("tidy", record)
    second = ctx.job_svc.enqueue_manual("tidy", record)
    ctx.commit()

    assert ctx.job_svc.delete_runs([first.id, first.id]) == 1
    ctx.commit()
    claimed = ctx.job_svc.claim_pending()
    assert claimed is not None and claimed.id == second.id
    assert ctx.job_svc.claim_pending() is None
    assert ctx.job_svc.get_job(first.id) is None


def test_a_deleted_running_run_stops_and_its_report_is_dropped(
    ctx: AppContext, make_schema, make_collection
):
    record = _record(ctx, make_schema, make_collection)
    ctx.job_svc.enqueue_manual("tidy", record)
    ctx.commit()
    running = ctx.job_svc.claim_pending()
    assert running is not None and not ctx.job_svc.should_stop(running.id)

    ctx.job_svc.delete_runs([running.id])
    ctx.commit()
    assert ctx.job_svc.should_stop(running.id)
    ctx.job_svc.mark_completed(  # what the worker does at the end: nothing left
        running.id,
        step_executions=[
            {"step_id": "a", "plugin": "civex.noop", "status": "completed"}
        ],
    )
    ctx.commit()
    assert ctx.job_svc.get_job(running.id) is None


def test_a_finished_run_goes_with_its_steps(
    ctx: AppContext, make_schema, make_collection
):
    record = _record(ctx, make_schema, make_collection)
    job = ctx.job_svc.enqueue_manual("tidy", record)
    ctx.commit()
    ctx.job_svc.mark_completed(
        job.id,
        step_executions=[
            {"step_id": "a", "plugin": "civex.noop", "status": "completed"}
        ],
    )
    ctx.commit()
    assert ctx.job_svc.delete_runs([job.id]) == 1
    ctx.commit()
    assert ctx.job_svc.list_jobs() == []


def test_runs_are_deleted_over_http(
    client: TestClient, ctx: AppContext, make_schema, make_collection
):
    record = _record(ctx, make_schema, make_collection)
    jobs = [ctx.job_svc.enqueue_manual("tidy", record) for _ in range(3)]
    ctx.commit()

    reply = client.post("/api/jobs/delete", json={"ids": [str(jobs[0].id)]})
    assert reply.json() == {"deleted": 1}
    assert client.delete(f"/api/jobs/{jobs[1].id}").status_code == 204
    assert client.delete(f"/api/jobs/{uuid.uuid4()}").status_code == 404
    reply = client.post(
        "/api/jobs/delete",
        json={"filter": {"field": "status", "op": "eq", "value": "pending"}},
    )
    assert reply.json() == {"deleted": 1}
    assert client.post("/api/jobs/delete", json={}).status_code == 422
