from typing import Optional

import typer

from civex.cli import dataset, plugin, record, remote, schema, workflow, worker
from civex.cli.clone import clone
from civex.cli.dump import dump, restore
from civex.cli.init import init
from civex.cli.plumbing import get_object, put_object, receive_pack, transfer_pack
from civex.cli.resolve import resolve
from civex.cli.sync import pull, push

app = typer.Typer(
    name="civex",
    help="Research data management system",
    no_args_is_help=True,
)

app.command("init")(init)
app.command("clone")(clone)
app.command("push")(push)
app.command("pull")(pull)
app.add_typer(schema.app, name="schema")
app.add_typer(dataset.app, name="dataset")
app.add_typer(record.app, name="record")
app.add_typer(workflow.app, name="workflow")
app.add_typer(plugin.app, name="plugin")
app.add_typer(worker.app, name="worker")
app.add_typer(remote.app, name="remote")
app.command("dump")(dump)
app.command("restore")(restore)
app.command("resolve")(resolve)

# Plumbing commands — called by SSHTransport on the remote side via SSH subprocess.
app.command("transfer-pack")(transfer_pack)
app.command("receive-pack")(receive_pack)
app.command("get-object")(get_object)
app.command("put-object")(put_object)


@app.command("serve")
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
