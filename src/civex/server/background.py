from __future__ import annotations

import contextlib
import io
import logging

log = logging.getLogger(__name__)


_NOISY_PREFIXES = (
    "sqlalchemy",
    "uvicorn",
    "fastapi",
    "httpx",
    "asyncio",
    "urllib3",
    "watchfiles",
    "h11",
)


class _WorkflowLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not any(record.name.startswith(p) for p in _NOISY_PREFIXES)


@contextlib.contextmanager
def _capture_output():
    """Capture stdout, stderr, and non-noisy log records into a single buffer."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(levelname)-8s %(name)s: %(message)s"))
    handler.addFilter(_WorkflowLogFilter())
    root = logging.getLogger()
    prev_level = root.level
    root.addHandler(handler)
    root.setLevel(min(prev_level, logging.DEBUG))
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            yield buf
    finally:
        root.removeHandler(handler)
        root.setLevel(prev_level)


def run_pending_jobs() -> None:
    """Drain the job queue. Safe to call as a FastAPI BackgroundTask."""
    from civex.config import ConfigError, load_config
    from civex.context import build_local_context
    from civex.domain.dtos import ErrorEnvelope
    from civex.domain.exceptions import JobCancelled, NotFoundError
    from civex.plugins import registry as plugin_registry
    from civex.plugins.base import WorkflowContext
    from civex.workflows import executor

    try:
        config = load_config()
    except ConfigError:
        return

    ctx = build_local_context(config)
    try:
        while True:
            job = ctx.job_svc.claim_pending()
            if job is None:
                break
            log_buf = io.StringIO()
            wf_ctx = None
            step_executions = None
            failure: Exception | None = None
            try:
                with _capture_output() as log_buf:
                    # Discovery runs inside the log-capture block (rather
                    # than once up front) so a broken plugin file's
                    # log.warning() -- which file failed and why -- lands in
                    # this job's log instead of vanishing into the process's
                    # own stderr (CIVEX-112).
                    plugin_registry.discover_user_plugins(config.civex_dir / "plugins")
                    plugins = plugin_registry.all_plugins()
                    wf_def = ctx.job_svc.find_workflow(job.workflow_name)
                    if wf_def is None:
                        raise ValueError(f"Workflow '{job.workflow_name}' not found")
                    try:
                        record = ctx.record_svc.get(str(job.record_id))
                    except NotFoundError:
                        raise ValueError(
                            f"The record this run was for ({str(job.record_id)[:8]}…) "
                            "is deleted or no longer exists, so the run can't start."
                        ) from None
                    dataset = ctx.dataset_svc._datasets.get_by_id(record.dataset_id)
                    if dataset is None:
                        raise ValueError("Dataset for record not found")
                    wf_ctx = WorkflowContext(
                        record=record,
                        dataset=dataset,
                        _app_ctx=ctx,
                        job_depth=job.depth,
                        job_id=str(job.id),
                        workflow_name=job.workflow_name,
                    )
                    initial_outputs = job.input_data or None
                    # Whatever the run writes is one event in history.
                    with ctx.history_svc.batch(
                        "workflow", job.workflow_name, str(job.id)
                    ):
                        step_executions = executor.run(
                            wf_def,
                            wf_ctx,
                            plugins,
                            initial_outputs=initial_outputs,
                            default_timeout_seconds=config.plugins.default_timeout_seconds,
                            should_stop=lambda: ctx.job_svc.should_stop(job.id),
                        )
            except Exception as e:
                # executor.run() attaches the envelope (with the failing step
                # id) to whatever it re-raises; anything raised before the
                # first step -- a missing workflow or record -- is classified
                # here instead, where there's no step to name. Same for
                # step_executions (CIVEX-117): None if nothing ran yet.
                # wf_ctx is None for that same before-any-step case, since it
                # isn't built until the record/dataset/workflow are resolved.
                failure = e

            # Persisting the outcome is a separate try/except from running
            # the workflow above: a DB error here (e.g. a dropped
            # connection) must not get mislabeled as this job's own
            # failure, and must not silently kill the drain loop -- a
            # background task's exception is otherwise only ever visible as
            # a raw traceback in the server log, with every job still
            # pending after it left unprocessed until the next manual
            # drain (CIVEX-296 stability review).
            try:
                if isinstance(failure, JobCancelled):
                    # Stopped on purpose: keep what it got done.
                    ctx.job_svc.mark_cancelled(
                        job.id,
                        log=log_buf.getvalue() or None,
                        step_executions=getattr(failure, "step_executions", None),
                        affected_records=wf_ctx.affected_records if wf_ctx else None,
                    )
                elif failure is None:
                    ctx.job_svc.mark_completed(
                        job.id,
                        log=log_buf.getvalue() or None,
                        step_executions=step_executions,
                        affected_records=wf_ctx.affected_records if wf_ctx else [],
                    )
                else:
                    envelope = getattr(
                        failure, "envelope", None
                    ) or ErrorEnvelope.from_exception(failure)
                    ctx.job_svc.mark_failed(
                        job.id,
                        envelope,
                        log=log_buf.getvalue() or None,
                        step_executions=getattr(failure, "step_executions", None),
                        affected_records=wf_ctx.affected_records if wf_ctx else None,
                    )
                ctx.commit()
            except Exception:
                log.exception(
                    "Failed to persist the outcome of job %s -- stopping "
                    "this drain pass. The job will be retried on the next "
                    "drain.",
                    job.id,
                )
                break
    finally:
        ctx.close()
