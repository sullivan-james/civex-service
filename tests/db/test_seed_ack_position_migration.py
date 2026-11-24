"""d7a3c9e5f2b8: a database already stamped at b8d4f1a7c3e6 (seed_acks without
head_seq) gains the column and the audit_log.hlc index; acks it held keep."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

_PRE = "b8d4f1a7c3e6"
_POST = "d7a3c9e5f2b8"


def _config() -> Config:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/civex/db/migrations"))
    return cfg


def test_a_database_stamped_before_the_position_gains_it(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'c.db'}")
    cfg = _config()
    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, _PRE)
        conn.commit()
        assert "head_seq" not in {
            c["name"] for c in inspect(conn).get_columns("seed_acks")
        }
        conn.execute(text("INSERT INTO seed_acks (entry_id) VALUES ('kept')"))
        conn.commit()

        command.upgrade(cfg, _POST)
        conn.commit()
        insp = inspect(conn)
        assert "head_seq" in {c["name"] for c in insp.get_columns("seed_acks")}
        assert "ix_audit_log_hlc" in {i["name"] for i in insp.get_indexes("audit_log")}
        assert conn.execute(text("SELECT entry_id, head_seq FROM seed_acks")).all() == [
            ("kept", 0)
        ]

        command.downgrade(cfg, _PRE)
        conn.commit()
        assert "head_seq" not in {
            c["name"] for c in inspect(conn).get_columns("seed_acks")
        }
