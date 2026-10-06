"""e8b4f2c6a917: history gains room for delta entries and a write order. Nothing
already stored is rewritten (a large history would make opening the project
hang); entries written afterwards are numbered by the database."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

_PRE = "d6c2a8f41b07"
_POST = "e8b4f2c6a917"

_INSERT = text(
    "INSERT INTO audit_log (id, action, entity_type, entity_id, old_data, new_data, "
    "timestamp) VALUES (:i, 'update', 'record', :e, :o, :n, :t)"
)


def _config() -> Config:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/civex/db/migrations"))
    return cfg


def _entry(conn, when: str) -> str:
    entry_id = uuid.uuid4().hex
    conn.execute(
        _INSERT,
        {
            "i": entry_id,
            "e": uuid.uuid4().hex,
            "o": json.dumps({"data": {"f": 1}}),
            "n": json.dumps({"data": {"f": 2}}),
            "t": when,
        },
    )
    return entry_id


def test_existing_history_is_left_as_it_is_and_new_entries_are_numbered(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'h.db'}")
    cfg = _config()
    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, _PRE)
        conn.commit()
        old = _entry(conn, "2026-01-01 00:00:00")
        conn.commit()

        command.upgrade(cfg, _POST)
        conn.commit()

        cols = {c["name"] for c in inspect(conn).get_columns("audit_log")}
        assert {"delta", "format", "local_seq"} <= cols
        meta = {c["name"] for c in inspect(conn).get_columns("sync_meta")}
        assert {"feed_floor", "history_from"} <= meta

        row = conn.execute(
            text(
                "SELECT format, delta, local_seq, old_data, new_data FROM audit_log "
                "WHERE id = :i"
            ),
            {"i": old},
        ).one()
        assert row[0] == 1 and row[1] is None and row[2] is None
        assert json.loads(row[3]) == {"data": {"f": 1}}
        assert json.loads(row[4]) == {"data": {"f": 2}}

        # Written later but stamped earlier (a clock stepped back): numbered in
        # the order written all the same.
        first = _entry(conn, "2026-06-01 00:00:00")
        second = _entry(conn, "2025-01-01 00:00:00")
        conn.commit()
        seq = dict(
            conn.execute(
                text("SELECT id, local_seq FROM audit_log WHERE id IN (:a, :b)"),
                {"a": first, "b": second},
            ).all()
        )
        assert seq[first] is not None and seq[second] > seq[first]
        assert (
            conn.execute(text("SELECT feed_floor FROM sync_meta")).scalar_one() == 0
        )

        command.downgrade(cfg, _PRE)
        conn.commit()
        cols = {c["name"] for c in inspect(conn).get_columns("audit_log")}
        assert not ({"delta", "format", "local_seq"} & cols)
        assert (
            conn.execute(
                text("SELECT count(*) FROM sqlite_master WHERE type = 'trigger'")
            ).scalar_one()
            == 0
        )
        assert conn.execute(text("SELECT count(*) FROM audit_log")).scalar_one() == 3
