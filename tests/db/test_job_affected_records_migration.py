"""d4a9b7e52c10 backfills job_affected_records from existing jobs'
affected_records JSON."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

_PRE = "c3f8a1d27e64"
_POST = "d4a9b7e52c10"


def _config() -> Config:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/civex/db/migrations"))
    return cfg


def test_backfill_links_each_job_to_the_valid_records_it_touched(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    cfg = _config()
    job_a, job_b, job_c = (str(uuid.uuid4()) for _ in range(3))
    r1, r2 = str(uuid.uuid4()), str(uuid.uuid4())

    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, _PRE)
        conn.commit()
        ds, sch = str(uuid.uuid4()), str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO datasets (id, name, created_at) VALUES (:i,'ds','2024-01-01')"
            ),
            {"i": ds},
        )
        conn.execute(
            text(
                "INSERT INTO schemas (id, name, created_at) VALUES (:i,'doc','2024-01-01')"
            ),
            {"i": sch},
        )
        rec = str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO records (id, dataset_id, schema_id, data, created_at, updated_at) "
                "VALUES (:i,:d,:s,'{}','2024-01-01','2024-01-01')"
            ),
            {"i": rec, "d": ds, "s": sch},
        )
        for jid, affected in [
            (
                job_a,
                [
                    {"record_id": r1, "schema_name": "doc"},
                    {"record_id": r1, "schema_name": "doc"},  # repeated
                    {"record_id": r2},
                    {"record_id": "not-a-uuid"},  # skipped
                ],
            ),
            (job_b, None),
            (job_c, []),
        ]:
            conn.execute(
                text(
                    "INSERT INTO workflow_jobs (id, workflow_name, record_id, trigger, status, "
                    "depth, created_at, affected_records) "
                    "VALUES (:i,'w',:rec,'manual','completed',0,'2024-01-01',:a)"
                ),
                {
                    "i": jid,
                    "rec": rec,
                    "a": None if affected is None else json.dumps(affected),
                },
            )
        conn.commit()

        command.upgrade(cfg, _POST)
        conn.commit()
        rows = conn.execute(
            text("SELECT job_id, record_id FROM job_affected_records")
        ).fetchall()

    assert {(r[0], r[1]) for r in rows} == {
        (uuid.UUID(job_a).hex, uuid.UUID(r1).hex),
        (uuid.UUID(job_a).hex, uuid.UUID(r2).hex),
    }
