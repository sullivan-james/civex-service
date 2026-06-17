from __future__ import annotations

import typer

from civex.config import Config, load_config
from civex.console import console
from civex.context import AppContext, build_local_context
from civex.domain.dtos import WorkflowJobDTO
from civex.domain.exceptions import ConfigError


def cli_load_config() -> Config:
    try:
        return load_config()
    except ConfigError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


def get_ctx() -> AppContext:
    return build_local_context(cli_load_config())


def run_job(job: WorkflowJobDTO, ctx: AppContext) -> tuple[None, str]:
    """Execute one workflow job. Returns captured log output. Raises on failure."""
    import contextlib
    import io
    import logging as _logging

    from civex.plugins import registry as plugin_registry
    from civex.plugins.base import WorkflowContext
    from civex.workflows import executor

    config = cli_load_config()
    plugin_registry.discover_user_plugins(config.civex_dir / "plugins")
    plugins = plugin_registry.all_plugins()

    wf_def = ctx.job_svc.find_workflow(job.workflow_name)
    if wf_def is None:
        raise ValueError(f"Workflow '{job.workflow_name}' not found in .civex/workflows/")

    record = ctx.record_svc.get(str(job.record_id))
    dataset = ctx.dataset_svc._datasets.get_by_id(record.dataset_id)
    if dataset is None:
        raise ValueError(f"Dataset for record '{job.record_id}' not found")

    _NOISY = ("sqlalchemy", "uvicorn", "fastapi", "httpx", "asyncio", "urllib3", "watchfiles", "h11")

    buf = io.StringIO()
    handler = _logging.StreamHandler(buf)
    handler.setLevel(_logging.DEBUG)
    handler.setFormatter(_logging.Formatter("%(levelname)-8s %(name)s: %(message)s"))
    handler.addFilter(type("F", (_logging.Filter,), {"filter": staticmethod(lambda r: not any(r.name.startswith(p) for p in _NOISY))})())
    root = _logging.getLogger()
    prev_level = root.level
    root.addHandler(handler)
    root.setLevel(min(prev_level, _logging.DEBUG))
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            wf_ctx = WorkflowContext(record=record, dataset=dataset, _app_ctx=ctx)
            executor.run(wf_def, wf_ctx, plugins, initial_outputs=job.input_data or None)
    finally:
        root.removeHandler(handler)
        root.setLevel(prev_level)

    return None, buf.getvalue()


def drain_jobs(ctx: AppContext) -> None:
    """Run all pending jobs inline. Prints a line per job."""
    while True:
        job = ctx.job_svc.claim_pending()
        if job is None:
            break
        console.print(f"  [dim]→ workflow '{job.workflow_name}' (trigger: {job.trigger})[/dim]")
        try:
            _, log = run_job(job, ctx)
            ctx.job_svc.mark_completed(job.id, log=log or None)
            ctx.commit()
            console.print("    [success]✓ done[/success]")
        except Exception as e:
            ctx.job_svc.mark_failed(job.id, str(e))
            ctx.commit()
            console.print(f"    [error]✗ {e}[/error]")
