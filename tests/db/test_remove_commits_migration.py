"""a9d3e5f1c708 drops the old sync's `commits` and gives audit_log its sync columns.

What matters is that nothing a customer has is lost: every audit entry survives
(snapshots intact) whether or not it had been put in a commit, and each gains
`sync_state = 'pending'`.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

_PRE_REVISION = "f2a6c8d1e093"
_POST_REVISION = "a9d3e5f1c708"


def _config() -> Config:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/civex/db/migrations"))
    return cfg


def _seed(conn, committed: bool) -> str:
    entry_id = str(uuid.uuid4())
    commit_id = str(uuid.uuid4())
    if committed:
        conn.execute(
            text(
                "INSERT INTO commits (id, seq, message, created_at, record_count, "
                "schema_count, dataset_count) VALUES (:id, 1, 'push', '2024-01-01', "
                "1, 0, 0)"
            ),
            {"id": commit_id},
        )
    conn.execute(
        text(
            "INSERT INTO audit_log (id, commit_id, action, entity_type, entity_id, "
            "old_data, new_data, timestamp) VALUES (:id, :commit_id, 'create', "
            "'record', :entity, NULL, '{\"name\": \"kept\"}', '2024-01-01')"
        ),
        {
            "id": entry_id,
            "commit_id": commit_id if committed else None,
            "entity": str(uuid.uuid4()),
        },
    )
    conn.commit()
    return entry_id


def test_entries_survive_with_or_without_a_commit(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'a.db'}")
    cfg = _config()

    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, _PRE_REVISION)
        conn.commit()
        committed = _seed(conn, committed=True)
        staged = _seed(conn, committed=False)

        command.upgrade(cfg, _POST_REVISION)
        conn.commit()

        insp = inspect(conn)
        columns = {c["name"] for c in insp.get_columns("audit_log")}
        assert "commit_id" not in columns
        assert {"actor", "device_id", "hlc", "hub_seq", "sync_state"} <= columns
        assert "commits" not in insp.get_table_names()
        names = {i["name"] for i in insp.get_indexes("audit_log")}
        assert "ix_audit_log_commit" not in names
        assert "ix_audit_log_staged" not in names

        rows = conn.execute(
            text("SELECT id, new_data, sync_state, actor, hub_seq FROM audit_log")
        ).fetchall()

    assert {r[0].replace("-", "") for r in rows} == {
        committed.replace("-", ""),
        staged.replace("-", ""),
    }
    for _id, new_data, sync_state, actor, hub_seq in rows:
        assert "kept" in str(new_data)
        assert sync_state == "pending"
        assert actor is None and hub_seq is None


def test_downgrade_restores_an_empty_commits_table(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'b.db'}")
    cfg = _config()

    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, _POST_REVISION)
        conn.commit()
        command.downgrade(cfg, _PRE_REVISION)
        conn.commit()

        insp = inspect(conn)
        assert "commits" in insp.get_table_names()
        columns = {c["name"] for c in insp.get_columns("audit_log")}
        assert "commit_id" in columns and "sync_state" not in columns
