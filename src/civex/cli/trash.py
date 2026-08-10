from __future__ import annotations

from datetime import datetime, timedelta, timezone

import typer
from rich.table import Table

from civex.cli.utils import cli_load_config, get_ctx as _ctx
from civex.console import console
from civex.domain.exceptions import NotFoundError

app = typer.Typer(
    help="Browse and manage soft-deleted schemas, collections and records "
    "(Recently Deleted)"
)


def _age(deleted_at: datetime) -> str:
    days = (datetime.now(timezone.utc) - deleted_at).days
    return "today" if days <= 0 else f"{days}d ago"


@app.command("list")
def trash_list() -> None:
    """List everything currently in Recently Deleted."""
    ctx = _ctx()
    config = cli_load_config()
    cutoff_days = config.retention.purge_after_days

    schemas = ctx.schema_svc.list_deleted()
    collections = ctx.dataset_svc.list_deleted()
    records = ctx.record_svc.list_deleted()

    if not (schemas or collections or records):
        console.print("[info]Recently Deleted is empty.[/info]")
        return

    table = Table("Type", "Name / ID", "Deleted", "Purge eligible")
    now = datetime.now(timezone.utc)
    rows = (
        [("schema", s.name, s.deleted_at) for s in schemas]
        + [("collection", d.name, d.deleted_at) for d in collections]
        + [("record", f"{r.schema_name} {str(r.id)[:8]}…", r.deleted_at) for r in records]
    )
    rows.sort(key=lambda r: r[2], reverse=True)
    for kind, label, deleted_at in rows:
        eligible = deleted_at <= now - timedelta(days=cutoff_days)
        table.add_row(
            kind,
            label,
            _age(deleted_at),
            "[warning]yes[/warning]" if eligible else "no",
        )
    console.print(table)
    console.print(
        f"[dim]Retention: {cutoff_days} day(s). Restore with `civex schema|collection|record "
        "restore <name/id>`, or delete permanently with `... purge`.[/dim]"
    )


@app.command("purge-expired")
def trash_purge_expired(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Permanently delete everything past the configured retention window."""
    ctx = _ctx()
    config = cli_load_config()
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=config.retention.purge_after_days
    )

    expired_schemas = [s for s in ctx.schema_svc.list_deleted() if s.deleted_at <= cutoff]
    expired_collections = [
        d for d in ctx.dataset_svc.list_deleted() if d.deleted_at <= cutoff
    ]
    expired_records = [
        r for r in ctx.record_svc.list_deleted() if r.deleted_at <= cutoff
    ]
    total = len(expired_schemas) + len(expired_collections) + len(expired_records)
    if total == 0:
        console.print("[info]Nothing is past the retention window.[/info]")
        return

    if not yes:
        typer.confirm(
            f"Permanently delete {total} item(s) past the "
            f"{config.retention.purge_after_days}-day retention window? This cannot be undone.",
            abort=True,
        )

    purged = 0
    for s in expired_schemas:
        try:
            ctx.schema_svc.purge(s.name)
            purged += 1
        except NotFoundError:
            pass
    for d in expired_collections:
        try:
            ctx.dataset_svc.purge(d.name)
            purged += 1
        except NotFoundError:
            pass
    for r in expired_records:
        try:
            ctx.record_svc.purge(str(r.id))
            purged += 1
        except NotFoundError:
            pass  # already gone via a schema/collection purge above
    ctx.commit()
    console.print(f"[success]Permanently deleted {purged} item(s).[/success]")
