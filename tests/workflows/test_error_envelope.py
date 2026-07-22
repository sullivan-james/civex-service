"""The structured error envelope (CIVEX-143): one {kind, message, retryable,
step} shape for a failed step, whether it failed in-process or out.

The point of the story is that nothing downstream can tell which tier a
failure came from, so these assert the envelope reaching the *job record* --
the place a user or a future retry policy actually reads it -- rather than
just the shape of the exception.
"""

from __future__ import annotations

import pytest
import yaml

from civex.domain.dtos import ErrorEnvelope
from civex.domain.exceptions import (
    CapabilityDeniedError,
    PluginExecutionError,
    PluginTimeoutError,
    ValidationError,
)
from civex.plugins.base import WorkflowContext
from civex.plugins.registry import all_plugins
from civex.workflows import executor
from civex.workflows.definition import WorkflowDef


def test_unclassified_exception_is_never_reported_as_retryable():
    """A bare ValueError from a built-in carries no classification. Guessing
    "retryable" for it is how a permanently broken step gets re-run
    forever."""
    envelope = ErrorEnvelope.from_exception(ValueError("boom"), step="one")
    assert envelope.kind == "plugin_error"
    assert envelope.retryable is False
    assert envelope.message == "boom"
    assert envelope.step == "one"


def test_timeout_is_the_one_plugin_failure_classed_retryable():
    """A blown wall-clock budget is about the machine, not the code -- unlike
    every other plugin failure class, the same run can succeed next time."""
    assert (
        ErrorEnvelope.from_exception(PluginTimeoutError("too slow")).retryable is True
    )
    assert (
        ErrorEnvelope.from_exception(PluginTimeoutError("too slow")).kind == "timeout"
    )


@pytest.mark.parametrize(
    "exc,kind",
    [
        (CapabilityDeniedError("get_file"), "capability_denied"),
        (ValidationError("bad field"), "validation_error"),
        (PluginExecutionError("crashed"), "plugin_error"),
        (
            PluginExecutionError("rate limited", kind="rate_limited", retryable=True),
            "rate_limited",
        ),
    ],
)
def test_domain_exceptions_classify_themselves(exc, kind):
    assert ErrorEnvelope.from_exception(exc).kind == kind


def test_a_plugin_declared_retryable_flag_is_believed():
    """Only the plugin knows whether its own failure was transient, so a
    subprocess plugin saying retryable=True is passed through, not
    re-derived."""
    exc = PluginExecutionError("upstream 503", kind="upstream_error", retryable=True)
    assert ErrorEnvelope.from_exception(exc).retryable is True


def test_envelope_survives_a_dict_round_trip():
    envelope = ErrorEnvelope(
        kind="timeout", message="too slow", retryable=True, step="parse"
    )
    assert ErrorEnvelope.from_dict(envelope.to_dict()) == envelope


def test_executor_names_the_step_that_failed(
    ctx, make_collection, make_schema, make_record
):
    """A job error that doesn't say which step failed is close to useless in
    a multi-step workflow, and the executor is the only layer that knows."""
    dataset = make_collection("study")
    make_schema("doc", fields=[("attachment", "file")])
    record = make_record("study", "doc", {})
    wf_ctx = WorkflowContext(record=record, dataset=dataset, _app_ctx=ctx)

    # load_file raises because the field is unset on the record.
    wf = WorkflowDef.model_validate(
        yaml.safe_load("""
name: wf
steps:
  - id: load-the-attachment
    plugin: civex.load_file
    config: {field: attachment}
""")
    )

    with pytest.raises(Exception) as excinfo:
        executor.run(wf, wf_ctx, all_plugins())

    envelope = excinfo.value.envelope
    assert envelope.step == "load-the-attachment"
    assert envelope.kind == "plugin_error"
    assert envelope.retryable is False


def test_failed_job_records_the_envelope_alongside_the_message(
    ctx, make_collection, make_schema, make_record
):
    """End to end: a built-in raising in-process lands on the job as both the
    human-readable message it always was and the structured form anything
    wanting to branch on the failure can read."""
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
    assert failed.error  # unchanged: still the plain message
    assert failed.error_details == {
        "kind": "plugin_error",
        "message": failed.error,
        "retryable": False,
        "step": "load-the-attachment",
    }


def test_successful_job_records_no_error_details(
    ctx, make_collection, make_schema, make_record
):
    from civex.cli.utils import drain_jobs

    dataset = make_collection("study")
    make_schema("doc", fields=[("name", "string")])
    record = make_record("study", "doc", {"name": "x"})

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
    assert finished.error_details is None
