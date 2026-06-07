from __future__ import annotations

from pathlib import Path

import typer
from sqlalchemy import create_engine

from civex.console import console
from civex.db.models import Base


def init(
    path: Path = typer.Argument(Path("."), help="Directory to initialize"),
    bare: bool = typer.Option(False, "--bare", help="Create a bare repository (remote storage, no working directory)"),
) -> None:
    """Initialize a new civex project in the given directory."""
    if bare:
        _init_bare(path.resolve())
    else:
        _init_working(path.resolve())


def _init_working(target: Path) -> None:
    civex_dir = target / ".civex"

    if civex_dir.exists():
        console.print("[warning]Already initialized.[/warning]")
        raise typer.Exit(0)

    civex_dir.mkdir(parents=True)

    db_path = civex_dir / "civex.db"
    db_url = f"sqlite:///{db_path}"

    (civex_dir / "config.toml").write_text(
        f'[db]\nurl = "{db_url}"\n'
    )

    objects_dir = civex_dir / "objects"
    objects_dir.mkdir()
    (civex_dir / "workflows").mkdir()
    (civex_dir / "plugins").mkdir()

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    console.print(f"[success]Initialized civex project at {target}[/success]")
    console.print(f"  Database   {db_path}")
    console.print(f"  Objects    {objects_dir}")
    console.print(f"  Workflows  {civex_dir / 'workflows'}")
    console.print(f"  Plugins    {civex_dir / 'plugins'}")
    console.print(f"  Config     {civex_dir / 'config.toml'}")


def _init_bare(target: Path) -> None:
    marker = target / "CIVEX_BARE"
    if marker.exists():
        console.print("[warning]Already a bare repository.[/warning]")
        raise typer.Exit(0)

    target.mkdir(parents=True, exist_ok=True)

    db_path = target / "civex.db"
    db_url = f"sqlite:///{db_path}"

    (target / "objects").mkdir(exist_ok=True)
    marker.write_text("")

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    console.print(f"[success]Initialized bare civex repository at {target}[/success]")
    console.print(f"  Database   {db_path}")
    console.print(f"  Objects    {target / 'objects'}")
