"""Shared project-initialisation logic used by both the CLI and the desktop launcher."""
from __future__ import annotations

from pathlib import Path


def scaffold_project(path: Path, db_url: str | None = None) -> str:
    """
    Create a .civex/ directory tree inside *path* and initialise the database.

    If *db_url* is not supplied, a SQLite database at .civex/civex.db is used.
    Returns the db_url that was written to config.toml.

    Raises FileExistsError if .civex/ already exists — callers decide how to
    surface that (CLI prints a warning; the desktop launcher silently skips).
    """
    civex_dir = path / ".civex"
    if civex_dir.exists():
        raise FileExistsError(f"Already initialised: {civex_dir}")

    path.mkdir(parents=True, exist_ok=True)
    civex_dir.mkdir()
    for sub in ("objects", "workflows", "plugins"):
        (civex_dir / sub).mkdir()

    if db_url is None:
        db_path = civex_dir / "civex.db"
        db_url = f"sqlite:///{db_path.as_posix()}"

    (civex_dir / "config.toml").write_text(f'[db]\nurl = "{db_url}"\n')

    from sqlalchemy import create_engine
    from civex.db.models import Base
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    return db_url
