"""f4b8d2a6c139: an export's one table becomes a list of tables, and back."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

_PRE = "e1a7c5b8f204"
_POST = "f4b8d2a6c139"


def _config() -> Config:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/civex/db/migrations"))
    return cfg


def _add(conn, schema_id: str, name: str, table: dict | None) -> None:
    conn.execute(
        text(
            'INSERT INTO export_definitions (id, schema_id, name, fields, files_layout, '
            'include_files, "table", created_at) '
            "VALUES (:id, :s, :n, '[]', 'tree', 1, :t, '2024-01-01')"
        ),
        {
            "id": uuid.uuid4().hex,
            "s": schema_id,
            "n": name,
            "t": json.dumps(table) if table is not None else None,
        },
    )


def test_a_saved_table_becomes_the_one_entry_of_the_list(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'e.db'}")
    cfg = _config()
    schema_id = uuid.uuid4().hex
    spec = {"format": "xlsx", "columns": ["a", "b"]}

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
        _add(conn, schema_id, "with table", spec)
        _add(conn, schema_id, "without", None)
        conn.commit()

        command.upgrade(cfg, _POST)
        conn.commit()

        columns = {c["name"] for c in inspect(conn).get_columns("export_definitions")}
        assert "tables" in columns and "table" not in columns
        rows = dict(
            conn.execute(text("SELECT name, tables FROM export_definitions")).all()
        )
        assert json.loads(rows["with table"]) == [spec]
        assert json.loads(rows["without"]) == []

        command.downgrade(cfg, _PRE)
        conn.commit()
        back = dict(
            conn.execute(text('SELECT name, "table" FROM export_definitions')).all()
        )
        assert json.loads(back["with table"]) == spec
        assert back["without"] is None
