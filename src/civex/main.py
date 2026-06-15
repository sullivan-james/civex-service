from typing import Optional

import typer

from civex.cli import auth, dataset, plugin, record, remote, schema, workflow, worker
from civex.cli.clone import clone
from civex.cli.dump import dump, restore
from civex.cli.init import init
from civex.cli.log import commit, log
from civex.cli.plumbing import get_object, put_object, receive_pack, transfer_pack
from civex.cli.resolve import resolve
from civex.cli.status import status
from civex.cli.sync import pull, push

app = typer.Typer(
    name="civex",
    help="Research data management system",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

_START = "Start a working area"
_WORK = "Work on the current change"
_HISTORY = "Examine the history and state"
_COLLAB = "Collaborate"

app.command("init", rich_help_panel=_START)(init)
app.command("clone", rich_help_panel=_START)(clone)

app.add_typer(schema.app, name="schema", rich_help_panel=_WORK)
app.add_typer(dataset.app, name="dataset", rich_help_panel=_WORK)
app.add_typer(record.app, name="record", rich_help_panel=_WORK)
app.add_typer(workflow.app, name="workflow", rich_help_panel=_WORK)
app.add_typer(plugin.app, name="plugin", rich_help_panel=_WORK)
app.add_typer(worker.app, name="worker", rich_help_panel=_WORK)
app.command("commit", rich_help_panel=_WORK)(commit)
app.command("resolve", rich_help_panel=_WORK)(resolve)

app.command("status", rich_help_panel=_HISTORY)(status)
app.command("log", rich_help_panel=_HISTORY)(log)

app.add_typer(remote.app, name="remote", rich_help_panel=_COLLAB)
app.add_typer(auth.app, name="auth", rich_help_panel=_COLLAB)
app.command("push", rich_help_panel=_COLLAB)(push)
app.command("pull", rich_help_panel=_COLLAB)(pull)
app.command("dump", rich_help_panel=_COLLAB)(dump)
app.command("restore", rich_help_panel=_COLLAB)(restore)

# Plumbing commands — called by SSHTransport on the remote side via SSH subprocess.
app.command("transfer-pack", hidden=True)(transfer_pack)
app.command("receive-pack", hidden=True)(receive_pack)
app.command("get-object", hidden=True)(get_object)
app.command("put-object", hidden=True)(put_object)


@app.command("serve", rich_help_panel=_COLLAB)
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address"),
    port: int = typer.Option(8000, "--port", "-p", help="Port"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes (dev mode)"),
) -> None:
    """Start the civex HTTP API server."""
    try:
        import uvicorn
    except ImportError:
        typer.echo("uvicorn is required: pip install 'civex[server]'", err=True)
        raise typer.Exit(1)

    typer.echo(f"Starting civex server at http://{host}:{port}")
    typer.echo(f"API docs: http://{host}:{port}/docs")
    uvicorn.run("civex.server.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
