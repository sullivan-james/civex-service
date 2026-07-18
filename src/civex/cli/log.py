"""
civex commit — group staged audit log entries into a named commit.
civex log    — list commits and optionally show audit history for an entity.
"""

from __future__ import annotations

import subprocess
import tempfile
from typing import Optional

import typer
from rich.table import Table

from civex.cli.utils import get_ctx
from civex.console import console


def commit(
    message: Optional[str] = typer.Option(
        None, "-m", "--message", help="Commit message"
    ),
) -> None:
    """Group staged changes into a named commit."""
    ctx = get_ctx()
    staged = ctx.audit_svc.count_staged()
    if staged["total"] == 0:
        console.print("[warning]Nothing to commit — no staged changes.[/warning]")
        ctx.close()
        raise typer.Exit(0)

    if message is None:
        editor = _get_editor()
        if editor is None:
            console.print("[error]No -m message given and $EDITOR is not set.[/error]")
            ctx.close()
            raise typer.Exit(1)
        message = _open_editor(editor)
        if not message:
            console.print("[warning]Aborting — empty commit message.[/warning]")
            ctx.close()
            raise typer.Exit(0)

    try:
        commit_dto = ctx.audit_svc.create_commit(message=message)
        ctx.commit()
    except ValueError as e:
        console.print(f"[error]{e}[/error]")
        ctx.close()
        raise typer.Exit(1)

    console.print(
        f"[success]Committed[/success] [dim]{str(commit_dto.id)[:8]}[/dim] {commit_dto.message or ''}"
    )
    console.print(f"  Records  {commit_dto.record_count}")
    console.print(f"  Schemas  {commit_dto.schema_count}")
    console.print(f"  Datasets {commit_dto.dataset_count}")
    ctx.close()


def log(
    record_id: Optional[str] = typer.Option(
        None, "--record", help="Show audit history for a specific record ID"
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum entries to show"),
) -> None:
    """Show commit history, or audit history for a specific entity."""
    ctx = get_ctx()

    if record_id:
        import uuid

        try:
            uid = uuid.UUID(record_id)
        except ValueError:
            record = ctx.record_svc.get(record_id)
            uid = record.id
        entries = ctx.audit_svc.list_audit(entity_id=uid, limit=limit)
        ctx.close()
        if not entries:
            console.print(f"[dim]No audit history for {record_id}.[/dim]")
            return
        table = Table(title=f"Audit history: {record_id[:8]}…", show_header=True)
        table.add_column("When", style="dim", width=24)
        table.add_column("Action", width=8)
        table.add_column("Commit", width=8)
        for e in entries:
            table.add_row(
                e.timestamp.strftime("%Y-%m-%d %H:%M:%S") if e.timestamp else "",
                e.action,
                str(e.commit_id)[:8] if e.commit_id else "[dim]staged[/dim]",
            )
        console.print(table)
        return

    commits = ctx.audit_svc.list_commits(limit=limit)
    staged = ctx.audit_svc.count_staged()
    ctx.close()

    if not commits and staged["total"] == 0:
        console.print(
            "[dim]No commits yet. Make some changes then run `civex commit -m 'message'`.[/dim]"
        )
        return

    if staged["total"] > 0:
        console.print(
            f"[yellow]Staged (uncommitted):[/yellow] "
            f"{staged['records']} record(s), "
            f"{staged['schemas']} schema/field(s), "
            f"{staged['datasets']} dataset(s)"
        )

    if not commits:
        return

    table = Table(show_header=True)
    table.add_column("ID", width=8)
    table.add_column("Date", width=12)
    table.add_column("Message")
    table.add_column("Records", justify="right", width=8)
    table.add_column("Schemas", justify="right", width=8)
    table.add_column("Datasets", justify="right", width=9)
    table.add_column("Pushed", width=6)

    for c in commits:
        table.add_row(
            str(c.id)[:8],
            c.created_at.strftime("%Y-%m-%d") if c.created_at else "",
            c.message or "[dim]—[/dim]",
            str(c.record_count),
            str(c.schema_count),
            str(c.dataset_count),
            "yes" if c.pushed_at else "[dim]no[/dim]",
        )

    console.print(table)


def _get_editor() -> str | None:
    import os

    return os.environ.get("EDITOR") or os.environ.get("VISUAL")


def _open_editor(editor: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
        f.write(
            "\n# Write your commit message above. Lines starting with # are ignored.\n"
        )
        tmpfile = f.name
    subprocess.run([editor, tmpfile], check=False)
    content = open(tmpfile).read()
    lines = [line for line in content.splitlines() if not line.startswith("#")]
    return "\n".join(lines).strip()
