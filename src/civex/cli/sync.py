"""
civex push  — push local changes to the remote bare repository.
civex pull  — pull remote changes into the local project.
"""

from __future__ import annotations

import typer

from civex.cli.utils import cli_load_config
from civex.console import console
from civex.services.sync_service import SyncService
from civex.sync.transport import SyncError


def push() -> None:
    """Push local changes to the remote bare repository."""
    config = cli_load_config()
    if config.remote is None:
        console.print(
            "[error]No remote configured. Run `civex remote set <url>` first.[/error]"
        )
        raise typer.Exit(1)

    console.print(f"Pushing to [bold]{config.remote.url}[/bold] ...")

    from civex.context import build_local_context

    ctx = build_local_context(config)
    try:
        svc = SyncService(config, ctx._session, ctx.audit_svc, ctx.file_svc._store)
        result = svc.push()
    except SyncError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()

    if result.is_empty:
        console.print("[dim]Nothing to push — no new commits.[/dim]")
        return

    console.print("[success]Push complete.[/success]")
    console.print(f"  Schemas    {result.schemas}")
    console.print(f"  Datasets   {result.datasets}")
    console.print(f"  Records    {result.records}")
    console.print(f"  Objects    {result.objects} uploaded")
    console.print(f"  Seq        {result.from_seq} → {result.to_seq}")


def pull() -> None:
    """Pull remote changes into the local project."""
    config = cli_load_config()
    if config.remote is None:
        console.print(
            "[error]No remote configured. Run `civex remote set <url>` first.[/error]"
        )
        raise typer.Exit(1)

    console.print(f"Pulling from [bold]{config.remote.url}[/bold] ...")

    from civex.context import build_local_context

    ctx = build_local_context(config)
    try:
        svc = SyncService(config, ctx._session, ctx.audit_svc, ctx.file_svc._store)
        result = svc.pull()
    except SyncError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()

    if result.is_empty:
        console.print("[dim]Already up to date.[/dim]")
        return

    console.print("[success]Pull complete.[/success]")
    console.print(f"  Schemas    {result.schemas}")
    console.print(f"  Datasets   {result.datasets}")
    console.print(f"  Records    {result.records}")
    console.print(
        f"  Objects    {result.objects} available remotely (fetched on demand)"
    )
    console.print(f"  Seq        {result.from_seq} → {result.to_seq}")
