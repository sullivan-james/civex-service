"""d6c2a8f41b07: a conflict row gains what the value was and who wrote the one that
stayed; rows already there are kept."""

from __future__ import annotations

import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

_PRE = "c9e1f4a7b3d2"
_POST = "d6c2a8f41b07"


def _config() -> Config:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/civex/db/migrations"))
    return cfg


def test_existing_conflicts_are_kept_and_gain_empty_context(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 's.db'}")
    cfg = _config()
    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, _PRE)
        conn.commit()
        conn.execute(
            text(
                "INSERT INTO sync_conflicts (id, kind, entity_type, entity_id, status, "
                "created_at) VALUES (:i, 'conflict', 'record', :e, 'open', '2024-01-01')"
            ),
            {"i": str(uuid.uuid4()), "e": str(uuid.uuid4())},
        )
        conn.commit()

        command.upgrade(cfg, _POST)
        conn.commit()

        cols = {c["name"] for c in inspect(conn).get_columns("sync_conflicts")}
        assert {"base", "theirs_actor", "theirs_at"} <= cols
        row = conn.execute(
            text("SELECT kind, base, theirs_actor, theirs_at FROM sync_conflicts")
        ).one()
        assert tuple(row) == ("conflict", None, None, None)

        command.downgrade(cfg, _PRE)
        conn.commit()
        cols = {c["name"] for c in inspect(conn).get_columns("sync_conflicts")}
        assert not ({"base", "theirs_actor", "theirs_at"} & cols)
