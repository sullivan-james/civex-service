from __future__ import annotations

import json
from typing import Any, Optional

import typer
from rich.markup import escape
from rich.table import Table

from civex.cli.utils import get_ctx as _ctx
from civex.console import console
from civex.domain.dtos import (
    BatchRevertDTO,
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


@app.command("undo-edit")
def history_undo_edit(
    batch_id: Optional[str] = typer.Argument(
        None,
        help="The bulk edit to undo (its id in history). Omit with --last",
    ),
    last: bool = typer.Option(False, "--last", help="Undo the most recent bulk edit"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Also overwrite fields that were edited since the bulk edit",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Undo a whole bulk edit, such as one made with civex record set.

    Every change in it is undone as a single revert would undo it, and the
    undo is one new event in history, so it can be undone too. Fields
    edited since are left alone unless --force is given; a record deleted
    since, or one that no longer takes its old value, is left and listed.
    """
    if (batch_id is None) == (not last):
        console.print("[error]Give the bulk edit's id, or --last.[/error]")
        raise typer.Exit(1)
    ctx = _ctx()
    try:
        if last:
            found, _ = ctx.history_svc.events(
                where={"field": "how", "op": "eq", "value": "edit"}, limit=1
            )
            if not found or found[0].batch is None:
                console.print("[error]There is no bulk edit to undo.[/error]")
                raise typer.Exit(1)
            batch_id = str(found[0].batch.id)
            label = found[0].batch.label
            if label:
                console.print(f"Last bulk edit: {escape(label)}")
        assert batch_id is not None
        plan = ctx.history_svc.revert_batch(batch_id, force=force)
        _print_batch_revert(plan, "would be")
        if not plan.applied:
            console.print("[warning]Nothing to undo.[/warning]")
            raise typer.Exit(1)
        if not yes:
            typer.confirm(f"Undo {plan.applied} changes?", abort=True)
        result = ctx.history_svc.revert_batch(batch_id, force=force, dry_run=False)
        ctx.commit()
    except CivexError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()
    _print_batch_revert(result, "were")


def _print_batch_revert(plan: BatchRevertDTO, verb: str) -> None:
    console.print(f"{plan.applied} of {plan.entries} changes {verb} undone.")
    if plan.same:
        console.print(f"{plan.same} had nothing left to undo.")
    if plan.conflicts:
        console.print(
            f"[warning]{plan.conflicts} met a later edit; those fields are "
            "left as they are unless --force.[/warning]"
        )
    if plan.left:
        console.print(f"[warning]{plan.left} can't be undone:[/warning]")
        for r in plan.reasons[:20]:
            console.print(f"  {r['record_id'][:8]}  {escape(r['reason'])}")


@app.command("compact")
def compact(
    vacuum: bool = typer.Option(
        False,
        "--vacuum",
        help="Afterwards, give the room this frees back to the disk (SQLite). "
        "Needs about the database file's size in free disk while it runs.",
    ),
) -> None:
    """Store history written before this version as what changed rather than
    two whole copies of a thing per edit. The server does this by itself in the
    background; this does it now, with a progress bar. Each entry is checked to
    read the same before it is rewritten, and stopping (Ctrl+C) loses nothing:
    running it again carries on."""
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn

    from civex.cli.utils import format_bytes

    c = _ctx()
    try:
        total = c.compaction_svc.remaining()
        converted = kept = 0
        if total:
            with Progress(
                TextColumn("Converting history"),
                BarColumn(),
                MofNCompleteColumn(),
                console=console,
                transient=True,
            ) as bar:
                task = bar.add_task("history", total=total)
                while True:
                    step = c.compaction_svc.step()
                    c.commit()
                    converted += step.converted
                    kept += step.kept
                    bar.update(task, completed=total - step.remaining)
                    if step.remaining == 0 or step.converted + step.kept == 0:
                        break
        console.print(
            f"Converted {converted} entr{'y' if converted == 1 else 'ies'}"
            + (f"; {kept} kept whole (they would not read the same)" if kept else "")
            + "."
        )
        space = c.compaction_svc.space()
        if vacuum and space is not None:
            console.print("Giving the free room back to the disk…")
            c.commit()
            c.compaction_svc.reclaim()
            after = c.compaction_svc.space()
            if after is not None:
                console.print(
                    f"[success]The database is now {format_bytes(after.size_bytes)} "
                    f"(was {format_bytes(space.size_bytes)}).[/success]"
                )
        elif space is not None and space.free_bytes:
            console.print(
                f"{format_bytes(space.free_bytes)} of the database file is now unused; "
                "`civex history compact --vacuum` gives it back to the disk."
            )
    except CivexError as e:
        console.print(f"[error]{escape(str(e))}[/error]")
        raise typer.Exit(1)
    finally:
        c.close()
