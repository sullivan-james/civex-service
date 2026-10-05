from __future__ import annotations

from pathlib import Path

import typer

from civex.console import console
from civex.domain.exceptions import ValidationError
from civex.project import scaffold_project
from civex.services import db_service


def init(
    path: Path = typer.Argument(Path("."), help="Directory to initialize"),
    sqlite: bool = typer.Option(
        False, "--sqlite", help="Force SQLite instead of Docker PostgreSQL"
    ),
) -> None:
    """Initialize a new civex project in the given directory."""
    _init_working(path.resolve(), use_sqlite=sqlite)


def _init_working(target: Path, use_sqlite: bool = False) -> None:
    civex_dir = target / "_civex"

    if civex_dir.exists():
        console.print("[warning]Already initialized.[/warning]")
        raise typer.Exit(0)

    db_url, docker_managed = _resolve_db_url(target, civex_dir, use_sqlite)
    scaffold_project(target, db_url=db_url, docker_managed=docker_managed)

    console.print(f"\n[success]Initialized civex project at {target}[/success]")
    console.print(f"  Database   {_display_url(db_url)}")
    console.print(f"  Objects    {civex_dir / 'objects'}")
    console.print(f"  Workflows  {civex_dir / 'workflows'}")
    console.print(f"  Plugins    {civex_dir / 'plugins'}")
    console.print(f"  Config     {civex_dir / 'config.toml'}")


def _resolve_db_url(
    target: Path, civex_dir: Path, use_sqlite: bool
) -> tuple[str, bool]:
    """Return (db_url, docker_managed), starting Docker postgres if available."""
    if not use_sqlite:
        if db_service.detect_pg_driver() is None:
            console.print(
                "[dim]No PostgreSQL driver found (psycopg2 / psycopg) — using SQLite.[/dim]"
            )
            console.print(db_service.driver_install_hint())
        elif db_service.docker_available():
            console.print("Setting up PostgreSQL via Docker...", end="  ")
            try:
                db_url = db_service.provision_docker_postgres(target.name)
                console.print("[success]OK[/success]")
                return db_url, True
            except ValidationError as exc:
                console.print("[warning]failed[/warning]")
                console.print(f"  [warning]{exc}[/warning]")
                console.print("  [warning]Falling back to SQLite.[/warning]")
        else:
            hint = db_service.docker_error_hint()
            console.print("[dim]Docker not available — using SQLite.[/dim]")
            console.print(f"  [dim]{hint}[/dim]")
            console.print(
                "  [dim]Run `civex db setup-docker` or `civex db setup-postgres` "
                "to switch to PostgreSQL.[/dim]"
            )

    db_path = civex_dir / "civex.db"
    return f"sqlite:///{db_path.as_posix()}", False


def _display_url(db_url: str) -> str:
    """Redact password and driver prefix for display."""
    import urllib.parse

    try:
        parsed = urllib.parse.urlparse(db_url)
        if parsed.scheme.startswith("postgresql"):
            return f"postgresql://{parsed.hostname}:{parsed.port or 5432}{parsed.path}"
    except Exception:
        pass
    return db_url
