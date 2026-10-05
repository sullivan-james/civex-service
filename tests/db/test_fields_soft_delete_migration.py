"""b7f2c9a14d36: fields gain deleted_at, and a name is unique among live fields.

Existing fields must survive untouched and live, the old "one name per schema"
rule must be gone (a deleted field no longer blocks its name), and the new rule
must still stop two live fields sharing one."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

_PRE = "a9d3e5f1c708"
_POST = "b7f2c9a14d36"


def _config() -> Config:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/civex/db/migrations"))
    return cfg


def _field(conn, schema_id: str, name: str, deleted_at: str | None = None) -> None:
    columns = "id, schema_id, name, dtype, required, restrictions, created_at"
    values = ":id, :s, :n, 'string', 0, '{}', '2024-01-01'"
    params = {"id": str(uuid.uuid4()), "s": schema_id, "n": name}
    if deleted_at:
        columns += ", deleted_at"
        values += ", :d"
        params["d"] = deleted_at
    conn.execute(text(f"INSERT INTO fields ({columns}) VALUES ({values})"), params)


def test_existing_fields_stay_live_and_the_name_rule_follows_deletion(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'f.db'}")
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
        _field(conn, schema_id, "title")
        conn.commit()

        command.upgrade(cfg, _POST)
        conn.commit()

        assert conn.execute(text("SELECT deleted_at FROM fields")).scalar() is None
        names = {i["name"] for i in inspect(conn).get_indexes("fields")}
        assert "ux_fields_schema_name_live" in names

        # A deleted field no longer blocks its name, nor do two deleted ones.
        _field(conn, schema_id, "title", deleted_at="2024-02-01")
        _field(conn, schema_id, "title", deleted_at="2024-03-01")
        conn.commit()

        # Two live fields with one name are still refused.
        with pytest.raises(IntegrityError):
            _field(conn, schema_id, "title")
        conn.rollback()


def test_downgrade_drops_deleted_fields_and_restores_the_old_rule(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'g.db'}")
    cfg = _config()
    schema_id = str(uuid.uuid4())

    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, _POST)
        conn.commit()
        conn.execute(
            text(
                "INSERT INTO schemas (id, name, created_at) "
                "VALUES (:id, 'thing', '2024-01-01')"
            ),
            {"id": schema_id},
        )
        _field(conn, schema_id, "title")
        _field(conn, schema_id, "title", deleted_at="2024-02-01")
        conn.commit()

        command.downgrade(cfg, _PRE)
        conn.commit()

        assert conn.execute(text("SELECT count(*) FROM fields")).scalar() == 1
        assert "deleted_at" not in {
            c["name"] for c in inspect(conn).get_columns("fields")
        }
        with pytest.raises(IntegrityError):
            _field(conn, schema_id, "title")
        conn.rollback()
