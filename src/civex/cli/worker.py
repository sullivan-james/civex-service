from __future__ import annotations

import time
from typing import Optional

import typer
from rich.table import Table

from civex.cli.utils import drain_jobs, get_ctx, run_job
from civex.console import console
from civex.domain.exceptions import NotFoundError

app = typer.Typer(help="Process queued workflow jobs")


@app.command("run")
def worker_run(
    watch: bool = typer.Option(False, "--watch", "-w", help="Keep polling for new jobs"),
    interval: int = typer.Option(5, "--interval", help="Seconds between polls (--watch only)"),
) -> None:
    """Process all pending workflow jobs. Use --watch to keep polling."""
    ctx = get_ctx()

    if not watch:
        drain_jobs(ctx)
        return

    console.print("[dim]Watching for jobs… (Ctrl-C to stop)[/dim]")
    while True:
        job = ctx.job_svc.claim_pending()
        if job is None:
            time.sleep(interval)
            continue
        console.print(f"  [dim]→ workflow '{job.workflow_name}' (trigger: {job.trigger})[/dim]")
        try:
            run_job(job, ctx)
            ctx.job_svc.mark_completed(job.id)
            ctx.commit()
            console.print("    [success]✓ done[/success]")
        except Exception as e:
            ctx.job_svc.mark_failed(job.id, str(e))
            ctx.commit()
            console.print(f"    [error]✗ {e}[/error]")


@app.command("jobs")
def worker_jobs(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter: pending, running, completed, failed"),
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

    console.print(f"[bold]Job {str(job.id)[:8]}…[/bold]  {job.workflow_name}  [{job.status}]")
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


@app.command("enqueue")
def worker_enqueue(
    workflow: str = typer.Option(..., "--workflow", "-w", help="Workflow name"),
    record_id: str = typer.Option(..., "--record", "-r", help="Record ID or short prefix"),
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
    console.print(f"[success]Enqueued '{workflow}' for record {str(record.id)[:8]}… (job {str(job.id)[:8]}…)[/success]")
