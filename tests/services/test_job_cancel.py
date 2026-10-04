"""Cancelling runs: the repository operations and the service rules behind Stop."""

from __future__ import annotations

import uuid

import pytest

from civex.context import AppContext
from civex.domain.exceptions import NotFoundError, ValidationError


@pytest.fixture()
def record(ctx: AppContext, make_schema, make_collection):
    make_schema("doc", fields=[("title", "string")])
    make_collection("study")
    rec = ctx.record_svc.add("study", "doc", {"title": "x"})
    ctx.commit()
    return rec


def _job(ctx: AppContext, record):
    job = ctx.job_svc.enqueue_manual("wf", record)
    ctx.commit()
    return job


def test_a_waiting_run_that_is_cancelled_never_starts(ctx, record) -> None:
    job = _job(ctx, record)

    cancelled = ctx.job_svc.cancel_job(job.id)

    assert cancelled.status == "cancelled" and cancelled.finished_at is not None
    assert ctx.job_svc.claim_pending() is None


def test_claiming_takes_each_waiting_run_once_oldest_first(ctx, record) -> None:
    first, second = _job(ctx, record), _job(ctx, record)

    a = ctx.job_svc.claim_pending()
    b = ctx.job_svc.claim_pending()

    assert a is not None and b is not None
    assert [a.id, b.id] == [first.id, second.id]
    assert ctx.job_svc.claim_pending() is None
    assert a.status == "running" and a.started_at is not None


def test_a_running_run_sees_that_it_was_cancelled(ctx, record) -> None:
    _job(ctx, record)
    running = ctx.job_svc.claim_pending()
    assert running is not None
    assert ctx.job_svc.should_stop(running.id) is False

    ctx.job_svc.cancel_job(running.id)
    ctx.commit()

    assert ctx.job_svc.should_stop(running.id) is True


def test_a_run_cancelled_on_its_last_step_stays_cancelled(ctx, record) -> None:
    _job(ctx, record)
    running = ctx.job_svc.claim_pending()
    assert running is not None
    ctx.job_svc.cancel_job(running.id)

    # The worker finishes anyway and reports success: that mustn't undo the cancel.
    ctx.job_svc.mark_completed(running.id, log="done", step_executions=[])
    ctx.commit()

    after = ctx.job_svc.get_job(running.id)
    assert after is not None and after.status == "cancelled"
    assert after.log == "done"  # but what it did is kept


def test_a_cancelled_run_keeps_the_steps_it_got_through(ctx, record) -> None:
    _job(ctx, record)
    running = ctx.job_svc.claim_pending()
    assert running is not None
    step = {
        "step_id": "s1",
        "plugin": "civex.get_field",
        "status": "success",
        "inputs": {},
        "outputs": {},
        "duration_seconds": 0.1,
        "depends_on": [],
    }

    ctx.job_svc.mark_cancelled(running.id, step_executions=[step])
    ctx.commit()

    after = ctx.job_svc.get_job(running.id)
    assert after is not None and after.status == "cancelled"
    assert [s["step_id"] for s in after.step_executions or []] == ["s1"]


def test_a_finished_run_is_left_alone_by_cancel(ctx, record) -> None:
    _job(ctx, record)
    job = ctx.job_svc.claim_pending()
    assert job is not None
    ctx.job_svc.mark_completed(job.id)
    ctx.commit()

    assert ctx.job_svc.cancel_job(job.id).status == "completed"


def test_cancelling_an_unknown_run_is_not_found(ctx) -> None:
    with pytest.raises(NotFoundError):
        ctx.job_svc.cancel_job(uuid.uuid4())


def test_stop_pauses_and_cancels_everything_active(ctx, record) -> None:
    waiting = _job(ctx, record)
    _job(ctx, record)
    running = ctx.job_svc.claim_pending()  # the oldest becomes the running one
    assert running is not None and running.id == waiting.id

    assert ctx.job_svc.stop_all() == 2
    ctx.commit()

    state = ctx.job_svc.automation_state()
    assert state == {"paused": True, "pending": 0, "running": 0, "batch": None}
    assert ctx.job_svc.should_stop(running.id) is True  # the running one stops


def test_pausing_closes_every_gate_and_resume_opens_them(ctx, record) -> None:
    ctx.job_svc.stop_all()
    assert ctx.job_svc.is_paused() is True
    assert ctx.job_svc.trigger_for_record(record, "record_updated") == []
    with pytest.raises(ValidationError, match="paused"):
        ctx.job_svc.enqueue_manual("wf", record)
    assert ctx.job_svc.claim_pending() is None

    ctx.job_svc.resume()

    assert ctx.job_svc.is_paused() is False
    assert ctx.job_svc.enqueue_manual("wf", record).status == "pending"
