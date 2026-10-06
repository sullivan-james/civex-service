"""c8e2a4f6d913: views gain files_layout, and views saved before it keep working.

A view saved before the column existed must come through as a tree (the layout
every view had implicitly), and the column must be there to change."""

from __future__ import annotations

import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

_PRE = "a3d8f0b6c125"
_POST = "c8e2a4f6d913"


def _config() -> Config:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/civex/db/migrations"))
    return cfg


def test_an_existing_view_becomes_a_tree_and_the_layout_can_change(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'v.db'}")
    cfg = _config()
    schema_id, view_id = str(uuid.uuid4()), str(uuid.uuid4())

    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, _PRE)
        conn.commit()
        conn.execute(
            text(
                "INSERT INTO schemas (id, name, created_at) "
                "VALUES (:id, 'thing', '2024-01-01')"
            ),
            {"id": schema_id},
        )
        conn.execute(
            text(
                "INSERT INTO views (id, schema_id, name, columns, sort, created_at) "
                "VALUES (:id, :s, 'old', '[]', '[]', '2024-01-01')"
            ),
            {"id": view_id, "s": schema_id},
        )
        conn.commit()
        assert "files_layout" not in {
            c["name"] for c in inspect(conn).get_columns("views")
        }

        command.upgrade(cfg, _POST)
        conn.commit()

        assert "files_layout" in {c["name"] for c in inspect(conn).get_columns("views")}
        assert conn.execute(text("SELECT files_layout FROM views")).scalar() == "tree"
        conn.execute(text("UPDATE views SET files_layout = 'flat'"))
        conn.commit()
        assert conn.execute(text("SELECT files_layout FROM views")).scalar() == "flat"


def test_downgrade_drops_the_column(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'd.db'}")
    cfg = _config()

    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, _POST)
        conn.commit()

        command.downgrade(cfg, _PRE)
        conn.commit()

        assert "files_layout" not in {
            c["name"] for c in inspect(conn).get_columns("views")
        }
