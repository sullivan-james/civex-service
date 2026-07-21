from __future__ import annotations

import typer

from civex.cli.utils import get_ctx
from civex.console import console
from civex.domain.exceptions import CivexError

app = typer.Typer(help="View this project's data/governance policy documents.")


@app.command("list")
def policy_list() -> None:
    """List org-authored policy documents (_civex/policies/*.md)."""
    ctx = get_ctx()
    policies = ctx.policy_svc.list()
    ctx.close()

    if not policies:
        console.print(
            "[dim]No policy documents configured. Add markdown files to "
            "_civex/policies/ to have them show up here.[/dim]"
        )
        return

    for p in policies:
        console.print(f"[bold]{p.stem}[/bold]  {p.title}")


@app.command("show")
def policy_show(stem: str = typer.Argument(..., help="Policy filename stem")) -> None:
    """Print one policy document's content."""
    ctx = get_ctx()
    try:
        policy = ctx.policy_svc.get(stem)
    except CivexError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    finally:
        ctx.close()

    console.print(policy.content)
