"""The models and the migrations describe the same database: what CI's
`alembic check` asks, here so it fails locally too. (A model's unique key once
said (kind, name) while its migration made (kind, name, version).)"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

from civex.db.models import Base


def test_a_migrated_database_is_what_the_models_say(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/civex/db/migrations"))
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        conn.commit()
        context = MigrationContext.configure(
            conn,
            opts={"compare_type": False, "render_as_batch": True},
        )
        differences = compare_metadata(context, Base.metadata)
    assert differences == []
