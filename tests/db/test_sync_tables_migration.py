"""c9e1f4a7b3d2: the sync tables, the audit indexes and `apply_state`.

An existing project gets its own project id and keeps its history, with every
entry reading as applied; going back removes what was added."""

from __future__ import annotations

import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

_PRE = "a3d8f0b6c125"
_POST = "c9e1f4a7b3d2"


def _config() -> Config:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/civex/db/migrations"))
    return cfg


def test_existing_history_is_kept_and_the_project_gets_an_id(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 's.db'}")
    cfg = _config()
    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, _PRE)
        conn.commit()
        entry = str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO audit_log (id, action, entity_type, entity_id, timestamp) "
                "VALUES (:i, 'create', 'record', :e, '2024-01-01')"
            ),
            {"i": entry, "e": str(uuid.uuid4())},
        )
        conn.commit()
        command.upgrade(cfg, _POST)
        conn.commit()

        tables = set(inspect(conn).get_table_names())
        assert {"sync_meta", "sync_ops", "sync_devices", "sync_conflicts"} <= tables
        meta = conn.execute(
            text("SELECT project_id, head_seq, cursor FROM sync_meta")
        ).one()
        uuid.UUID(str(meta[0]))
        assert (meta[1], meta[2]) == (0, 0)
        assert (
            conn.execute(text("SELECT apply_state FROM audit_log")).scalar()
            == "applied"
        )

        command.downgrade(cfg, _PRE)
        conn.commit()
        assert "sync_meta" not in inspect(conn).get_table_names()
        cols = {c["name"] for c in inspect(conn).get_columns("audit_log")}
        assert "apply_state" not in cols
        assert conn.execute(text("SELECT count(*) FROM audit_log")).scalar() == 1
