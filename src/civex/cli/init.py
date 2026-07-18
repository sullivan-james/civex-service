from __future__ import annotations

from pathlib import Path

import typer
from sqlalchemy import create_engine

from civex.console import console
from civex.db.migrate import ensure_schema_current
from civex.project import scaffold_project


def init(
    path: Path = typer.Argument(Path("."), help="Directory to initialize"),
    bare: bool = typer.Option(
        False,
        "--bare",
        help="Create a bare repository (remote storage, no working directory)",
    ),
    sqlite: bool = typer.Option(
        False, "--sqlite", help="Force SQLite instead of Docker PostgreSQL"
    ),
) -> None:
    """Initialize a new civex project in the given directory."""
    if bare:
        _init_bare(path.resolve())
    else:
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
        from civex.cli._docker import (
            docker_available,
            docker_error_hint,
            setup_docker_postgres,
        )
        from civex.cli._pgdriver import detect_pg_driver, driver_install_hint

        if detect_pg_driver() is None:
            console.print(
                "[dim]No PostgreSQL driver found (psycopg2 / psycopg) — using SQLite.[/dim]"
            )
            console.print(driver_install_hint())
        elif docker_available():
            db_url = setup_docker_postgres(target.name)
            if db_url:
                return db_url, True
            console.print(
                "  [warning]Docker postgres setup failed — falling back to SQLite.[/warning]"
            )
        else:
            hint = docker_error_hint()
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


def _init_bare(target: Path) -> None:
    marker = target / "CIVEX_BARE"
    if marker.exists():
        console.print("[warning]Already a bare repository.[/warning]")
        raise typer.Exit(0)

    target.mkdir(parents=True, exist_ok=True)

    db_path = target / "civex.db"
    db_url = f"sqlite:///{db_path.as_posix()}"

    (target / "objects").mkdir(exist_ok=True)
    marker.write_text("")

    engine = create_engine(db_url)
    ensure_schema_current(engine)
    engine.dispose()

    console.print(f"[success]Initialized bare civex repository at {target}[/success]")
    console.print(f"  Database   {db_path}")
    console.print(f"  Objects    {target / 'objects'}")
