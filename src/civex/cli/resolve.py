from __future__ import annotations

import typer

from civex.cli.utils import get_ctx as _ctx
from civex.console import console
from civex.domain.exceptions import NotFoundError


def resolve(
    id: str = typer.Argument(..., help="UUID or UUID prefix to look up"),
) -> None:
    """Identify a resource (schema, dataset, or record) by UUID or prefix."""
    ctx = _ctx()
    prefix = id.lower()

    for s in ctx.schema_svc.list_all():
        if str(s.id).startswith(prefix):
            console.print(f"schema   [bold]{s.name}[/bold]")
            return

    for d in ctx.dataset_svc.list_all():
        if str(d.id).startswith(prefix):
            console.print(f"dataset  [bold]{d.name}[/bold]   records: {d.record_count}")
            return

    try:
        record = ctx.record_svc.get(id)
        dataset = ctx.dataset_svc._datasets.get_by_id(record.dataset_id)
        dataset_name = dataset.name if dataset else str(record.dataset_id)
        console.print(f"record   [bold]{record.id}[/bold]   dataset: {dataset_name}")
        return
    except NotFoundError:
        pass

    console.print(f"[error]No resource found with ID '{id}'[/error]")
    raise typer.Exit(1)
