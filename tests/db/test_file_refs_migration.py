"""e5b81c3d7a04 backfills file_references from existing records/jobs and
job_affected_schemas from affected_records JSON, then a real upgrade leaves
the new indexes in place."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

_PRE = "a1c7e5f93b2d"
_POST = "e5b81c3d7a04"


def _config() -> Config:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/civex/db/migrations"))
    return cfg


def test_backfill_and_indexes(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    cfg = _config()
    ds, sch, rec, job = (str(uuid.uuid4()) for _ in range(4))
    sha_a, sha_b, sha_dup = "a" * 64, "b" * 64, "c" * 64

    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, _PRE)
        conn.commit()
        conn.execute(text("INSERT INTO datasets (id, name, created_at) VALUES (:i,'ds','2024-01-01')"), {"i": ds})
        conn.execute(text("INSERT INTO schemas (id, name, created_at) VALUES (:i,'doc','2024-01-01')"), {"i": sch})
        data = {
            "f1": {"sha256": sha_a, "filename": "a", "size": 1},
            "f2": [
                {"sha256": sha_b, "filename": "b", "size": 1},
                {"sha256": sha_dup, "filename": "c", "size": 1},
                {"sha256": sha_dup, "filename": "c2", "size": 1},  # same blob twice
            ],
            "junk": {"sha256": "not-a-digest"},
        }
        conn.execute(
            text(
                "INSERT INTO records (id, dataset_id, schema_id, data, created_at, updated_at)"
                " VALUES (:i,:d,:s,:data,'2024-01-01','2024-01-01')"
            ),
            {"i": rec, "d": ds, "s": sch, "data": json.dumps(data)},
        )
        conn.execute(
            text(
                "INSERT INTO workflow_jobs (id, workflow_name, record_id, trigger, status,"
                " input_data, affected_records, depth, created_at)"
                " VALUES (:i,'wf',:r,'manual','completed',:inp,:aff,0,'2024-01-01')"
            ),
            {
                "i": job,
                "r": rec,
                "inp": json.dumps({"files": [{"sha256": sha_a}]}),
                "aff": json.dumps([{"record_id": rec, "schema_name": "doc", "action": "created"}]),
            },
        )
        conn.commit()

        command.upgrade(cfg, _POST)
        conn.commit()

        rows = conn.execute(text("SELECT sha256, record_id, job_id FROM file_references")).all()
        by_owner = {(r[0], r[1] is not None) for r in rows}
        assert by_owner == {
            (sha_a, True),
            (sha_b, True),
            (sha_dup, True),  # deduped per owner
            (sha_a, False),  # the job input
        }
        links = conn.execute(text("SELECT job_id, schema_id FROM job_affected_schemas")).all()
        assert [(str(uuid.UUID(str(a))), str(uuid.UUID(str(b)))) for a, b in links] == [
            (str(uuid.UUID(job)), str(uuid.UUID(sch)))
        ]

        idx = {i["name"] for t in ("records", "workflow_jobs", "audit_log", "step_executions")
               for i in inspect(conn).get_indexes(t)}
        assert {
            "ix_records_parent",
            "ix_records_live_dataset_created",
            "ix_workflow_jobs_status_created",
            "ix_audit_log_entity",
            "ix_audit_log_staged",
            "ix_step_executions_plugin_status",
        } <= idx

        command.downgrade(cfg, _PRE)
        assert "file_references" not in inspect(conn).get_table_names()
