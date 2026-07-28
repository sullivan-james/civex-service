"""CIVEX-170: workflow_jobs.step_executions (a JSON list) normalizes into a
child `step_executions` table. This exercises the migration itself -- that
existing JSON rows backfill correctly and the old column is gone -- rather
than the ORM read/write path, which test_step_executions.py already covers.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

_PRE_REVISION = "336bf9b1d235"  # head just before this migration
_POST_REVISION = "23bbe21d0f1e"  # this migration


def _config() -> Config:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/civex/db/migrations"))
    return cfg


def test_step_executions_json_backfills_into_child_table(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'backfill.db'}")
    cfg = _config()

    job_id = str(uuid.uuid4())
    record_id = str(uuid.uuid4())
    dataset_id = str(uuid.uuid4())
    schema_id = str(uuid.uuid4())

    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, _PRE_REVISION)
        conn.commit()

        conn.execute(
            text(
                "INSERT INTO datasets (id, name, created_at) VALUES (:id, 'ds', '2024-01-01')"
            ),
            {"id": dataset_id},
        )
        conn.execute(
            text(
                "INSERT INTO schemas (id, name, created_at) VALUES (:id, 'doc', '2024-01-01')"
            ),
            {"id": schema_id},
        )
        conn.execute(
            text(
                "INSERT INTO records (id, dataset_id, schema_id, data, created_at, updated_at) "
                "VALUES (:id, :dataset_id, :schema_id, '{}', '2024-01-01', '2024-01-01')"
            ),
            {"id": record_id, "dataset_id": dataset_id, "schema_id": schema_id},
        )
        conn.execute(
            text(
                "INSERT INTO workflow_jobs "
                "(id, workflow_name, record_id, schema_name, trigger, status, step_executions, created_at) "
                "VALUES (:id, 'wf', :record_id, 'doc', 'manual', 'completed', :steps, '2024-01-01')"
            ),
            {
                "id": job_id,
                "record_id": record_id,
                "steps": (
                    '[{"step_id": "read", "plugin": "civex.get_field", "status": "success", '
                    '"inputs": {}, "outputs": {"value": "x"}, "duration_seconds": 0.01, '
                    '"error": null, "depends_on": []},'
                    '{"step_id": "write", "plugin": "civex.save_field", "status": "failed", '
                    '"inputs": {"value": "x"}, "outputs": null, "duration_seconds": 0.02, '
                    '"error": "boom", "depends_on": ["read"]}]'
                ),
            },
        )
        conn.commit()

        command.upgrade(cfg, _POST_REVISION)
        conn.commit()

        columns = {c["name"] for c in inspect(conn).get_columns("workflow_jobs")}
        assert "step_executions" not in columns
        assert "step_executions" in inspect(conn).get_table_names()

        # step_executions.job_id round-trips through the Uuid column type
        # (canonical hex, no dashes) while workflow_jobs.id above was
        # inserted as a raw literal string via text() -- so it won't
        # string-match here even though the FK is correct. Only one job
        # exists in this DB, so ordering by position alone is enough.
        rows = conn.execute(
            text("SELECT position, step_id, plugin, status, error FROM step_executions ORDER BY position")
        ).fetchall()

    assert [tuple(r) for r in rows] == [
        (0, "read", "civex.get_field", "success", None),
        (1, "write", "civex.save_field", "failed", "boom"),
    ]


def test_downgrade_restores_the_json_column(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'downgrade.db'}")
    cfg = _config()

    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, _POST_REVISION)
        conn.commit()

        command.downgrade(cfg, _PRE_REVISION)
        conn.commit()

        columns = {c["name"] for c in inspect(conn).get_columns("workflow_jobs")}
        assert "step_executions" in columns
        assert "step_executions" not in inspect(conn).get_table_names()
