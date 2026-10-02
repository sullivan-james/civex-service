from __future__ import annotations

from typing import Optional

import typer

from civex.cli.utils import get_ctx
from civex.console import console
from civex.domain.exceptions import (
    AlreadyExistsError,
    CivexError,
    NotFoundError,
    ValidationError,
    VolumeUnavailableError,
)

app = typer.Typer(help="Manage file storage volumes", no_args_is_help=True)


def _fmt_bytes(b: int | None) -> str:
    if b is None:
        return "—"
    if b >= 1_073_741_824:
        return f"{b / 1_073_741_824:.1f} GB"
    if b >= 1_048_576:
        return f"{b / 1_048_576:.0f} MB"
    return f"{b / 1024:.0f} KB"


@app.command("list")
def store_list() -> None:
    """List configured volumes and their current usage."""
    ctx = get_ctx()
    try:
        stats = ctx.store_svc.volume_stats()
    finally:
        ctx.close()

    if not stats:
        console.print("[dim]No volumes configured.[/dim]")
        return

    from rich.table import Table

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Name", style="bold")
    table.add_column("Path")
    table.add_column("Queue", justify="center")
    table.add_column("Civex used")
    table.add_column("Allocated")
    table.add_column("Disk free")
    table.add_column("Status")

    for v in stats:
        in_queue = "✓" if v["in_queue"] else ""
        used = _fmt_bytes(v["civex_used_bytes"])
        alloc = (
            _fmt_bytes(int(v["allocated_gb"] * 1_073_741_824))
            if v["allocated_gb"]
            else "unlimited"
        )
        free = _fmt_bytes(v["disk_free_bytes"])
        if v["state"] == "offline":
            status = "[dim]offline[/dim]"
        elif v["state"] == "wrong_drive":
            status = "[red]wrong drive[/red]"
        elif v["state"] in ("readonly", "retired"):
            status = f"[dim]{v['state'].replace('readonly', 'read-only')}[/dim]"
        elif v["warning"]:
            status = "[yellow]⚠ low space[/yellow]"
        else:
            status = "[green]ok[/green]"
        table.add_row(v["name"], v["path"], in_queue, used, alloc, free, status)

    console.print(table)

    from rich.markup import escape

    for v in stats:
        if v["state"] in ("offline", "wrong_drive"):
            console.print(f"\n[bold]{escape(v['name'])}[/bold]: {escape(v['reason'])}")
            if v["fix"]:
                console.print(f"  {escape(v['fix'])}")
            if v["state"] == "offline":
                console.print(
                    f"  Change the path: [bold]civex store update {escape(v['name'])}"
                    " --path <new path>[/bold]"
                )
            else:
                console.print(
                    f"  Adopt the drive: [bold]civex store adopt {escape(v['name'])}"
                    "[/bold]"
                )


