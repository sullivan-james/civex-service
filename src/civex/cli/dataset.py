from __future__ import annotations

import uuid
from collections import Counter
from typing import Optional

import typer
from rich.table import Table
from rich.tree import Tree

from civex.cli.utils import get_ctx as _ctx
from civex.console import console
from civex.domain.dtos import SchemaDTO
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError

app = typer.Typer(
    help="Manage collections (named containers for studies or investigations)"
)


@app.command("create")
def dataset_create(
    name: str = typer.Argument(..., help="Collection name"),
    description: Optional[str] = typer.Option(
        None, "--description", "-d", help="Collection description"
    ),
) -> None:
    """Create a new collection."""
    ctx = _ctx()
    try:
        dataset = ctx.dataset_svc.create(name, description=description)
        ctx.commit()
        console.print(f"[success]Created collection '{dataset.name}'.[/success]")
    except AlreadyExistsError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("list")
def dataset_list() -> None:
    """List all collections."""
    ctx = _ctx()
    datasets = ctx.dataset_svc.list_all()
    if not datasets:
        console.print(
            "[info]No collections yet. Use `civex collection create` to add one.[/info]"
        )
        return

    table = Table("Name", "Records", "Description")
    for d in datasets:
        table.add_row(d.name, str(d.record_count), d.description or "")
    console.print(table)


@app.command("show")
def dataset_show(name: str = typer.Argument(..., help="Collection name")) -> None:
    """Show a collection summary with record counts per schema."""
    ctx = _ctx()
    try:
        d = ctx.dataset_svc.get(name)
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    console.print(f"[bold]{d.name}[/bold]")
    console.print(f"  Records  {d.record_count}")
    if d.description:
        console.print(f"  {d.description}")

    if d.record_count > 0:
        records = ctx.record_svc.find(name, schema_name=None, filters=[], limit=100_000)
        counts = Counter(r.schema_name for r in records)
        table = Table("Schema", "Records")
        for schema_name, count in sorted(counts.items()):
            table.add_row(schema_name, str(count))
        console.print(table)


@app.command("update")
def dataset_update(
    name: str = typer.Argument(..., help="Collection name"),
    rename: Optional[str] = typer.Option(
        None, "--rename", help="New name for the collection"
    ),
    description: Optional[str] = typer.Option(
        None, "--description", "-d", help="New description for the collection"
    ),
) -> None:
    """Update a collection's name or description."""
    if rename is None and description is None:
        console.print(
            "[error]Provide at least one of --rename or --description.[/error]"
        )
        raise typer.Exit(1)
    ctx = _ctx()
    try:
        dataset = ctx.dataset_svc.update(name, new_name=rename, description=description)
        ctx.commit()
        if rename and rename != name:
            console.print(
                f"[warning]Workflow configs that reference '{name}' by name will need updating.[/warning]"
            )
        console.print(f"[success]Updated collection '{dataset.name}'.[/success]")
    except (NotFoundError, AlreadyExistsError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("delete")
def dataset_delete(
    name: str = typer.Argument(..., help="Collection name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Delete a collection and all its records to Recently Deleted.

    Reversible with `civex collection restore` within the retention window
    (see `civex trash list`); `civex collection purge` deletes permanently.
    """
    if not yes:
        typer.confirm(f"Delete collection '{name}' and all its records?", abort=True)
    ctx = _ctx()
    try:
        ctx.dataset_svc.delete(name)
        ctx.commit()
        console.print(f"[success]Deleted '{name}'.[/success]")
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("restore")
def dataset_restore(name: str = typer.Argument(..., help="Collection name")) -> None:
    """Restore a soft-deleted collection (and the records cascade-deleted with it)."""
    ctx = _ctx()
    try:
        ctx.dataset_svc.restore(name)
        ctx.commit()
        console.print(f"[success]Restored '{name}'.[/success]")
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("purge")
def dataset_purge(
    name: str = typer.Argument(..., help="Collection name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Permanently delete a collection that's already in Recently Deleted. Irreversible."""
    if not yes:
        typer.confirm(f"Permanently delete '{name}'? This cannot be undone.", abort=True)
    ctx = _ctx()
    try:
        ctx.dataset_svc.purge(name)
        ctx.commit()
        console.print(f"[success]Permanently deleted '{name}'.[/success]")
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)


@app.command("graph")
def dataset_graph(name: str = typer.Argument(..., help="Collection name")) -> None:
    """Show the schema hierarchy for schemas present in a collection."""
    ctx = _ctx()
    try:
        ctx.dataset_svc.get(name)
    except NotFoundError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    records = ctx.record_svc.find(name, schema_name=None, filters=[], limit=100_000)
    if not records:
        console.print("[info]Collection has no records yet.[/info]")
        return

    schema_counts: Counter[uuid.UUID] = Counter(r.schema_id for r in records)
    schema_ids_present = set(schema_counts)

    all_schemas = ctx.schema_svc.list_all()
    by_id: dict[uuid.UUID, SchemaDTO] = {s.id: s for s in all_schemas}

    # Find root ancestors of all present schemas.
    def _root(schema_id: uuid.UUID) -> uuid.UUID:
        s = by_id.get(schema_id)
        while s and s.parent_id and s.parent_id in by_id:
            s = by_id[s.parent_id]
        return s.id if s else schema_id

    roots = {_root(sid) for sid in schema_ids_present}

    children: dict[uuid.UUID, list[SchemaDTO]] = {}
    for s in all_schemas:
        if s.parent_id:
            children.setdefault(s.parent_id, []).append(s)

    def _label(schema: SchemaDTO) -> str:
        count = schema_counts.get(schema.id, 0)
        if schema.id in schema_ids_present:
            return f"[bold]{schema.name}[/bold] [dim]({count} record{'s' if count != 1 else ''})[/dim]"
        return f"[dim]{schema.name}[/dim]"

    def _build(schema: SchemaDTO, branch: Tree) -> None:
        for child in sorted(children.get(schema.id, []), key=lambda s: s.name):
            _build(child, branch.add(_label(child)))

    for root_id in sorted(roots, key=lambda i: by_id[i].name):
        root = by_id[root_id]
        tree = Tree(_label(root))
        _build(root, tree)
        console.print(tree)
