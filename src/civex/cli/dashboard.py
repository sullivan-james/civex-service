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
        elif c.view is not None:
            what = f"analysis: {c.view.schema_name}/{c.view.name}"
        else:
            what = "analysis: (deleted)"
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
    analysis: Optional[str] = typer.Option(
        None,
        "--analysis",
        "-a",
        help="A saved analysis, as 'schema/view name'",
    ),
    widget: Optional[str] = typer.Option(
        None, "--widget", "-w", help=f"A built-in widget: {', '.join(WIDGETS)}"
    ),
    size: str = typer.Option("small", "--size", help=f"How wide: {' or '.join(SIZES)}"),
    title: Optional[str] = typer.Option(
        None, "--title", help="A title of its own (default: the card's name)"
    ),
    position: Optional[int] = typer.Option(
        None, "--at", help="Where to put it, from 1 (default: at the end)"
    ),
) -> None:
    """Put a saved analysis or a built-in widget on the Analytics page. The
    page is shared: everyone sees the change, and it shows in Activity."""
    ctx = _ctx()
    try:
        view_id = None
        if analysis:
            schema, _, name = analysis.partition("/")
            if not name:
                raise ValidationError("Name the analysis as 'schema/view name'")
            view_id = str(ctx.view_svc.get(schema, name).id)
        page = ctx.dashboard_svc.add(
            view_id=view_id,
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
    """Take a card off the Analytics page (the saved analysis itself stays)."""
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
