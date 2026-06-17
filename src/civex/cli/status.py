"""civex status — show uncommitted changes and unpushed commits."""
from __future__ import annotations


from civex.cli.utils import get_ctx
from civex.console import console


def status() -> None:
    """Show staged (uncommitted) changes and unpushed commits."""
    ctx = get_ctx()
    staged = ctx.audit_svc.count_staged()
    unpushed = ctx.audit_svc.list_unpushed_commits()
    ctx.close()

    has_staged = staged["total"] > 0
    has_unpushed = len(unpushed) > 0

    if not has_staged and not has_unpushed:
        console.print("[green]Nothing to commit, nothing to push.[/green]")
        return

    if has_staged:
        console.print("[bold]Changes staged for commit:[/bold]")
        if staged["records"]:
            console.print(f"  [cyan]records[/cyan]   {staged['records']} change(s)")
        if staged["schemas"]:
            console.print(f"  [cyan]schemas[/cyan]   {staged['schemas']} change(s)")
        if staged["datasets"]:
            console.print(f"  [cyan]datasets[/cyan]  {staged['datasets']} change(s)")
        console.print("")
        console.print('  (use "civex commit -m \'<message>\'" to commit)')
        console.print("")

    if has_unpushed:
        console.print(f"[bold]Commits not yet pushed[/bold] ({len(unpushed)}):")
        for c in unpushed:
            date = c.created_at.strftime("%Y-%m-%d") if c.created_at else "?"
            console.print(
                f"  [dim]{str(c.id)[:8]}[/dim]  {date}  {c.message or '[dim]—[/dim]'}"
            )
        console.print("")
        console.print('  (use "civex push" to upload)')
