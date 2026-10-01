"""c3f8a1d27e64 backfills record_references from existing records' data."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

_PRE = "9b4d2f6e8a13"
_POST = "c3f8a1d27e64"


def _config() -> Config:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/civex/db/migrations"))
    return cfg


def test_backfill_reads_single_and_list_references(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    cfg = _config()
    ds, sch = str(uuid.uuid4()), str(uuid.uuid4())
    one, two, referrer, plain = (str(uuid.uuid4()) for _ in range(4))
    ref_field, list_field, text_field = (str(uuid.uuid4()) for _ in range(3))

    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, _PRE)
        conn.commit()
        conn.execute(text("INSERT INTO datasets (id, name, created_at) VALUES (:i,'ds','2024-01-01')"), {"i": ds})
        conn.execute(text("INSERT INTO schemas (id, name, created_at) VALUES (:i,'doc','2024-01-01')"), {"i": sch})
        for rid, data in [
            (one, {}),
            (two, {}),
            (
                referrer,
                {
                    ref_field: one,
                    list_field: [one, two],
                    text_field: "just words",
                    "legacy_name_key": one,
                },
            ),
            (plain, {text_field: "no refs"}),
        ]:
            conn.execute(
                text(
                    "INSERT INTO records (id, dataset_id, schema_id, data, created_at, updated_at) "
                    "VALUES (:i,:d,:s,:data,'2024-01-01','2024-01-01')"
                ),
                {"i": rid, "d": ds, "s": sch, "data": json.dumps(data)},
            )
        conn.commit()

        command.upgrade(cfg, _POST)
        conn.commit()
        rows = conn.execute(
            text("SELECT record_id, field_id, target_id FROM record_references")
        ).fetchall()

    norm = lambda u: uuid.UUID(u).hex  # noqa: E731 - sqlite stores hex
    assert {(r[0], r[1], r[2]) for r in rows} == {
        (norm(referrer), norm(ref_field), norm(one)),
        (norm(referrer), norm(list_field), norm(one)),
        (norm(referrer), norm(list_field), norm(two)),
    }
