"""
Plugin commands — stub.
Plugins are the individual steps within a workflow (data sources, transformations, outputs).
"""

import typer

app = typer.Typer(help="Inspect available workflow plugins")


@app.command("list")
def plugin_list() -> None:
    """List registered plugins. (Not yet implemented)"""
    typer.echo("Plugin commands coming soon.")


@app.command("info")
def plugin_info(name: str = typer.Argument(...)) -> None:
    """Show a plugin's inputs, outputs, and config schema. (Not yet implemented)"""
    typer.echo(f"Would show info for plugin '{name}'.")
