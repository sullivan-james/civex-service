from __future__ import annotations

from typing import Optional

import typer
from rich.table import Table

from civex.cli.utils import get_ctx as _ctx
from civex.console import console
from civex.domain.dashboard import SIZES, WIDGETS
from civex.domain.exceptions import NotFoundError, ValidationError

app = typer.Typer(help="The Analytics page: the cards everyone in the project sees")


def _print(page) -> None:
    table = Table("Card", "What", "Size")
    for c in page.cards:
        card = c.card
        if card.widget:
            what = f"widget: {WIDGETS[card.widget][0]}"
        else:
            chart = card.chart.to_dict()
            drawn = (
                f"a map of {chart['map']}"
                if "map" in chart
                else ", ".join(chart["measures"])
                + (" by " + ", ".join(chart["group_by"]) if chart["group_by"] else "")
            )
            where = c.collection_name or "every collection"
            what = f"chart: {c.schema_name or '(gone)'} in {where}: {drawn}"
        if card.title:
            what += f' as "{card.title}"'
        table.add_row(card.id, what, card.size)
    console.print(table)
    if not page.edited:
        console.print("Nobody has changed the page yet: it shows every widget.")


@app.command("show")
def dashboard_show() -> None:
    """List the cards on the Analytics page, in order, with the id each is
    removed by."""
    ctx = _ctx()
    try:
        _print(ctx.dashboard_svc.page())
    finally:
        ctx.close()


@app.command("add")
def dashboard_add(
    schema: Optional[str] = typer.Option(
        None, "--schema", "-s", help="A chart of this kind of record"
    ),
    by: Optional[list[str]] = typer.Option(
        None,
        "--by",
        "-b",
        help="One bar for each value of a field (repeatable, up to 3), as "
        "'civex record summarise --by' takes it",
    ),
    measure: Optional[list[str]] = typer.Option(
        None,
        "--measure",
        "-m",
        help="What each bar shows (repeatable), as 'civex record summarise "
        "--measure' takes it; 'count' when none is given",
    ),
    map_field: Optional[str] = typer.Option(
        None, "--map", help="A map of this location field instead of bars"
    ),
    collection: Optional[str] = typer.Option(
        None, "--in", help="Only records in this collection (omit for every one)"
    ),
    where: Optional[list[str]] = typer.Option(
        None, "--where", "-w", help="Only records matching field=value (repeatable)"
    ),
    search: Optional[str] = typer.Option(
        None, "--search", "-q", help="Only records whose values contain this text"
    ),
    widget: Optional[str] = typer.Option(
        None, "--widget", help=f"A built-in widget: {', '.join(WIDGETS)}"
    ),
    size: str = typer.Option("small", "--size", help=f"How wide: {' or '.join(SIZES)}"),
    title: Optional[str] = typer.Option(
        None, "--title", help="A title of its own (default: the card's name)"
    ),
    position: Optional[int] = typer.Option(
        None, "--at", help="Where to put it, from 1 (default: at the end)"
    ),
) -> None:
    """Put a chart or a built-in widget on the Analytics page. A chart is of
    one kind of record (--schema): bars (--by, --measure) or a map (--map),
    over the records --in, --where and --search choose. The page is shared:
    everyone sees the change, and it shows in Activity."""
    ctx = _ctx()
    try:
        chart = None
        if schema:
            chart = (
                {"map": map_field}
                if map_field
                else {
                    "group_by": list(by or []),
                    "measures": list(measure or ["count"]),
                }
            )
        tree = None
        if where:
            leaves = []
            for item in where:
                field, sep, value = item.partition("=")
                if not sep:
                    raise ValidationError("Write --where as field=value")
                leaves.append({"field": field, "op": "eq", "value": value})
            tree = leaves[0] if len(leaves) == 1 else {"and": leaves}
        page = ctx.dashboard_svc.add(
            chart=chart,
            schema=schema,
            collection=collection,
            search=search,
            filter_tree=tree,
            widget=widget,
            size=size,
            title=title,
            position=None if position is None else position - 1,
        )
        ctx.commit()
        _print(page)
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()


@app.command("remove")
def dashboard_remove(
    card: str = typer.Argument(..., help="The card's id, as 'show' lists it"),
) -> None:
    """Take a card off the Analytics page."""
    ctx = _ctx()
    try:
        page = ctx.dashboard_svc.remove(card)
        ctx.commit()
        _print(page)
    except (NotFoundError, ValidationError) as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)
    finally:
        ctx.close()
