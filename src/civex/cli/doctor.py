"""civex doctor -- check the installation and the project's data integrity."""

from __future__ import annotations

import typer

from civex.cli.utils import get_ctx
from civex.config import find_project_root
from civex.console import console
from civex.install_check import remove_stale_environments, run_install_checks
from civex.services import db_service

_MARK = {
    "ok": "[success]ok[/success]",
    "warn": "[warning]!![/warning]",
    "fail": "[error]xx[/error]",
}


def doctor(
    fix: bool = typer.Option(
        False,
        "--fix",
        help="Remove cached plugin environments whose Python is gone.",
    ),
) -> None:
    """Check this civex install and, inside a project, its data.

    The install checks look for another copy of civex shadowing this one on
    PATH, for uv, and for a working Python for custom plugins. The project
    checks look for integrity issues: dangling reference/reference_list values
    left over from before deletes checked for referrers, and live records that
    sit under a deleted record (out of sight; `civex record restore-above`
    puts one back in place). It checks the database has every table and
    column this civex expects, whatever revision it is stamped at. It also
    warns when the project keeps its files in
    a bucket but files are still recorded on drives, out of reach.

    With --fix, deletes cached plugin environments that point at a Python that
    no longer exists (uv rebuilds them the next time the plugin runs).
    """
    if fix:
        removed = remove_stale_environments()
        if removed:
            console.print(
                f"Removed {len(removed)} out-of-date plugin environment(s); "
                "they are rebuilt the next time their plugin runs."
            )
        else:
            console.print("[dim]No out-of-date plugin environments to remove.[/dim]")

    failed = False
    for check in run_install_checks():
        console.print(f"{_MARK[check.status]} {check.name}: {check.detail}")
        if check.fix and check.status != "ok":
            console.print(f"     [dim]{check.fix}[/dim]")
        failed = failed or check.status == "fail"

    if find_project_root() is None:
        console.print("[dim]Not in a civex project, so no data checks were run.[/dim]")
        if failed:
            raise typer.Exit(1)
        return

    ctx = get_ctx()
    lacking = db_service.structure_problems(ctx.config.db.url)
    if lacking:
        shown = ", ".join(lacking[:8]) + (" …" if len(lacking) > 8 else "")
        console.print(
            f"{_MARK['fail']} Database: it is stamped as up to date but lacks "
            f"what this civex expects: {shown}"
        )
        console.print(
            "     [dim]A migration it was stamped past never ran here. Back up "
            "the database, then apply the missing migrations (`civex db "
            "current` shows its revision).[/dim]"
        )
        ctx.close()  # the data checks would trip over what is missing
        raise typer.Exit(1)
    dangling = ctx.record_svc.find_dangling_references()
    orphans, orphan_total = ctx.record_svc.orphans(50)
    stranded = ctx.bucket_svc.status()
    ctx.close()

    if stranded.left_on_drives:
        console.print(
            f"{_MARK['warn']} Files: {stranded.left_on_drives:,} file(s) are "
            f"recorded on drives, but this project keeps its files in the bucket "
            f"'{stranded.bucket}', so they can't be reached."
        )
        console.print(
            "     [dim]Take [store.s3] out of _civex/config.toml to reach them "
            "again; civex doesn't move files between drives and a bucket.[/dim]"
        )

    if not dangling and not orphan_total:
        console.print("[success]No integrity issues found.[/success]")
        if failed:
            raise typer.Exit(1)
        return

    if dangling:
        console.print(f"[error]Found {len(dangling)} dangling reference(s):[/error]")
        for d in dangling:
            console.print(
                f"  [cyan]{d['schema_name']}[/cyan] record {d['record_id']} "
                f"field '{d['field_name']}' -> missing record "
                f"{d['dangling_target_id']}"
            )
    if orphan_total:
        console.print(
            f"[error]Found {orphan_total} record(s) under a deleted record "
            "(out of sight, and refused by a sync server):[/error]"
        )
        for o in orphans:
            top = o.above[0]
            console.print(
                f"  [cyan]{o.record.schema_name}[/cyan] "
                f"{o.record.natural_name or ''} {str(o.record.id)[:8]} under "
                f"deleted {top.schema_name} {top.natural_name or ''} "
                f"{str(top.id)[:8]}"
            )
        if orphan_total > len(orphans):
            console.print(f"  [dim]...and {orphan_total - len(orphans)} more[/dim]")
        console.print(
            "  [dim]Put one back in place with `civex record restore-above <id>`, "
            "or delete it.[/dim]"
        )
    raise typer.Exit(1)
