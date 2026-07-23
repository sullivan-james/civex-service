"""Per-step execution records (CIVEX-117): `executor.run()` already knew each
step's resolved inputs, outputs, and duration in memory -- these assert that
data is actually returned/persisted, not just computed and discarded, mirroring
how test_error_envelope.py asserts the envelope reaches the job record rather
than just the exception.
"""

from __future__ import annotations

import yaml

from civex.plugins.base import WorkflowContext
from civex.plugins.registry import all_plugins
from civex.workflows import executor
from civex.workflows.definition import WorkflowDef


def test_run_returns_a_success_record_per_step(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("doc", fields=[("name", "string")])
    record = make_record("study", "doc", {"name": "alice"})
    wf_ctx = WorkflowContext(record=record, dataset=dataset, _app_ctx=ctx)

    wf = WorkflowDef.model_validate(
        yaml.safe_load("""
name: wf
steps:
  - id: read
    plugin: civex.get_field
    config: {field: name}
""")
    )

    step_executions = executor.run(wf, wf_ctx, all_plugins())

    assert step_executions == [
        {
            "step_id": "read",
            "plugin": "civex.get_field",
            "status": "success",
            "inputs": {},
            "outputs": {"value": "alice"},
            "duration_seconds": step_executions[0]["duration_seconds"],
            "error": None,
        }
    ]
    assert step_executions[0]["duration_seconds"] >= 0.0


def test_run_records_a_skipped_step(ctx, make_collection, make_schema, make_record):
    dataset = make_collection("study")
    make_schema("doc", fields=[("name", "string")])
    record = make_record("study", "doc", {"name": "alice"})
    wf_ctx = WorkflowContext(record=record, dataset=dataset, _app_ctx=ctx)

    wf = WorkflowDef.model_validate(
        yaml.safe_load("""
name: wf
steps:
  - id: read
    plugin: civex.get_field
    config: {field: name}
    if: "1 == 2"
""")
    )

    step_executions = executor.run(wf, wf_ctx, all_plugins())

    assert step_executions == [
        {
            "step_id": "read",
            "plugin": "civex.get_field",
            "status": "skipped",
            "inputs": {},
            "outputs": None,
            "duration_seconds": 0.0,
            "error": None,
        }
    ]


def test_a_failing_step_attaches_partial_records_to_the_exception(
    ctx, make_collection, make_schema, make_record
):
    dataset = make_collection("study")
    make_schema("doc", fields=[("name", "string"), ("attachment", "file")])
    record = make_record("study", "doc", {"name": "alice"})
    wf_ctx = WorkflowContext(record=record, dataset=dataset, _app_ctx=ctx)

    wf = WorkflowDef.model_validate(
        yaml.safe_load("""
name: wf
steps:
  - id: read
    plugin: civex.get_field
    config: {field: name}
  - id: load-the-attachment
    plugin: civex.load_file
    config: {field: attachment}
""")
    )

    try:
        executor.run(wf, wf_ctx, all_plugins())
        assert False, "expected the second step to raise"
    except Exception as e:
        recorded = e.step_executions  # type: ignore[attr-defined]

    assert [r["step_id"] for r in recorded] == ["read", "load-the-attachment"]
    assert recorded[0]["status"] == "success"
    assert recorded[1]["status"] == "failed"
    assert recorded[1]["outputs"] is None
    assert recorded[1]["error"]


def test_drain_jobs_persists_step_executions_on_a_completed_job(
    ctx, make_collection, make_schema, make_record
):
    from civex.cli.utils import drain_jobs

    dataset = make_collection("study")
    make_schema("doc", fields=[("name", "string")])
    record = make_record("study", "doc", {"name": "alice"})

    wf_dir = ctx.workflow_svc._dir
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "fine.yaml").write_text("""
name: fine
steps:
  - id: read
    plugin: civex.get_field
    config: {field: name}
""")
    job = ctx.job_svc.enqueue_manual("fine", record)
    ctx.commit()

    drain_jobs(ctx)

    finished = ctx.job_svc.get_job(job.id)
    assert finished is not None
    assert finished.status == "completed"
    assert finished.step_executions == [
        {
            "step_id": "read",
            "plugin": "civex.get_field",
            "status": "success",
            "inputs": {},
            "outputs": {"value": "alice"},
            "duration_seconds": finished.step_executions[0]["duration_seconds"],
            "error": None,
        }
    ]


def test_drain_jobs_persists_partial_step_executions_on_a_failed_job(
    ctx, make_collection, make_schema, make_record
):
    from civex.cli.utils import drain_jobs

    dataset = make_collection("study")
    make_schema("doc", fields=[("attachment", "file")])
    record = make_record("study", "doc", {})

    wf_dir = ctx.workflow_svc._dir
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "failing.yaml").write_text("""
name: failing
steps:
  - id: load-the-attachment
    plugin: civex.load_file
    config: {field: attachment}
""")
    job = ctx.job_svc.enqueue_manual("failing", record)
    ctx.commit()

    drain_jobs(ctx)

    failed = ctx.job_svc.get_job(job.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.step_executions is not None
    assert len(failed.step_executions) == 1
    assert failed.step_executions[0]["status"] == "failed"
    assert failed.step_executions[0]["step_id"] == "load-the-attachment"
