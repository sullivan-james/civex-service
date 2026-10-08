"""e6a2c8f4d1b7: the library keeps every version (and back)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

_PRE = "b2d6f8a3c517"
_POST = "e6a2c8f4d1b7"


def _config() -> Config:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/civex/db/migrations"))
    return cfg


def _add(conn, name: str, version: int) -> None:
    conn.execute(
        text(
            "INSERT INTO library_items (id, kind, name, content, sha256, size, "
            "version, needs, triggers, published_at) VALUES (:id, 'workflow', :n, "
            "'steps: []', :sha, 9, :v, '[]', '[]', '2026-10-08')"
        ),
        {"id": uuid.uuid4().hex, "n": name, "sha": str(version) * 64, "v": version},
    )


def test_a_library_from_before_keeps_its_items_and_takes_versions(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'l.db'}")
    cfg = _config()
    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, _PRE)
        _add(conn, "tidy", 3)
        conn.commit()
        with pytest.raises(IntegrityError):  # one row per item, before
            _add(conn, "tidy", 4)
        conn.rollback()

        command.upgrade(cfg, _POST)
        conn.commit()
        row = conn.execute(
            text("SELECT version, pins, contract FROM library_items")
        ).one()
        assert (row.version, row.pins, row.contract) == (3, "{}", None)
        _add(conn, "tidy", 4)  # another version of the same item
        conn.commit()
        with pytest.raises(IntegrityError):  # but each version once
            _add(conn, "tidy", 4)
        conn.rollback()

        command.downgrade(cfg, _PRE)
        conn.commit()
        assert conn.execute(
            text("SELECT version FROM library_items")
        ).scalars().all() == [4]
        assert "pins" not in {
            c["name"] for c in inspect(conn).get_columns("library_items")
        }
