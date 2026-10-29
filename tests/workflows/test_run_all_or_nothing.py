"""A run's writes are kept when it gets to the end and all undone when a step
fails (`AppContext.all_or_nothing`, used by both drains); a run stopped on
purpose keeps what it got through. Plugins don't commit."""

from __future__ import annotations

import pytest

WORKFLOW = """
name: half
steps:
  - id: read
    plugin: civex.get_field
    config: {field: source}
  - id: save
    plugin: civex.save_field
    config: {field: title}
    inputs: {value: read.value}
  - id: then-fail
    plugin: civex.load_file
    if: "read.value == 'after'"
    config: {field: attachment}
"""

WORKS = """
name: whole
steps:
  - id: read
    plugin: civex.get_field
    config: {field: source}
  - id: save
    plugin: civex.save_field
    config: {field: title}
    inputs: {value: read.value}
"""


@pytest.fixture
def record(ctx, make_collection, make_schema, make_record):
    make_collection("study")
    make_schema(
        "doc",
        fields=[("title", "string"), ("source", "string"), ("attachment", "file")],
    )
    rec = make_record("study", "doc", {"title": "before", "source": "after"})
    wf_dir = ctx.workflow_svc._dir
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "half.yaml").write_text(WORKFLOW)
    (wf_dir / "whole.yaml").write_text(WORKS)
    ctx.commit()
    return rec


def _title(ctx, record) -> str:
    ctx.rollback()  # read what was committed, not what this session holds
    return ctx.record_svc.get(str(record.id)).data["title"]


@pytest.mark.parametrize("drain", ["cli", "server"])
def test_a_failed_run_keeps_nothing_it_wrote(ctx, record, drain) -> None:
    job = ctx.job_svc.enqueue_manual("half", record)
    ctx.commit()

    _drain(ctx, drain)

    job = ctx.job_svc.get_job(job.id)
    assert job.status == "failed"
    assert job.error_details["step"] == "then-fail"
    ran = [s["step_id"] for s in job.step_executions]
    assert ran == ["read", "save", "then-fail"]  # the save happened, then was undone
    assert _title(ctx, record) == "before"
    assert not job.affected_records
    if drain == "server":
        assert "Nothing this run changed was kept" in (job.log or "")


@pytest.mark.parametrize("drain", ["cli", "server"])
def test_a_run_that_gets_to_the_end_keeps_its_writes(ctx, record, drain) -> None:
    job = ctx.job_svc.enqueue_manual("whole", record)
    ctx.commit()

    _drain(ctx, drain)

    done = ctx.job_svc.get_job(job.id)
    assert done.status == "completed", (done.error, done.log)
    assert _title(ctx, record) == "after"


def _drain(ctx, drain: str) -> None:
    if drain == "cli":
        from civex.cli.utils import drain_jobs

        drain_jobs(ctx)
    else:
        from civex.server.background import run_pending_jobs

        run_pending_jobs(lambda: _Unclosable(ctx))


class _Unclosable:
    """The test's own context, handed to the server drain (which closes the
    context it is given) without being closed."""

    def __init__(self, ctx) -> None:
        self._ctx = ctx

    def __getattr__(self, name):
        if name == "close":
            return lambda: None
        return getattr(self._ctx, name)
