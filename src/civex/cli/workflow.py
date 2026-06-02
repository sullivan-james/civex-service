"""
Workflow commands — stub.
Workflows will be directed graphs of plugins that process record data.
"""
import typer

app = typer.Typer(help="Manage and run data processing workflows")


@app.command("list")
def workflow_list() -> None:
    """List workflows. (Not yet implemented)"""
    typer.echo("Workflow commands coming soon.")


@app.command("run")
def workflow_run(name: str = typer.Argument(...)) -> None:
    """Run a workflow. (Not yet implemented)"""
    typer.echo(f"Would run workflow '{name}'.")