@app.command("add")
def store_add(
    name: str = typer.Argument(..., help="Volume name"),
    path: str = typer.Option(
        ..., "--path", "-p", help="Directory path for this volume"
    ),
    allocated_gb: Optional[float] = typer.Option(
        None, "--allocated-gb", help="Max GB civex may use (omit for unlimited)"
    ),
) -> None:
    """Add a new storage volume."""
    ctx = get_ctx()
    try:
        ctx.store_svc.add_volume(name, path, allocated_gb)
        console.print(f"[green]Added volume '{name}' at {path}.[/green]")
        if allocated_gb:
            console.print(f"  Allocation: {allocated_gb:.1f} GB")
        console.print(
            "  Add it to the write queue with: [bold]civex store queue set[/bold]"
        )
    except (AlreadyExistsError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()


@app.command("adopt")
def store_adopt(
    name: str = typer.Argument(..., help="Volume name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation"),
) -> None:
    """Declare that the drive at a volume's path is that volume.

    A volume is recognised by an identity marker in its root, so civex can tell
    an unplugged drive from a different drive mounted at the same path. If a
    volume is reported as the wrong drive but this is in fact the right one
    (the marker was deleted, or the drive was re-formatted), this rewrites the
    marker. Nothing else on the drive is changed.
    """
    ctx = get_ctx()
    try:
        if not yes:
            status = ctx.store_svc.volume_stats()
            current = next((v for v in status if v["name"] == name), None)
            if current is not None and current["reason"]:
                console.print(f"[warning]{current['reason']}[/warning]")
            if not typer.confirm(f"Treat the drive at this path as volume '{name}'?"):
                raise typer.Exit(1)
        result = ctx.store_svc.adopt_volume(name)
        console.print(f"[green]Volume '{name}' is now {result.state}.[/green]")
    except (NotFoundError, VolumeUnavailableError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()


@app.command("update")
def store_update(
    name: str = typer.Argument(..., help="Volume name"),
    path: Optional[str] = typer.Option(None, "--path", "-p", help="New directory path"),
    allocated_gb: Optional[float] = typer.Option(
        None, "--allocated-gb", help="New allocation limit in GB"
    ),
    clear_allocation: bool = typer.Option(
        False, "--clear-allocation", help="Remove allocation limit"
    ),
) -> None:
    """Update a volume's path or allocation."""
    ctx = get_ctx()
    from civex.services.store_service import _UNSET

    alloc = _UNSET
    if allocated_gb is not None:
        alloc = allocated_gb
    elif clear_allocation:
        alloc = None
    try:
        ctx.store_svc.update_volume(name, path=path, allocated_gb=alloc)
        console.print(f"[green]Updated volume '{name}'.[/green]")
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()


@app.command("remove")
def store_remove(
    name: str = typer.Argument(..., help="Volume name"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Remove even if the volume contains objects (existing file references will become unresolvable)",
    ),
) -> None:
    """Remove a volume from the configuration (does not delete files)."""
    ctx = get_ctx()
    try:
        ctx.store_svc.remove_volume(name, force=force)
        console.print(f"[green]Removed volume '{name}'.[/green]")
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()


@app.command("queue")
def store_queue(
    names: list[str] = typer.Argument(..., help="Volume names in write priority order"),
) -> None:
    """Set the write queue (ordered list of volumes for new file writes)."""
    ctx = get_ctx()
    try:
        ctx.store_svc.set_queue(names)
        console.print(f"[green]Write queue set to: {' → '.join(names)}[/green]")
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()


@app.command("gc")
def store_gc(
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Actually delete collectible objects. Without this flag, only reports what would be deleted.",
    ),
    grace_days: int = typer.Option(
        14,
        "--grace-days",
        help="Skip unreferenced objects written more recently than this "
        "many days, to avoid racing an in-flight upload whose record/job "
        "write hasn't committed yet.",
    ),
    show: int = typer.Option(
        20, "--show", help="Max collectible objects to list individually"
    ),
    rebuild_refs: bool = typer.Option(
        False,
        "--rebuild-refs",
        help="Recompute the file-reference table from every record and job "
        "before collecting. Normally unnecessary (it is kept current on every "
        "write); use it if the table may have drifted, e.g. after editing the "
        "database directly.",
    ),
) -> None:
    """Reclaim object-store blobs no longer referenced by any record or workflow job.

    Not a root: audit history and job step logs, which retain FileRef
    snapshots forever -- treating them as roots would leave almost nothing
    collectible. Old audit diffs may reference a sha256 that GC has since
    removed; that's the accepted tradeoff of running this at all.

    Defaults to a dry run. Pass --apply to actually delete.
    """
    ctx = get_ctx()
    try:
        if rebuild_refs:
            count = ctx.gc_svc.rebuild_references()
            ctx.commit()
            console.print(f"Rebuilt file-reference table ({count} references).")
        report = ctx.gc_svc.run(dry_run=not apply, grace_days=grace_days)
    except CivexError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    except OSError as e:
        console.print(f"[error]Storage error while running GC: {e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()

    def _fmt(b: int) -> str:
        if b >= 1_073_741_824:
            return f"{b / 1_073_741_824:.1f} GB"
        if b >= 1_048_576:
            return f"{b / 1_048_576:.1f} MB"
        return f"{b} B"

    if report.errors:
        console.print(
            "[warning]Some reference sources could not be read -- "
            "nothing was deleted this run:[/warning]"
        )
        for err in report.errors:
            console.print(f"  [warning]{err}[/warning]")

    console.print(f"Scanned {report.scanned} object(s) in the store.")
    console.print(f"  {report.referenced} referenced by a live record or job")
    console.print(
        f"  {report.protected_by_grace} unreferenced but within the "
        f"{report.grace_days}-day grace period"
    )
    applied = apply and not report.errors
    verb = "Deleted" if applied else "Collectible"
    console.print(
        f"  [bold]{verb} {report.deleted_count} object(s), {_fmt(report.deleted_bytes)}[/bold]"
    )

    for obj in report.deleted[:show]:
        console.print(f"    {obj.sha256[:12]}…  {_fmt(obj.size):>10}  ({obj.volume})")
    if report.deleted_count > show:
        console.print(f"    … and {report.deleted_count - show} more")

    if report.stale_scratch_removed:
        console.print(
            f"  {verb} {report.stale_scratch_removed} abandoned upload scratch file(s)"
        )

    if not applied and (report.deleted_count or report.stale_scratch_removed):
        console.print(
            "\n[dim]Dry run -- re-run with --apply to actually delete these.[/dim]"
        )
