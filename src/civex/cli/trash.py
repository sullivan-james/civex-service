from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import typer
from rich.markup import escape
from rich.table import Table

from civex.cli.utils import cli_load_config, get_ctx as _ctx
from civex.console import console
from civex.domain.dtos import DatasetDTO, RecordDTO, SchemaDTO
from civex.domain.exceptions import NotFoundError

app = typer.Typer(
    help="Browse and manage soft-deleted schemas, collections and records "
    "(Recently Deleted)"
)


def _age(deleted_at: datetime) -> str:
    days = (datetime.now(timezone.utc) - deleted_at).days
    return "today" if days <= 0 else f"{days}d ago"


def _deleted_at(dto: SchemaDTO | DatasetDTO | RecordDTO) -> datetime:
    """dto.deleted_at, narrowed: everything list_deleted() returns is deleted."""
    assert dto.deleted_at is not None
    return dto.deleted_at


# `--kind` as the history filter's kind of thing.
_KIND_FILTER = {
    "schema": "schema",
    "field": "field",
    "collection": "dataset",
    "record": "record",
}
KINDS = tuple(_KIND_FILTER)


@app.command("list")
def trash_list(
    kind: Optional[str] = typer.Option(
        None, "--kind", "-k", help="Only schemas, fields, collections or records"
    ),
    search: Optional[str] = typer.Option(
        None, "--search", "-s", help="Text to find in a name or a record's values"
    ),
    limit: int = typer.Option(25, "--limit", "-n", min=1, help="How many to show"),
    offset: int = typer.Option(0, "--offset", min=0, help="Skip this many"),
) -> None:
    """List what is in Recently Deleted, newest first.

    This is history filtered to what is deleted now (`civex history` shows the
    rest). A delete that took many records with it, such as a bulk delete or a
    tree, is one line.
    """
    if kind is not None and kind not in KINDS:
        console.print(f"[error]--kind must be one of: {', '.join(KINDS)}[/error]")
        raise typer.Exit(1)
    conditions = [
        {"field": "now", "op": "eq", "value": "deleted"},
        {"field": "change", "op": "eq", "value": "delete"},
    ]
    if kind:
        conditions.append({"field": "kind", "op": "eq", "value": _KIND_FILTER[kind]})
    ctx = _ctx()
    try:
        events, total = ctx.history_svc.events(
            where={"and": conditions}, search=search, offset=offset, limit=limit
        )
        retention = cli_load_config().retention.purge_after_days
    finally:
        ctx.close()

    if not events:
        console.print(
            "[info]No matches.[/info]"
            if (kind or search)
            else "[info]Recently Deleted is empty.[/info]"
        )
        return

    table = Table("Type", "Name", "ID", "Deleted")
    for event in events:
        if event.entry is not None:
            entry = event.entry
            now = entry.now or {}
            name = now.get("name") or (entry.old_data or {}).get("name") or "-"
            place = now.get("collection") or (
                f"schema {now['schema_name']}"
                if now.get("kind") == "field" and now.get("schema_name")
                else None
            )
            where = f" [dim]in {escape(str(place))}[/dim]" if place else ""
            table.add_row(
                now.get("kind", entry.entity_type),
                f"{escape(str(name))}{where}",
                # A field is restored by its full ID; the rest by name.
                str(entry.entity_id)
                if now.get("kind") == "field"
                else str(entry.entity_id)[:8],
                _age(entry.timestamp),
            )
        else:
            held = ", ".join(f"{p['count']} {p['entity_type']}(s)" for p in event.parts)
            table.add_row(
                "batch", f"Deleted together: {held}", "", _age(event.timestamp)
            )
    console.print(table)
    if total > len(events):
        console.print(f"[dim]Showing {len(events)} of {total}. Use --offset.[/dim]")
    console.print(
        f"[dim]Retention: {retention} day(s). Restore with `civex schema|collection|record "
        "restore <name/id>` (a field: `civex schema restore-field <schema> <id>`), "
        "or delete permanently with `... purge`.[/dim]"
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

    expired_schemas = [
        s for s in ctx.schema_svc.list_deleted() if _deleted_at(s) <= cutoff
    ]
    expired_collections = [
        d for d in ctx.dataset_svc.list_deleted() if _deleted_at(d) <= cutoff
    ]
    expired_records = [
        r for r in ctx.record_svc.list_deleted() if _deleted_at(r) <= cutoff
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
