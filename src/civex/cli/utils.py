from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from civex.config import Config, load_config
from civex.console import console
from civex.domain.dtos import ErrorEnvelope, WorkflowJobDTO
from civex.domain.exceptions import ConfigError, JobCancelled

if TYPE_CHECKING:
    from civex.context import AppContext


def _ensure_container_ready(project_name: str) -> None:
    """
    Pre-flight check for docker-managed projects, called before any CLI
    command that needs a working DB connection. Auto-starts a stopped
    container; prints a clear, actionable message and exits if the
    container — or worse, its data volume — is gone.
    """
    from civex.docker_manager import ContainerRecoveryOutcome, ensure_container_running

    result = ensure_container_running(project_name)
    name = result.container_name

    if result.outcome in (
        ContainerRecoveryOutcome.READY,
        ContainerRecoveryOutcome.DOCKER_UNAVAILABLE,
    ):
        # READY: nothing to do. DOCKER_UNAVAILABLE: let the normal connection
        # attempt surface its own error rather than guessing why.
        return

    if result.outcome == ContainerRecoveryOutcome.START_FAILED:
        console.print(f"[error]Failed to start container '{name}'.[/error]")
        console.print(f"  [error]{result.detail}[/error]")
        raise typer.Exit(1)

    console.print(f"[error]PostgreSQL container '{name}' not found.[/error]")
    if result.outcome == ContainerRecoveryOutcome.MISSING_VOLUME_PRESENT:
        console.print("  Its data volume is still present, though.")
        console.print(
            "  Run [bold]civex db setup-docker[/bold] to recreate the container "
            "— your data will be reattached."
        )
    else:
        console.print(
            "  [bold]Its data volume is gone too — any data in this project's "
            "database is likely unrecoverable.[/bold]"
        )
        console.print(
            "  If you have a separate backup/dump, restore from that instead."
        )
        console.print(
            "  Otherwise, [bold]civex db setup-docker[/bold] will create a "
            "brand-new, EMPTY database at the same settings."
        )
    raise typer.Exit(1)


def cli_load_config() -> Config:
    try:
        config = load_config()
    except ConfigError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    if config.db.docker_managed:
        _ensure_container_ready(config.project_root.name)

    return config


def get_ctx() -> AppContext:
    from civex.context import build_local_context

    return build_local_context(cli_load_config())


def run_job(job: WorkflowJobDTO, ctx: AppContext) -> tuple[list[dict], str, list[dict]]:
    """Execute one workflow job. Returns (per-step execution records,
    captured log output, affected records). Raises on failure -- the
    exception carries whatever per-step records did complete as
    `.step_executions` (CIVEX-117)."""
    import contextlib
    import io
    import logging as _logging

    from civex.plugins import registry as plugin_registry
    from civex.plugins.base import WorkflowContext
    from civex.workflows import executor

    config = cli_load_config()

    wf_def = ctx.job_svc.find_workflow(job.workflow_name)
    if wf_def is None:
        raise ValueError(
            f"Workflow '{job.workflow_name}' not found in _civex/workflows/"
        )

    record = ctx.record_svc.get(str(job.record_id))
    dataset = ctx.dataset_svc._datasets.get_by_id(record.dataset_id)
    if dataset is None:
        raise ValueError(f"Dataset for record '{job.record_id}' not found")

    _NOISY = (
        "sqlalchemy",
        "uvicorn",
        "fastapi",
        "httpx",
        "asyncio",
        "urllib3",
        "watchfiles",
        "h11",
    )

    buf = io.StringIO()
    handler = _logging.StreamHandler(buf)
    handler.setLevel(_logging.DEBUG)
    handler.setFormatter(_logging.Formatter("%(levelname)-8s %(name)s: %(message)s"))
    handler.addFilter(
        type(
            "F",
            (_logging.Filter,),
            {
                "filter": staticmethod(
                    lambda r: not any(r.name.startswith(p) for p in _NOISY)
                )
            },
        )()
    )
    root = _logging.getLogger()
    prev_level = root.level
    root.addHandler(handler)
    root.setLevel(min(prev_level, _logging.DEBUG))
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            # Discovery runs inside the log-capture block (rather than once
            # up front) so a broken plugin file's log.warning() -- and thus
            # which file failed and why -- lands in this job's log instead of
            # vanishing into the process's own stderr (CIVEX-112).
            plugin_registry.discover_user_plugins(config.civex_dir / "plugins")
            plugins = plugin_registry.all_plugins()
            # job_depth is what ends a chain of workflows that keep triggering
            # each other; without it every hop here would start again at 0.
            wf_ctx = WorkflowContext(
                record=record,
                dataset=dataset,
                _app_ctx=ctx,
                job_depth=job.depth,
                job_id=str(job.id),
                workflow_name=job.workflow_name,
            )
            try:
                step_executions = executor.run(
                    wf_def,
                    wf_ctx,
                    plugins,
                    initial_outputs=job.input_data or None,
                    default_timeout_seconds=config.plugins.default_timeout_seconds,
                    should_stop=lambda: ctx.job_svc.should_stop(job.id),
                )
            except Exception as e:
                # Mirrors executor.run()'s own .step_executions attachment --
                # whatever records the run touched before the failing step
                # are still real writes the caller's mark_failed() should see.
                e.affected_records = wf_ctx.affected_records  # type: ignore[attr-defined]
                raise
    finally:
        root.removeHandler(handler)
        root.setLevel(prev_level)

    return step_executions, buf.getvalue(), wf_ctx.affected_records


