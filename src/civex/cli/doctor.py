"""civex doctor -- surface data integrity issues (CIVEX-169)."""

from __future__ import annotations

import typer

from civex.cli.utils import get_ctx
from civex.console import console


def doctor() -> None:
    """Check the project for data integrity issues, such as dangling reference/
    reference_list values left over from before deletes checked for referrers."""
    ctx = get_ctx()
    dangling = ctx.record_svc.find_dangling_references()
    ctx.close()

    if not dangling:
        console.print("[success]No integrity issues found.[/success]")
        return

    console.print(f"[error]Found {len(dangling)} dangling reference(s):[/error]")
    for d in dangling:
        console.print(
            f"  [cyan]{d['schema_name']}[/cyan] record {d['record_id']} "
            f"field '{d['field_name']}' -> missing record {d['dangling_target_id']}"
        )
    raise typer.Exit(1)
