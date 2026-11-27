"""civex doctor -- check the installation and the project's data integrity."""

from __future__ import annotations

import typer

from civex.cli.utils import cli_load_config
from civex.config import find_project_root
from civex.console import console
from civex.install_check import remove_stale_environments, run_install_checks
from civex.project import Project
from civex.services import health_service

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
    repair: bool = typer.Option(
        False,
        "--repair",
        help="Back the database up, then add the tables and columns it lacks.",
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
    a bucket but files are still recorded on drives, out of reach. The same
    checks are on the Health page of the app.

    With --fix, deletes cached plugin environments that point at a Python that
    no longer exists (uv rebuilds them the next time the plugin runs).

    With --repair, backs the database up (into _civex/backups) and adds the
    tables and columns it lacks, then checks again. Safe to run twice.
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

    in_project = find_project_root() is not None
    if repair:
        if not in_project:
            console.print("[error]--repair needs a civex project.[/error]")
            raise typer.Exit(1)
        project = Project.local(cli_load_config())
        try:
            result = health_service.repair_database(project)
        except health_service.RepairRefused as e:
            console.print(f"[error]{e}[/error]")
            raise typer.Exit(1)
        console.print(f"Backed the database up to {result.backup}")
        if result.added:
            console.print(f"Added: {', '.join(result.added)}")
        else:
            console.print("[dim]Nothing was missing.[/dim]")

    if in_project:
        from civex.cli.utils import get_ctx

        get_ctx().close()  # a stopped Docker database is started, or says why
        report = health_service.check_health(Project.local(cli_load_config()))
    else:
        report = health_service.HealthReport(install=run_install_checks(), structure=[])

    for check in report.install or []:
        console.print(f"{_MARK[check.status]} {check.name}: {check.detail}")
        if check.fix and check.status != "ok":
            console.print(f"     [dim]{check.fix}[/dim]")

    if not in_project:
        console.print("[dim]Not in a civex project, so no data checks were run.[/dim]")
        if report.failed:
            raise typer.Exit(1)
        return

    found = [p for p in report.problems() if p.kind != "install"]
    for problem in found:
        mark = _MARK[problem.severity]
        console.print(f"{mark} {problem.message}")
        for item in problem.items[:50] if problem.kind != "database" else ():
            console.print(f"  {item}")
        if problem.fix:
            hint = problem.fix
            if problem.kind == "database":
                hint = "Run `civex doctor --repair`, or open Health in the app."
            console.print(f"     [dim]{hint}[/dim]")

    if not found:
        console.print("[success]No integrity issues found.[/success]")
    if report.failed:
        raise typer.Exit(1)
