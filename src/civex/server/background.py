from __future__ import annotations

import contextlib
import io
import logging


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
    from civex.plugins import registry as plugin_registry
    from civex.plugins.base import WorkflowContext
    from civex.workflows import executor

    try:
        config = load_config()
    except ConfigError:
        return

    ctx = build_local_context(config)
    try:
        plugin_registry.discover_user_plugins(config.civex_dir / "plugins")
        plugins = plugin_registry.all_plugins()
        while True:
            job = ctx.job_svc.claim_pending()
            if job is None:
                break
            log_buf = io.StringIO()
            try:
                with _capture_output() as log_buf:
                    wf_def = ctx.job_svc.find_workflow(job.workflow_name)
                    if wf_def is None:
                        raise ValueError(f"Workflow '{job.workflow_name}' not found")
                    record = ctx.record_svc.get(str(job.record_id))
                    dataset = ctx.dataset_svc._datasets.get_by_id(record.dataset_id)
                    if dataset is None:
                        raise ValueError("Dataset for record not found")
                    wf_ctx = WorkflowContext(
                        record=record,
                        dataset=dataset,
                        _app_ctx=ctx,
                        job_depth=job.depth,
                    )
                    initial_outputs = job.input_data or None
                    executor.run(
                        wf_def, wf_ctx, plugins, initial_outputs=initial_outputs
                    )
                ctx.job_svc.mark_completed(job.id, log=log_buf.getvalue() or None)
                ctx.commit()
            except Exception as e:
                ctx.job_svc.mark_failed(job.id, str(e), log=log_buf.getvalue() or None)
                ctx.commit()
    finally:
        ctx.close()
