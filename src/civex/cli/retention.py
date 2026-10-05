from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import typer
from rich.table import Table

from civex.cli.utils import cli_load_config, get_ctx as _ctx
from civex.console import console
from civex.domain.dtos import RetentionReportDTO
from civex.domain.exceptions import CivexError

app = typer.Typer(
    help="Clean up by age: deleted items, change history and workflow runs. "
    "Nothing is removed unless you run it."
)


def _date(value: Optional[str], option: str) -> Optional[datetime]:
    """A date or time from the command line, as an instant (UTC if no zone)."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        console.print(
            f"[error]{option} must be a date like 2026-01-31 or "
            f"2026-01-31T12:00, not '{value}'.[/error]"
        )
        raise typer.Exit(1)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@app.command("show")
def retention_show() -> None:
    """Show how long each kind is kept, and what a clean-up would remove now."""
    config = cli_load_config()
    r = config.retention
    forever = "forever"
    table = Table("Kind", "Kept", "Cleaned up by a clean-up")
    table.add_row(
        "Deleted items",
        f"restorable for {r.purge_after_days} day(s)",
        "permanently deleted after that"
        if r.auto_purge_deleted
        else "no (only by hand)",
    )
    table.add_row(
        "Change history",
        f"{r.audit_days} day(s)" if r.audit_days else forever,
        "removed after that" if r.audit_days else "never",
    )
    table.add_row(
        "Workflow runs and logs",
        f"{r.run_days} day(s)" if r.run_days else forever,
        "removed after that" if r.run_days else "never",
    )
    console.print(table)
    ctx = _ctx()
    try:
        report = ctx.retention_svc.run(ctx.retention_svc.settings_cutoffs())
    finally:
        ctx.close()
    _print_report(report)
    console.print(
        "[dim]Change it in Settings → Retention, or `[retention]` in "
        "_civex/config.toml. Run it with `civex retention run`.[/dim]"
    )


def _print_report(report: RetentionReportDTO) -> None:
    if not report.anything:
        console.print("[info]Nothing is old enough to remove.[/info]")
    else:
        verb = "Would remove" if report.dry_run else "Removed"
        parts = []
        if (
            report.deleted_records
            or report.deleted_collections
            or report.deleted_schemas
        ):
            parts.append(
                f"{report.deleted_records} deleted record(s), "
                f"{report.deleted_collections} collection(s), "
                f"{report.deleted_schemas} schema(s) for good"
            )
        if report.audit_entries:
            parts.append(f"{report.audit_entries} change-history entr(ies)")
        if report.runs:
            parts.append(
                f"{report.runs} workflow run(s) with {report.run_steps} step log(s)"
            )
        console.print(f"[success]{verb}:[/success] " + "; ".join(parts) + ".")
    if report.audit_kept_restorable:
        console.print(
            f"[dim]Kept {report.audit_kept_restorable} older history entr(ies): "
            "about things that can still be restored.[/dim]"
        )
    if report.audit_kept_unsynced:
        console.print(
            f"[dim]Kept {report.audit_kept_unsynced} older history entr(ies): "
            "not yet synced.[/dim]"
        )
    for skipped in report.skipped:
        console.print(f"[warning]Could not delete {skipped}[/warning]")


@app.command("run")
def retention_run(
    from_settings: bool = typer.Option(
        False,
        "--settings",
        help="Apply the retention settings (each kind left at keep-forever is left alone)",
    ),
    deleted_before: Optional[str] = typer.Option(
        None,
        "--deleted-before",
        help="Permanently delete everything deleted before this date",
    ),
    audit_before: Optional[str] = typer.Option(
        None, "--history-before", help="Remove change history before this date"
    ),
    runs_before: Optional[str] = typer.Option(
        None,
        "--runs-before",
        help="Remove finished workflow runs and their logs before this date",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Only say what would be removed"
    ),
) -> None:
    """Remove what is older than the retention settings or than dates you give.

    Give --settings to apply the settings, and/or a date per kind (a date wins
    over the setting for its kind). It always counts first and asks before
    removing anything. History about something that can still be restored is
    never removed. Run
    `civex store gc` afterwards to reclaim files nothing refers to any more.
    """
    dates = (
        _date(deleted_before, "--deleted-before"),
        _date(audit_before, "--history-before"),
        _date(runs_before, "--runs-before"),
    )
    if not from_settings and not any(dates):
        console.print(
            "[error]Say what to clean up: --settings, or --deleted-before, "
            "--history-before, --runs-before.[/error]"
        )
        raise typer.Exit(1)
    ctx = _ctx()
    try:
        cutoffs = ctx.retention_svc.cutoffs(from_settings, *dates)
        preview = ctx.retention_svc.run(cutoffs, dry_run=True)
        _print_report(preview)
        if dry_run or not preview.anything:
            return
        if not yes:
            typer.confirm("Remove these for good? This cannot be undone.", abort=True)
        report = ctx.retention_svc.run(cutoffs, dry_run=False)
        ctx.commit()
    except CivexError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()
    _print_report(report)


@app.command("forget-purged")
def retention_forget_purged(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Only count"),
) -> None:
    """Delete the history of records that were permanently deleted.

    Permanently deleting a record now deletes every history entry about it. This
    does the same for records that were permanently deleted before that was so.
    It cannot be undone.
    """
    ctx = _ctx()
    try:
        found = ctx.retention_svc.forget_purged(dry_run=True)
        if found == 0:
            console.print("[info]Nothing to delete.[/info]")
            return
        console.print(
            f"{found} history entr(ies) are about records that were permanently deleted."
        )
        if dry_run:
            return
        if not yes:
            typer.confirm("Delete them? This cannot be undone.", abort=True)
        removed = ctx.retention_svc.forget_purged(dry_run=False)
        ctx.commit()
    finally:
        ctx.close()
    console.print(f"[success]Deleted {removed} history entr(ies).[/success]")
