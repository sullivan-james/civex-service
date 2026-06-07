from __future__ import annotations

import typer

from civex.cli.utils import cli_load_config
from civex.config import save_config
from civex.console import console

app = typer.Typer(help="Manage the remote repository.")


@app.command("set")
def remote_set(
    url: str = typer.Argument(..., help="Remote URL (ssh://user@host:/path or file:///path)"),
) -> None:
    """Set (or replace) the remote URL for this project."""
    from civex.sync.transport import SyncError, get_transport
    try:
        get_transport(url)
    except SyncError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    config = cli_load_config()
    from civex.config import RemoteConfig
    config = config.__class__(
        project_root=config.project_root,
        db=config.db,
        remote=RemoteConfig(url=url),
    )
    save_config(config)
    console.print(f"[success]Remote set to {url}[/success]")


@app.command("show")
def remote_show() -> None:
    """Show the current remote configuration."""
    config = cli_load_config()
    if config.remote is None:
        console.print("[dim]No remote configured. Use `civex remote set <url>` to add one.[/dim]")
        return
    console.print(f"  URL            {config.remote.url}")
    console.print(f"  Last pushed    {config.remote.last_pushed_at or '(never)'}")
    console.print(f"  Last pulled    {config.remote.last_pulled_at or '(never)'}")


@app.command("unset")
def remote_unset() -> None:
    """Remove the remote from this project."""
    config = cli_load_config()
    if config.remote is None:
        console.print("[dim]No remote configured.[/dim]")
        return
    from civex.config import Config
    config = Config(project_root=config.project_root, db=config.db, remote=None)
    save_config(config)
    console.print("[success]Remote removed.[/success]")
