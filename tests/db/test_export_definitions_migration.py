"""d9f3b1c7e4a2: exports saved with a schema get their table, and nothing else is
disturbed."""

from __future__ import annotations

import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

_PRE = "c8e2a4f6d913"
_POST = "d9f3b1c7e4a2"


def _config() -> Config:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/civex/db/migrations"))
    return cfg


def test_the_table_is_added_and_an_export_can_be_saved_in_it(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'e.db'}")
    cfg = _config()
    schema_id = str(uuid.uuid4())

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
        conn.commit()
        assert "export_definitions" not in inspect(conn).get_table_names()

        command.upgrade(cfg, _POST)
        conn.commit()

        columns = {c["name"] for c in inspect(conn).get_columns("export_definitions")}
        assert {
            "schema_id",
            "holder_schema_id",
            "name",
            "fields",
            "filter_tree",
            "files_layout",
            "created_at",
        } <= columns
        conn.execute(
            text(
                "INSERT INTO export_definitions "
                "(id, schema_id, name, fields, files_layout, created_at) "
                "VALUES (:id, :s, 'x', '[]', 'tree', '2024-01-01')"
            ),
            {"id": str(uuid.uuid4()), "s": schema_id},
        )
        conn.commit()
        assert (
            conn.execute(text("SELECT count(*) FROM export_definitions")).scalar() == 1
        )


def test_downgrade_drops_the_table(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'd.db'}")
    cfg = _config()

    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, _POST)
        conn.commit()

        command.downgrade(cfg, _PRE)
        conn.commit()

        assert "export_definitions" not in inspect(conn).get_table_names()
