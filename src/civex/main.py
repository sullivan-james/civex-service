import typer
from typing import Annotated, Optional

from civex import __version__
from civex.cli import (
    ai as ai_cli,
    auth,
    dataset,
    db,
    history,
    plugin,
    policy,
    record,
    remote,
    retention,
    schema,
    store,
    trash,
    view,
    workflow,
    worker,
)
from civex.cli.shell import run_shell
from civex.cli.clone import clone
from civex.cli.demo import demo
from civex.cli.doctor import doctor
from civex.cli.dump import dump, restore
from civex.cli.init import init
from civex.cli.license import license_cmd
from civex.cli.plumbing import (
    get_object,
    head_seq,
    put_object,
    receive_pack,
    transfer_pack,
)
from civex.cli.resolve import resolve
from civex.cli.status import status
from civex.cli.sync import pull, push
from civex.cli.update import update

app = typer.Typer(
    name="civex",
    help="Research data management system",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"civex {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[
        Optional[bool],
        typer.Option(
            "--version",
            "-v",
            help="Show version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    pass


_START = "Start a working area"
_WORK = "Work on the current change"
_COLLAB = "Collaborate"

app.command("init", rich_help_panel=_START)(init)
app.command("clone", rich_help_panel=_START)(clone)
app.command("demo", rich_help_panel=_START)(demo)
app.add_typer(db.app, name="db", rich_help_panel=_START)
app.command("license", rich_help_panel=_START)(license_cmd)
app.command("update", rich_help_panel=_START)(update)

app.add_typer(ai_cli.app, name="ai", rich_help_panel=_WORK)
app.add_typer(schema.app, name="schema", rich_help_panel=_WORK)
app.add_typer(dataset.app, name="collection", rich_help_panel=_WORK)
app.add_typer(record.app, name="record", rich_help_panel=_WORK)
app.add_typer(store.app, name="store", rich_help_panel=_WORK)
app.add_typer(workflow.app, name="workflow", rich_help_panel=_WORK)
app.add_typer(plugin.app, name="plugin", rich_help_panel=_WORK)
app.add_typer(policy.app, name="policy", rich_help_panel=_WORK)
app.add_typer(worker.app, name="automation", rich_help_panel=_WORK)
app.add_typer(trash.app, name="trash", rich_help_panel=_WORK)
app.add_typer(retention.app, name="retention", rich_help_panel=_WORK)
app.add_typer(history.app, name="history", rich_help_panel=_WORK)
app.add_typer(view.app, name="view", rich_help_panel=_WORK)
app.command("resolve", rich_help_panel=_WORK)(resolve)
app.command("doctor", rich_help_panel=_WORK)(doctor)

app.command("status", rich_help_panel=_COLLAB)(status)

app.add_typer(remote.app, name="remote", rich_help_panel=_COLLAB)
app.add_typer(auth.app, name="auth", rich_help_panel=_COLLAB)
app.command("push", rich_help_panel=_COLLAB)(push)
app.command("pull", rich_help_panel=_COLLAB)(pull)
app.command("dump", rich_help_panel=_COLLAB)(dump)
app.command("restore", rich_help_panel=_COLLAB)(restore)

# Plumbing commands — called by SSHTransport on the remote side via SSH subprocess.
app.command("transfer-pack", hidden=True)(transfer_pack)
app.command("receive-pack", hidden=True)(receive_pack)
app.command("head-seq", hidden=True)(head_seq)
app.command("get-object", hidden=True)(get_object)
app.command("put-object", hidden=True)(put_object)


def _is_loopback_host(host: str) -> bool:
    """True if binding to *host* keeps the server reachable only from this machine."""
    import ipaddress

    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@app.command("serve", rich_help_panel=_COLLAB)
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address"),
    port: int = typer.Option(8000, "--port", "-p", help="Port"),
    reload: bool = typer.Option(
        False, "--reload", help="Auto-reload on code changes (dev mode)"
    ),
    allow_remote: bool = typer.Option(
        False,
        "--allow-remote",
        help="Permit binding to a non-loopback address. The server has NO authentication — "
        "only use this on a trusted network behind a reverse proxy or firewall.",
    ),
    log_level: str = typer.Option(
        "INFO",
        "--log-level",
        help="Log level: DEBUG | INFO | WARNING | ERROR. Overrides [logging] in config.toml.",
    ),
    open_browser: bool = typer.Option(
        False,
        "--open",
        help="Open the browser once the server is up. If civex is already "
        "running on this port, just open the browser.",
    ),
) -> None:
    """Start the civex HTTP API server."""
    try:
        import uvicorn
    except ImportError:
        typer.echo("uvicorn is required: pip install 'civex[server]'", err=True)
        raise typer.Exit(1)

    import os

    # Passed to the app (and inherited by uvicorn's --reload subprocess) so logging
    # is configured inside the worker that actually serves requests.
    os.environ["CIVEX_LOG_LEVEL"] = log_level.upper()

    if not _is_loopback_host(host):
        if not allow_remote:
            typer.secho(
                f"Refusing to bind to non-loopback address '{host}': the civex server has no "
                "authentication and would be reachable by other machines.\n"
                "Re-run with --allow-remote if this is intentional (and put it behind a "
                "reverse proxy / firewall).",
                err=True,
                fg=typer.colors.RED,
                bold=True,
            )
            raise typer.Exit(1)
        typer.secho(
            f"WARNING: binding to '{host}' — the server is reachable by other machines and has "
            "NO authentication. Anyone who can reach it can read/write your data and run code.",
            err=True,
            fg=typer.colors.YELLOW,
            bold=True,
        )

    # Signal the LocalGuardMiddleware to stand down when the operator has opted
    # into remote exposure. Inherited by uvicorn's reload subprocesses.
    if allow_remote:
        os.environ["CIVEX_ALLOW_REMOTE"] = "1"

    if open_browser:
        from civex.launcher import is_serving, open_url, open_when_ready

        url = f"http://{host}:{port}"
        if is_serving(host, port):
            typer.echo(f"Civex is already running at {url}; opening it.")
            open_url(url)
            raise typer.Exit(0)
        open_when_ready(url)

    typer.echo(f"Starting civex server at http://{host}:{port}")
    typer.echo(f"API docs: http://{host}:{port}/docs")
    if reload:
        typer.echo(
            "Dev mode: for frontend HMR run `cd frontend && npm run dev` "
            "and browse to http://localhost:5173"
        )
    # reload_dirs pinned to the installed package source: uvicorn otherwise
    # falls back to watching Path.cwd(), which is wherever `civex serve` was
    # launched from (e.g. a _civex project dir with no Python source at all)
    # rather than wherever the editable install actually lives -- silently
    # never reloading on code changes.
    from pathlib import Path

    reload_dirs = [str(Path(__file__).resolve().parent)] if reload else None

    # log_config=None: defer all logging to civex's own structlog pipeline
    # (configured in create_app) so uvicorn's records flow through the same sinks.
    uvicorn.run(
        "civex.server.app:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=reload_dirs,
        log_config=None,
    )


@app.command("shortcut", rich_help_panel=_START)
def shortcut() -> None:
    """Put a Desktop shortcut that starts civex for this project and opens it."""
    from civex.config import find_project_root
    from civex.domain.exceptions import ConfigError
    from civex.launcher import create_shortcut

    root = find_project_root()
    if root is None:
        typer.secho(
            "No civex project here. Run `civex init` first.", fg=typer.colors.RED
        )
        raise typer.Exit(1)
    try:
        path = create_shortcut(root)
    except ConfigError as e:
        typer.secho(str(e), fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.echo(f"Created {path}")


@app.command("shell")
def shell() -> None:
    """Start an interactive civex shell (no 'civex' prefix needed)."""
    run_shell()


if __name__ == "__main__":
    app()
