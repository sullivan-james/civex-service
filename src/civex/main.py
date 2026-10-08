import typer
from typing import Annotated, Optional

from civex import __version__
from civex.domain.hosts import is_loopback
from civex.cli import (
    ai as ai_cli,
    dataset,
    db,
    history,
    plugin,
    policy,
    record,
    retention,
    schema,
    files,
    store,
    logs as logs_cli,
    sync as sync_cli,
    trash,
    view,
    workflow,
    worker,
)
from civex.cli.shell import run_shell
from civex.cli.demo import demo
from civex.cli.doctor import doctor
from civex.cli.dump import dump, restore
from civex.cli.init import init
from civex.cli.license import license_cmd
from civex.cli.resolve import resolve
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
app.command("demo", rich_help_panel=_START)(demo)
app.add_typer(db.app, name="db", rich_help_panel=_START)
app.command("license", rich_help_panel=_START)(license_cmd)
app.command("update", rich_help_panel=_START)(update)

app.add_typer(ai_cli.app, name="ai", rich_help_panel=_WORK)
app.add_typer(schema.app, name="schema", rich_help_panel=_WORK)
app.add_typer(dataset.app, name="collection", rich_help_panel=_WORK)
app.add_typer(record.app, name="record", rich_help_panel=_WORK)
app.add_typer(store.app, name="store", rich_help_panel=_WORK)
app.add_typer(files.app, name="files", rich_help_panel=_WORK)
app.add_typer(workflow.app, name="workflow", rich_help_panel=_WORK)
app.add_typer(plugin.app, name="plugin", rich_help_panel=_WORK)
app.add_typer(policy.app, name="policy", rich_help_panel=_WORK)
app.add_typer(worker.app, name="automation", rich_help_panel=_WORK)
app.add_typer(trash.app, name="trash", rich_help_panel=_WORK)
app.add_typer(sync_cli.app, name="sync", rich_help_panel=_COLLAB)
app.command("clone", rich_help_panel=_COLLAB)(sync_cli.clone)
app.add_typer(retention.app, name="retention", rich_help_panel=_WORK)
app.add_typer(history.app, name="history", rich_help_panel=_WORK)
app.add_typer(logs_cli.app, name="logs", rich_help_panel=_WORK)
app.add_typer(view.app, name="view", rich_help_panel=_WORK)
app.command("resolve", rich_help_panel=_WORK)(resolve)
app.command("doctor", rich_help_panel=_WORK)(doctor)

app.command("dump", rich_help_panel=_COLLAB)(dump)
app.command("restore", rich_help_panel=_COLLAB)(restore)


def _refuse_unless_serving() -> None:
    """`--sync-only` serves devices only, so the project must be an authority."""
    from civex.config import find_project_root, read_sync_flag

    root = find_project_root()
    if root is None or not read_sync_flag(root / "_civex", "serve"):
        typer.secho(
            "This project is not an authority: run `civex sync authority enable` first.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)


def _refuse_newer_database() -> None:
    """Stop `civex serve` before it starts when the project's database is from
    a newer civex, instead of serving a UI where every request fails. Quiet
    when there is no project or no readable database; the server reports those
    its own way."""
    from civex.config import load_config
    from civex.domain.exceptions import ConfigError
    from civex.services import db_service

    try:
        error = db_service.newer_database_error(load_config().db.url)
    except ConfigError:
        return
    if error is not None:
        from civex.cli.utils import print_database_too_new

        print_database_too_new(error)
        raise typer.Exit(1)


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
    sync_only: bool = typer.Option(
        False,
        "--sync-only",
        help="Serve only what devices following this project call, for an "
        "authority on a network: point the HTTPS proxy at this, and run the app "
        "itself on this machine.",
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

    if sync_only:
        _refuse_unless_serving()
        if open_browser:
            typer.secho("--open has nothing to open with --sync-only", err=True)
            raise typer.Exit(1)

    if not is_loopback(host):
        # Devices' tokens would cross the network in plain HTTP; the app
        # itself has no authentication at all.
        risk = (
            "device tokens would travel unencrypted (put an HTTPS proxy in front)"
            if sync_only
            else "the civex server has no authentication and would be reachable "
            "by other machines"
        )
        if not allow_remote:
            typer.secho(
                f"Refusing to bind to non-loopback address '{host}': {risk}.\n"
                "Re-run with --allow-remote if this is intentional (and put it behind a "
                "reverse proxy / firewall).",
                err=True,
                fg=typer.colors.RED,
                bold=True,
            )
            raise typer.Exit(1)
        typer.secho(
            f"WARNING: binding to '{host}': {risk}.",
            err=True,
            fg=typer.colors.YELLOW,
            bold=True,
        )

    # Signal the LocalGuardMiddleware to stand down when the operator has opted
    # into remote exposure. Inherited by uvicorn's reload subprocesses.
    if allow_remote:
        os.environ["CIVEX_ALLOW_REMOTE"] = "1"

    # How to start this server again after an update from the app
    # (civex.updates); not in dev mode, which is never updated that way.
    if not reload:
        import json
        import sys

        from civex.updates import SERVE_ARGS_ENV

        os.environ[SERVE_ARGS_ENV] = json.dumps(sys.argv[1:])

    _refuse_newer_database()

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

    # So an update of this copy can stop this server and start it again. Only
    # now, once nothing above has refused to start: a record of a server that
    # never ran would be found by an update.
    if not reload:
        from civex import running

        running.register(host, port)

    # log_config=None: defer all logging to civex's own structlog pipeline
    # (configured in create_app) so uvicorn's records flow through the same sinks.
    uvicorn.run(
        "civex.server.app:create_sync_app" if sync_only else "civex.server.app:app",
        factory=sync_only,
        host=host,
        port=port,
        reload=reload,
        reload_dirs=reload_dirs,
        log_config=None,
    )


@app.command("desktop", rich_help_panel=_START)
def desktop() -> None:
    """Open civex in a window of its own, with a project picker.

    Needs the desktop extra: `uv tool install --force "civex[desktop]"`.
    """
    try:
        import webview  # noqa: F401
    except ImportError:
        typer.secho(
            "The desktop window needs the desktop extra: "
            'uv tool install --force "civex[desktop]"',
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    from civex.desktop.tray import main as open_window

    open_window()


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
