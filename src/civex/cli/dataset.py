from __future__ import annotations

from typing import Optional

import typer
from rich.table import Table

from civex.config import load_config
from civex.console import console
from civex.context import build_local_context
from civex.domain.exceptions import AlreadyExistsError, NotFoundError

app = typer.Typer(help="Manage datasets (named collections of records)")


def _ctx():
    return build_local_context(load_config())


@app.command("create")
def dataset_create(
    name: str = typer.Argument(...),
    schema_name: str = typer.Option(..., "--schema", "-s"),
    description: Optional[str] = typer.Option(None, "--description", "-d"),
) -> None:
    """Create a new dataset."""
    ctx = _ctx()
    try:
        dataset = ctx.dataset_svc.create(name, schema_name=schema_name, description=description)
        ctx.commit()
        console.print(f"[success]Created dataset '{dataset.name}' (schema: {schema_name}).[/success]")
    except (NotFoundError, AlreadyExistsError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("list")
def dataset_list() -> None:
    """List all datasets."""
    ctx = _ctx()
    datasets = ctx.dataset_svc.list_all()
    if not datasets:
        console.print("[info]No datasets yet. Use `civex dataset create` to add one.[/info]")
        return

    table = Table("Name", "Schema", "Records", "Description")
    for d in datasets:
        table.add_row(d.name, d.schema_name, str(d.record_count), d.description or "")
    console.print(table)


@app.command("show")
def dataset_show(name: str = typer.Argument(...)) -> None:
    """Show a dataset summary."""
    ctx = _ctx()
    try:
        d = ctx.dataset_svc.get(name)
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    console.print(f"[bold]{d.name}[/bold]")
    console.print(f"  Schema   {d.schema_name}")
    console.print(f"  Records  {d.record_count}")
    if d.description:
        console.print(f"  {d.description}")


@app.command("delete")
def dataset_delete(
    name: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete a dataset and all its records."""
    if not yes:
        typer.confirm(f"Delete dataset '{name}' and all its records?", abort=True)
    ctx = _ctx()
    try:
        ctx.dataset_svc.delete(name)
        ctx.commit()
        console.print(f"[success]Deleted '{name}'.[/success]")
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
