from __future__ import annotations

import json
from typing import Any, Optional

import typer
from rich.markup import escape
from rich.table import Table

from civex.cli.utils import get_ctx as _ctx
from civex.console import console
from civex.domain.dtos import (
    REVERT_APPLY,
    REVERT_CONFLICT,
    REVERT_SAME,
    AuditLogDTO,
    RevertPlanDTO,
)
from civex.domain.exceptions import CivexError

app = typer.Typer(
    help="See what changed, and when, and undo a change to a record. "
    "Entry ids are the short ones listed here."
)

_MAX_VALUE = 60
_MAX_CHANGES = 6

_STATUS_WORDS = {
    REVERT_APPLY: "[success]put back[/success]",
    REVERT_CONFLICT: "[warning]edited since[/warning]",
    REVERT_SAME: "[dim]already as it was[/dim]",
}


def _show(value: Any) -> str:
    """A value as one short line of text."""
    if value is None:
        return "(none)"
    if isinstance(value, dict) and "filename" in value:
        return str(value["filename"])
    if isinstance(value, list) and all(
        isinstance(v, dict) and "filename" in v for v in value
    ):
        return ", ".join(str(v["filename"]) for v in value) or "(none)"
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= _MAX_VALUE else text[: _MAX_VALUE - 1] + "…"


def _change_line(change: dict[str, Any]) -> str:
    name = change.get("label") or change["field"]
    return f"{escape(str(name))}: {escape(_show(change['before']))} → {escape(_show(change['after']))}"


def _changes_cell(entry: AuditLogDTO) -> str:
    lines = [_change_line(c) for c in entry.changes[:_MAX_CHANGES]]
    if len(entry.changes) > _MAX_CHANGES:
        lines.append(f"[dim]… and {len(entry.changes) - _MAX_CHANGES} more[/dim]")
    return "\n".join(lines) or "[dim]–[/dim]"


def _print_entries(entries: list[AuditLogDTO], total: int) -> None:
    if not entries:
        console.print("[info]No history yet.[/info]")
        return
    table = Table("Entry", "When", "Action", "Changes")
    for entry in entries:
        table.add_row(
            str(entry.id)[:8],
            entry.timestamp.astimezone().strftime("%Y-%m-%d %H:%M"),
            entry.action,
            _changes_cell(entry),
        )
    console.print(table)
    if total > len(entries):
        console.print(f"[dim]Showing {len(entries)} of {total}. Use --offset.[/dim]")
    console.print("[dim]See one in full with `civex history show <entry>`.[/dim]")


def _list(kind: str, ref: str, action: str | None, limit: int, offset: int) -> None:
    ctx = _ctx()
    try:
        scope = ctx.history_svc.scope_of(kind, ref)
        entries = ctx.history_svc.page(
            offset=offset, limit=limit, action=action, **scope
        )
        total = ctx.history_svc.count(action=action, **scope)
    except CivexError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()
    _print_entries(entries, total)


_ACTION = typer.Option(
    None, "--action", "-a", help="Only entries of this action (create, update, …)"
)
_LIMIT = typer.Option(20, "--limit", "-n", min=1, help="How many entries to show")
_OFFSET = typer.Option(0, "--offset", min=0, help="Skip this many entries")


@app.command("record")
def history_record(
    record_id: str = typer.Argument(..., help="Record ID or short prefix"),
    action: Optional[str] = _ACTION,
    limit: int = _LIMIT,
    offset: int = _OFFSET,
) -> None:
    """Show what changed on a record, newest first."""
    _list("record", record_id, action, limit, offset)


@app.command("schema")
def history_schema(
    name: str = typer.Argument(..., help="Schema name"),
    action: Optional[str] = _ACTION,
    limit: int = _LIMIT,
    offset: int = _OFFSET,
) -> None:
    """Show what changed on a schema and its own fields, newest first."""
    _list("schema", name, action, limit, offset)


@app.command("collection")
def history_collection(
    name: str = typer.Argument(..., help="Collection name or ID"),
    action: Optional[str] = _ACTION,
    limit: int = _LIMIT,
    offset: int = _OFFSET,
) -> None:
    """Show what changed on a collection, newest first."""
    _list("collection", name, action, limit, offset)


@app.command("show")
def history_show(
    entry_id: str = typer.Argument(..., help="History entry ID or short prefix"),
) -> None:
    """Show one history entry with every change in full."""
    ctx = _ctx()
    try:
        entry = ctx.history_svc.get(entry_id)
    except CivexError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()
    when = entry.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    console.print(f"[bold]{entry.action}[/bold] {entry.entity_type} {entry.entity_id}")
    console.print(f"[dim]{when}[/dim]")
    for change in entry.changes:
        console.print(f"  {_change_line(change)}")
    if not entry.changes:
        console.print("  [dim]No field changes.[/dim]")


def _print_plan(plan: RevertPlanDTO) -> None:
    if plan.kind == "restore":
        console.print("This will restore the deleted record.")
    elif plan.kind == "delete":
        console.print("This will delete the record (it can be restored afterwards).")
    if not plan.fields:
        return
    table = Table("Field", "Now", "Back to", "")
    for f in plan.fields:
        word = _STATUS_WORDS.get(f.status) or f"[error]{escape(f.reason or '')}[/error]"
        table.add_row(
            escape(f.label or f.field),
            escape(_show(f.current)),
            escape(_show(f.target)),
            word,
        )
    console.print(table)


@app.command("revert")
def history_revert(
    entry_id: str = typer.Argument(..., help="History entry ID or short prefix"),
    field: Optional[list[str]] = typer.Option(
        None,
        "--field",
        "-f",
        help="Only put this field back (repeat for several). Default: every "
        "field the entry changed",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Also overwrite fields that were edited since the entry",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Undo a change to a record.

    An update puts the fields it changed back to what they were, a delete
    restores the record, and a create deletes it. Fields edited since are
    left alone unless --force is given. The revert is recorded in the
    record's history like any other edit, so it can be undone too.
    """
    ctx = _ctx()
    try:
        plan = ctx.history_svc.plan_revert(entry_id, field or None)
        if plan.blocked:
            console.print(f"[error]{plan.blocked}[/error]")
            raise typer.Exit(1)
        _print_plan(plan)
        if plan.has_conflicts and not force:
            console.print(
                "[warning]Fields edited since are left alone. "
                "Use --force to overwrite them.[/warning]"
            )
        if not yes:
            typer.confirm("Revert this change?", abort=True)
        result = ctx.history_svc.revert(entry_id, field or None, force=force)
        ctx.commit()
    except CivexError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()
    if result.applied:
        console.print(f"[success]Put back: {', '.join(result.applied)}.[/success]")
    else:
        console.print("[success]Reverted.[/success]")