def drain_jobs(ctx: AppContext) -> None:
    """Run all pending jobs inline. Prints a line per job."""
    while True:
        job = ctx.job_svc.claim_pending()
        if job is None:
            break
        console.print(
            f"  [dim]→ workflow '{job.workflow_name}' (trigger: {job.trigger})[/dim]"
        )
        failure: Exception | None = None
        step_executions: list[dict] = []
        log = ""
        affected_records: list[dict] = []
        try:
            step_executions, log, affected_records = run_job(job, ctx)
        except Exception as e:
            failure = e

        if isinstance(failure, JobCancelled):
            # Stopped on purpose: keep what it got done, and carry on with
            # whatever is still queued (which is nothing after a Stop).
            try:
                ctx.job_svc.mark_cancelled(
                    job.id,
                    step_executions=getattr(failure, "step_executions", None),
                    affected_records=getattr(failure, "affected_records", None),
                )
                ctx.commit()
                console.print(f"    [warning]■ stopped: {failure}[/warning]")
            except Exception as e:
                console.print(f"    [error]✗ failed to record the stop: {e}[/error]")
                break
            continue

        # Persisting the outcome is deliberately outside the try/except
        # above: a DB error here must not be mistaken for this job's own
        # failure, and must not crash the whole drain with a raw traceback
        # -- leaving every other still-pending job unprocessed until the
        # user re-runs the command (CIVEX-296 stability review).
        try:
            if failure is None:
                ctx.job_svc.mark_completed(
                    job.id,
                    log=log or None,
                    step_executions=step_executions,
                    affected_records=affected_records,
                )
                ctx.commit()
                console.print("    [success]✓ done[/success]")
            else:
                envelope = getattr(
                    failure, "envelope", None
                ) or ErrorEnvelope.from_exception(failure)
                ctx.job_svc.mark_failed(
                    job.id,
                    envelope,
                    step_executions=getattr(failure, "step_executions", None),
                    affected_records=getattr(failure, "affected_records", None),
                )
                ctx.commit()
                where = f" [{envelope.step}]" if envelope.step else ""
                console.print(f"    [error]✗{where} {envelope.kind}: {failure}[/error]")
        except Exception as e:
            console.print(
                f"    [error]✗ failed to record this job's outcome: {e}[/error]"
            )
            console.print(
                "[dim]Stopping -- remaining jobs will be picked up on the next run.[/dim]"
            )
            break


def format_bytes(b: float | None) -> str:
    if b is None:
        return "—"
    if b >= 1_073_741_824:
        return f"{b / 1_073_741_824:.1f} GB"
    if b >= 1_048_576:
        return f"{b / 1_048_576:.0f} MB"
    return f"{b / 1024:.0f} KB"
