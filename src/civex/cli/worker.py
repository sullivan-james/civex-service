from __future__ import annotations

import time
from typing import Optional

import typer
from rich.table import Table

from civex.cli.utils import drain_jobs, get_ctx, run_job
from civex.console import console
from civex.domain.dtos import ErrorEnvelope
from civex.domain.exceptions import NotFoundError

app = typer.Typer(help="Manage automated workflow processing")


@app.command("run")
def worker_run(
    watch: bool = typer.Option(
        False, "--watch", "-w", help="Keep polling for new jobs"
    ),
    interval: int = typer.Option(
        5, "--interval", help="Seconds between polls (--watch only)"
    ),
) -> None:
    """Process all pending workflow jobs. Use --watch to keep polling."""
    ctx = get_ctx()

    if not watch:
        drain_jobs(ctx)
        return

    console.print("[dim]Watching for jobs… (Ctrl-C to stop)[/dim]")
    while True:
        # This loop is meant to run unattended for a long time, so a single
        # transient failure anywhere in an iteration -- claiming a job,
        # running it, or persisting its outcome -- must be logged and
        # waited out rather than allowed to kill the whole daemon with a
        # raw traceback (CIVEX-296 stability review). Contrast with the
        # one-poll-per-call server equivalent, where a fresh call already
        # gets a clean retry; here the retry has to be built into the loop
        # itself.
        try:
            job = ctx.job_svc.claim_pending()
        except Exception as e:
            console.print(f"[error]✗ failed to claim the next job: {e}[/error]")
            time.sleep(interval)
            continue
        if job is None:
            time.sleep(interval)
            continue
        console.print(
            f"  [dim]→ workflow '{job.workflow_name}' (trigger: {job.trigger})[/dim]"
        )
        failure: Exception | None = None
        step_executions: list[dict] = []
        affected_records: list[dict] = []
        try:
            step_executions, _, affected_records = run_job(job, ctx)
        except Exception as e:
            failure = e

        # Persisting the outcome is deliberately outside the try/except
        # above: a DB error here must not be mistaken for this job's own
        # failure, and must not crash the daemon.
        try:
            if failure is None:
                ctx.job_svc.mark_completed(
                    job.id,
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
                retry_hint = " [dim](retryable)[/dim]" if envelope.retryable else ""
                console.print(
                    f"    [error]✗{where} {envelope.kind}: {failure}[/error]{retry_hint}"
                )
        except Exception as e:
            console.print(
                f"    [error]✗ failed to record this job's outcome: {e}[/error]"
            )
            time.sleep(interval)


@app.command("jobs")
def worker_jobs(
    status: Optional[str] = typer.Option(
        None, "--status", "-s", help="Filter: pending, running, completed, failed"
    ),
) -> None:
    """List workflow jobs."""
    ctx = get_ctx()
    jobs = ctx.job_svc.list_jobs(status=status)

    if not jobs:
        msg = f"No {status} jobs." if status else "No jobs."
        console.print(f"[info]{msg}[/info]")
        return

    table = Table("ID", "Workflow", "Schema", "Record", "Trigger", "Status", "Created")
    for j in jobs:
        table.add_row(
            str(j.id)[:8] + "…",
            j.workflow_name,
            j.schema_name,
            str(j.record_id)[:8] + "…",
            j.trigger,
            j.status,
            j.created_at.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)


@app.command("logs")
def worker_logs(
    job_id: str = typer.Argument(..., help="Job ID or short prefix"),
) -> None:
    """Show captured log output for a job."""
    ctx = get_ctx()
    jobs = ctx.job_svc.list_jobs()
    job = next(
        (j for j in jobs if str(j.id).startswith(job_id) or str(j.id) == job_id),
        None,
    )
    if job is None:
        console.print(f"[error]Job '{job_id}' not found.[/error]")
        raise typer.Exit(1)

    console.print(
        f"[bold]Job {str(job.id)[:8]}…[/bold]  {job.workflow_name}  [{job.status}]"
    )
    console.print(f"  Record   {str(job.record_id)[:8]}…  Schema: {job.schema_name}")
    console.print(f"  Trigger  {job.trigger}")
    if job.started_at:
        console.print(f"  Started  {job.started_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    if job.finished_at:
        console.print(f"  Finished {job.finished_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    if job.error:
        console.print(f"\n[error]Error: {job.error}[/error]")
    if job.log:
        console.print("\n[dim]─── captured output ─────────────────────────[/dim]")
        console.print(job.log.rstrip())
        console.print("[dim]──────────────────────────────────────────────[/dim]")
    elif job.status in ("completed", "failed"):
        console.print("\n[dim](no output captured)[/dim]")


@app.command("stats")
def worker_stats() -> None:
    """Show failed step-execution counts by plugin, across all jobs."""
    ctx = get_ctx()
    counts = ctx.job_svc.failure_counts_by_plugin()

    if not counts:
        console.print("[info]No failed steps recorded.[/info]")
        return

    table = Table("Plugin", "Failures")
    for plugin, count in counts.items():
        table.add_row(plugin, str(count))
    console.print(table)


@app.command("enqueue")
def worker_enqueue(
    workflow: str = typer.Option(..., "--workflow", "-w", help="Workflow name"),
    record_id: str = typer.Option(
        ..., "--record", "-r", help="Record ID or short prefix"
    ),
) -> None:
    """Manually enqueue a workflow job for a specific record."""
    ctx = get_ctx()
    try:
        record = ctx.record_svc.get(record_id)
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    job = ctx.job_svc.enqueue_manual(workflow, record)
    ctx.commit()
    console.print(
        f"[success]Enqueued '{workflow}' for record {str(record.id)[:8]}… (job {str(job.id)[:8]}…)[/success]"
    )
