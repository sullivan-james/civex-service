"""Shared project-initialisation logic used by both the CLI and the desktop launcher."""

from __future__ import annotations

from pathlib import Path

_README = """\
This directory is managed by civex (https://github.com/sullivan-james/civex).
Do not edit its contents manually — use the civex CLI or UI instead.

  config.toml   project configuration
  civex.db      SQLite database (records, schemas, workflows)
  objects/      content-addressed file storage
  workflows/    YAML workflow definitions
  plugins/      custom Python plugins
"""

# Keeps secrets (API keys in config.toml) and local state out of any surrounding
# git repository. workflows/ and plugins/ are intentionally NOT ignored — they
# are shareable definitions.
_GITIGNORE = """\
# civex local state — do not commit
config.toml
civex.db
civex.db-journal
civex.db-wal
objects/
logs/
"""


def scaffold_project(path: Path, db_url: str | None = None) -> str:
    """
    Create a _civex/ directory tree inside *path* and initialise the database.

    If *db_url* is not supplied, a SQLite database at _civex/civex.db is used.
    Returns the db_url that was written to config.toml.

    Raises FileExistsError if _civex/ already exists — callers decide how to
    surface that (CLI prints a warning; the desktop launcher silently skips).
    """
    civex_dir = path / "_civex"
    if civex_dir.exists():
        raise FileExistsError(f"Already initialised: {civex_dir}")

    path.mkdir(parents=True, exist_ok=True)
    civex_dir.mkdir()
    for sub in ("objects", "workflows", "plugins"):
        (civex_dir / sub).mkdir()

    (civex_dir / "README").write_text(_README)
    (civex_dir / ".gitignore").write_text(_GITIGNORE)

    if db_url is None:
        db_path = civex_dir / "civex.db"
        db_url = f"sqlite:///{db_path.as_posix()}"

    (civex_dir / "config.toml").write_text(f'[db]\nurl = "{db_url}"\n')

    from sqlalchemy import create_engine
    from civex.db.migrate import ensure_schema_current

    engine = create_engine(db_url)
    ensure_schema_current(engine)
    engine.dispose()

    return db_url
