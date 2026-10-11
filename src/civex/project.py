"""A project: what a context is built from, and how one is first made.

`Project` is a project as whoever hosts it sees it. `civex serve` and the CLI
host the one project in the current directory (`Project.local`); a service
hosting many projects builds one per request, with its own settings store,
engine and signed-in actor. Everything downstream (`build_context`, the
services) takes a `Project` and never asks where it came from.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from civex.config import Config, ConfigStore, FileConfigStore
from civex.domain.features import LOCAL_FEATURES

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


@dataclass
class Project:
    """What a context is built from.

    `actor` is who changes made through this context are recorded as (the
    project's chosen name or the OS user locally; the signed-in person on a
    hosted service). `device_id` is this machine's device, when the project
    follows an authority; None lets the context work it out. `engine` lets a
    host share one connection pool across projects (None: one per database
    URL), and `migrated` says the host already brought the database up to
    date, so the context needn't check on every request."""

    config: Config
    config_store: ConfigStore
    actor: str | None = None
    device_id: uuid.UUID | None = None
    engine: Engine | None = None
    migrated: bool = False
    # What the host offers for this project (`domain.features`): a project in
    # a folder on this machine gets everything a machine can do.
    features: frozenset[str] = LOCAL_FEATURES

    @classmethod
    def local(cls, config: Config) -> Project:
        """The project at `config.project_root`, kept in its config.toml, with
        changes recorded as its chosen name or the OS user."""
        from civex.identity import local_actor

        return cls(
            config=config,
            config_store=FileConfigStore(config.project_root),
            actor=local_actor(config.identity.name),
            features=local_features(config),
        )


def local_features(config: Config) -> frozenset[str]:
    """What a machine does for the project at `config`: everything, except
    that a project keeping its files in a bucket (`[store.s3]`) has no drives
    to manage, and offers files straight to and from the bucket instead."""
    from civex.domain import features

    s3 = config.store_config.s3
    if s3 is None:
        return LOCAL_FEATURES
    offered = set(LOCAL_FEATURES) - {features.VOLUMES}
    if s3.direct:
        offered.add(features.DIRECT_FILES)
    return frozenset(offered)


_README = """\
This directory is managed by civex (https://civexdata.github.io/civex-docs/).
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
.cache/
"""


def scaffold_project(
    path: Path, db_url: str | None = None, docker_managed: bool = False
) -> str:
    """
    Create a _civex/ directory tree inside *path* and initialise the database.

    If *db_url* is not supplied, a SQLite database at _civex/civex.db is used.
    *docker_managed* records whether *db_url* points at a container civex
    itself provisioned (see civex.services.db_service) — used later to decide
    whether to run container-recovery checks before a command connects.
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

    config_toml = f'[db]\nurl = "{db_url}"\n'
    if docker_managed:
        config_toml += "docker_managed = true\n"
    (civex_dir / "config.toml").write_text(config_toml)

    from sqlalchemy import create_engine
    from civex.db.migrate import ensure_schema_current

    engine = create_engine(db_url)
    ensure_schema_current(engine)
    engine.dispose()

    return db_url
