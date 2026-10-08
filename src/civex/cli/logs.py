"""`civex logs`: every log civex keeps on this computer, and their latest
lines. The rules are in civex.logs; these commands only show them."""

from __future__ import annotations

import time
from pathlib import Path

import typer
from rich.markup import escape
from rich.table import Table

from civex import fs_open, logs
from civex.config import find_project_root
from civex.console import console
from civex.domain.exceptions import NotFoundError

app = typer.Typer(
    help="See civex's logs: this project's server, the desktop app, its "
    "launcher and updates."
)

_COLOURS = {"warning": "yellow", "error": "red", "critical": "red bold", "debug": "dim"}


def _civex_dir() -> Path | None:
    root = find_project_root()
    return root / "_civex" if root else None


def _find(log_id: str) -> logs.LogSource:
    try:
        return logs.find(_civex_dir(), log_id)
    except NotFoundError as e:
        console.print(f"[error]{escape(str(e))}[/error] (`civex logs list` shows them)")
        raise typer.Exit(1)


@app.command("list")
def logs_list() -> None:
    """The logs civex keeps on this computer, and where they are."""
    table = Table()
    for col in ("Log", "What", "Last written", "Where"):
        table.add_column(col)
    for source in logs.sources(_civex_dir()):
        info = source.describe()
        table.add_row(
            source.id,
            source.name,
            info["modified"] or "nothing yet",
            escape(info["path"]),
        )
    console.print(table)


def _show(line: logs.LogLine) -> None:
    colour = _COLOURS.get(line.level or "", "")
    head = f"[dim]{line.time}[/dim] " if line.time else ""
    level = (
        f"[{colour}]{line.level.upper():<8}[/] "
        if line.level and colour
        else (f"{line.level.upper():<8} " if line.level else "")
    )
    extra = " ".join(f"{k}={v}" for k, v in line.fields.items() if k != "logger")
    console.print(
        f"{head}{level}{escape(line.message)}"
        + (f" [dim]{escape(extra)}[/dim]" if extra else ""),
        highlight=False,
    )


@app.command("show")
def logs_show(
    log_id: str = typer.Argument("project", help="Which log (`civex logs list`)."),
    lines: int = typer.Option(50, "--lines", "-n", help="How many of the latest."),
    level: str = typer.Option(
        None, "--level", "-l", help="Only this level and above: warning, error, ..."
    ),
    search: str = typer.Option(None, "--search", "-s", help="Only lines with this."),
    follow: bool = typer.Option(
        False, "--follow", "-f", help="Keep showing new lines."
    ),
) -> None:
    """Print a log's latest lines (and, with --follow, the new ones)."""
    source = _find(log_id)
    seen = logs.read(source, lines, level, search)
    for line in seen:
        _show(line)
    if not follow:
        return
    last = seen[-1] if seen else None
    try:
        while True:
            time.sleep(1)
            fresh = logs.read(source, 200, level, search)
            if last is not None and last in fresh:
                fresh = fresh[len(fresh) - fresh[::-1].index(last) :]
            for line in fresh:
                _show(line)
            if fresh:
                last = fresh[-1]
    except KeyboardInterrupt:
        return


@app.command("path")
def logs_path(log_id: str = typer.Argument("project", help="Which log.")) -> None:
    """Print where a log is."""
    console.print(str(_find(log_id).path), highlight=False)


@app.command("open")
def logs_open(log_id: str = typer.Argument("project", help="Which log.")) -> None:
    """Show a log's folder in the file manager."""
    folder = _find(log_id).path.parent
    if not folder.is_dir() or not fs_open.open_folder(folder):
        console.print(f"Couldn't open it: {escape(str(folder))}")
        raise typer.Exit(1)
