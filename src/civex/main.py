import typer

from civex.cli import dataset, plugin, record, schema, workflow
from civex.cli.init import init

app = typer.Typer(
    name="civex",
    help="Research data management system",
    no_args_is_help=True,
)

app.command("init")(init)
app.add_typer(schema.app, name="schema")
app.add_typer(dataset.app, name="dataset")
app.add_typer(record.app, name="record")
app.add_typer(workflow.app, name="workflow")
app.add_typer(plugin.app, name="plugin")

if __name__ == "__main__":
    app()
