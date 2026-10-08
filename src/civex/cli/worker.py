from __future__ import annotations

import time
from typing import Optional

import typer
from rich.markup import escape
from rich.table import Table

from civex.cli.utils import drain_jobs, get_ctx, run_job
from civex.console import console
from civex.domain.dtos import ErrorEnvelope
from civex.domain.exceptions import JobCancelled, NotFoundError, ValidationError

app = typer.Typer(help="Manage automated workflow processing")


def _what_changed(job) -> list[str]:
    """One line per field that changed to start this run, saying which ones
    the workflow was watching."""
    lines = []
    for c in (job.trigger_detail or {}).get("changes", []):
        mark = "" if c.get("watched", True) else " (not watched)"
        lines.append(f"{c['field']}: {c.get('before')!s} → {c.get('after')!s}{mark}")
    return lines


def _caused_by(job) -> str | None:
    cause = (job.trigger_detail or {}).get("caused_by")
    if not cause:
        return None
    return f"run {str(cause['job_id'])[:8]}… of '{cause.get('workflow')}'"


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
            if isinstance(failure, JobCancelled):
                ctx.job_svc.mark_cancelled(
                    job.id,
                    step_executions=getattr(failure, "step_executions", None),
                    affected_records=getattr(failure, "affected_records", None),
                )
                ctx.commit()
                console.print(f"    [warning]■ stopped: {failure}[/warning]")
            elif failure is None:
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
        None,
        "--status",
        "-s",
        help="Filter: pending, running, completed, failed, cancelled",
    ),
) -> None:
    """List workflow jobs, with the fields that started each one."""
    ctx = get_ctx()
    jobs = ctx.job_svc.list_jobs(status=status)

    if not jobs:
        msg = f"No {status} jobs." if status else "No jobs."
        console.print(f"[info]{msg}[/info]")
        return

    named = {
        str(r.id): r
        for r in ctx.record_svc.labels(list({str(j.record_id) for j in jobs}))
    }

    def record_cell(record_id) -> str:
        """The record's name and short id, or that it is deleted or gone."""
        short = str(record_id)[:8] + "…"
        record = named.get(str(record_id))
        if record is None:
            return f"{short} [warning](no longer exists)[/warning]"
        label = f"{escape(record.natural_name)} " if record.natural_name else ""
        note = " [warning](deleted)[/warning]" if record.deleted_at else ""
        return f"{label}{short}{note}"

    table = Table(
        "ID", "Workflow", "Schema", "Record", "Trigger", "Changed", "Status", "Created"
    )
    for j in jobs:
        changed = ", ".join(
            c["field"] for c in (j.trigger_detail or {}).get("changes", [])
        )
        table.add_row(
            str(j.id)[:8] + "…",
            j.workflow_name,
            j.schema_name,
            record_cell(j.record_id),
            j.trigger,
            changed or "—",
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
    for line in _what_changed(job):
        console.print(f"  Changed  {line}")
    caused = _caused_by(job)
    if caused:
        console.print(f"  Caused by  {caused}  (chain depth {job.depth})")
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


@app.command("stop")
def worker_stop(
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask first."),
) -> None:
    """Stop all automation, for example a workflow that keeps triggering itself.

    Pauses automation (nothing new is triggered or started, and manual runs are
    refused), cancels every waiting run, and stops every running one before its
    next step. A step already in progress finishes or times out first. Start
    again with `civex automation resume`.
    """
    if not yes and not typer.confirm(
        "Pause automation and cancel every waiting and running workflow?"
    ):
        raise typer.Exit(1)
    ctx = get_ctx()
    try:
        cancelled = ctx.job_svc.stop_all()
        ctx.commit()
    finally:
        ctx.close()
    console.print(
        f"[warning]Automation is paused.[/warning] Cancelled {cancelled} run"
        f"{'' if cancelled == 1 else 's'}. `civex automation resume` starts it again."
    )


@app.command("resume")
def worker_resume() -> None:
    """Lift a pause: triggers fire and waiting runs are picked up again."""
    ctx = get_ctx()
    try:
        ctx.job_svc.resume()
    finally:
        ctx.close()
    console.print("[success]Automation is running.[/success]")


@app.command("status")
def worker_status() -> None:
    """Say whether automation is paused, and how many runs are waiting or running."""
    ctx = get_ctx()
    try:
        state = ctx.job_svc.automation_state()
    finally:
        ctx.close()
    if state["paused"]:
        console.print("[warning]Automation is paused.[/warning]")
    else:
        console.print("Automation is running.")
    console.print(f"  {state['pending']} waiting, {state['running']} running")


@app.command("cancel")
def worker_cancel(
    job_id: str = typer.Argument(..., help="Job ID or short prefix"),
) -> None:
    """Cancel one run.

    A waiting run never starts; a running one stops before its next step.
    """
    ctx = get_ctx()
    try:
        job = next(
            (j for j in ctx.job_svc.list_jobs() if str(j.id).startswith(job_id)),
            None,
        )
        if job is None:
            console.print(f"[error]Job '{job_id}' not found.[/error]")
            raise typer.Exit(1)
        if job.status not in ("pending", "running"):
            console.print(f"Job {str(job.id)[:8]}… is already {job.status}.")
            return
        ctx.job_svc.cancel_job(job.id)
        ctx.commit()
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()
    console.print(
        f"[warning]Cancelled {job.workflow_name} ({str(job.id)[:8]}…).[/warning]"
    )


@app.command("delete")
def worker_delete(
    job_ids: list[str] = typer.Argument(None, help="Run IDs or short prefixes"),
    pending: bool = typer.Option(
        False, "--pending", help="Every run still waiting to start."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask first."),
) -> None:
    """Delete runs, so a waiting one never starts.

    A running run stops before its next step; a finished one is removed with its
    log. What a run already changed in records stays, in their history.
    """
    if not job_ids and not pending:
        console.print("[error]Name runs to delete, or use --pending.[/error]")
        raise typer.Exit(1)
    ctx = get_ctx()
    try:
        jobs = ctx.job_svc.list_jobs(status="pending") if pending else []
        if job_ids:
            every = ctx.job_svc.list_jobs()
            for prefix in job_ids:
                found = [j for j in every if str(j.id).startswith(prefix)]
                if len(found) != 1:
                    console.print(
                        f"[error]'{prefix}' matches {len(found)} runs: give more of "
                        "its id.[/error]"
                    )
                    raise typer.Exit(1)
                jobs.append(found[0])
        jobs = list({j.id: j for j in jobs}.values())
        if not jobs:
            console.print("Nothing to delete.")
            return
        for j in jobs:
            console.print(
                f"  {str(j.id)[:8]}…  {j.workflow_name}  [dim]{j.status}[/dim]"
            )
        noun = "run" if len(jobs) == 1 else "runs"
        if not yes and not typer.confirm(f"Delete {len(jobs)} {noun}?"):
            raise typer.Exit(1)
        deleted = ctx.job_svc.delete_runs([j.id for j in jobs])
        ctx.commit()
    finally:
        ctx.close()
    console.print(f"Deleted {deleted} {'run' if deleted == 1 else 'runs'}.")
