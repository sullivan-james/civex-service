from __future__ import annotations

from typing import Optional

import typer

from civex.cli.utils import get_ctx
from civex.console import console
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError

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
    stats = ctx.store_svc.volume_stats()
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
        alloc = _fmt_bytes(int(v["allocated_gb"] * 1_073_741_824)) if v["allocated_gb"] else "unlimited"
        free = _fmt_bytes(v["disk_free_bytes"])
        if not v["available"]:
            status = "[dim]unavailable[/dim]"
        elif v["warning"]:
            status = "[yellow]⚠ low space[/yellow]"
        else:
            status = "[green]ok[/green]"
        table.add_row(v["name"], v["path"], in_queue, used, alloc, free, status)

    console.print(table)


@app.command("add")
def store_add(
    name: str = typer.Argument(..., help="Volume name"),
    path: str = typer.Option(..., "--path", "-p", help="Directory path for this volume"),
    allocated_gb: Optional[float] = typer.Option(None, "--allocated-gb", help="Max GB civex may use (omit for unlimited)"),
) -> None:
    """Add a new storage volume."""
    ctx = get_ctx()
    try:
        ctx.store_svc.add_volume(name, path, allocated_gb)
        console.print(f"[green]Added volume '{name}' at {path}.[/green]")
        if allocated_gb:
            console.print(f"  Allocation: {allocated_gb:.1f} GB")
        console.print("  Add it to the write queue with: [bold]civex store queue set[/bold]")
    except AlreadyExistsError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    finally:
        ctx.close()


@app.command("update")
def store_update(
    name: str = typer.Argument(..., help="Volume name"),
    path: Optional[str] = typer.Option(None, "--path", "-p", help="New directory path"),
    allocated_gb: Optional[float] = typer.Option(None, "--allocated-gb", help="New allocation limit in GB"),
    clear_allocation: bool = typer.Option(False, "--clear-allocation", help="Remove allocation limit"),
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
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    finally:
        ctx.close()


@app.command("remove")
def store_remove(
    name: str = typer.Argument(..., help="Volume name"),
    force: bool = typer.Option(False, "--force", help="Remove even if the volume contains objects (existing file references will become unresolvable)"),
) -> None:
    """Remove a volume from the configuration (does not delete files)."""
    ctx = get_ctx()
    try:
        ctx.store_svc.remove_volume(name, force=force)
        console.print(f"[green]Removed volume '{name}'.[/green]")
    except (NotFoundError, ValidationError) as e:
        console.print(f"[red]{e}[/red]")
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
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    finally:
        ctx.close()
