from __future__ import annotations

from pathlib import Path

import typer
from sqlalchemy import create_engine

from civex.console import console
from civex.db.models import Base


def init(
    path: Path = typer.Argument(Path("."), help="Directory to initialize"),
) -> None:
    """Initialize a new civex project in the given directory."""
    target = path.resolve()
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

    console.print(f"[success]Initialized civex project at {target}[/success]")
    console.print(f"  Database   {db_path}")
    console.print(f"  Objects    {objects_dir}")
    console.print(f"  Workflows  {civex_dir / 'workflows'}")
    console.print(f"  Plugins    {civex_dir / 'plugins'}")
    console.print(f"  Config     {civex_dir / 'config.toml'}")
