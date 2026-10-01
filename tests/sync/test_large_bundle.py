"""A push of more records than one IN (...) can hold must still export, and
importing it must not read the receiver one row at a time."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from civex.db.models import AuditLog, Base, Commit, Dataset, Record, Schema
from civex.sync.exporter import export_bundle
from civex.sync.importer import apply_bundle

# SQLite's default bound-variable limit is 32,766.
N = 33_500


def _seeded(tmp_path: Path, name: str) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / name}")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_export_bundles_more_records_than_sqlite_can_bind(tmp_path: Path) -> None:
    s = _seeded(tmp_path, "src.db")
    now = datetime.now(timezone.utc)
    ds, sch = Dataset(name="ds"), Schema(name="doc")
    s.add_all([ds, sch])
    s.flush()
    commit = Commit(seq=1, message="push", record_count=N, schema_count=0, dataset_count=0)
    s.add(commit)
    s.flush()
    ids = [uuid.uuid4() for _ in range(N)]
    s.bulk_insert_mappings(
        Record,
        [
            {
                "id": i,
                "dataset_id": ds.id,
                "schema_id": sch.id,
                "data": {},
                "created_at": now,
                "updated_at": now,
            }
            for i in ids
        ],
    )
    s.bulk_insert_mappings(
        AuditLog,
        [
            {
                "id": uuid.uuid4(),
                "commit_id": commit.id,
                "action": "create",
                "entity_type": "record",
                "entity_id": i,
                "timestamp": now,
            }
            for i in ids
        ],
    )
    s.commit()

    bundle = export_bundle(s, since_seq=0)

    assert len(bundle.records) == N
    assert {r["id"] for r in bundle.records} == {str(i) for i in ids}

    # Importing it reads existing rows a chunk at a time, not one per record.
    dest = _seeded(tmp_path, "dest.db")
    selects: list[str] = []
    event.listen(
        dest.get_bind(),
        "before_cursor_execute",
        lambda c, cur, st, *a: selects.append(st) if st.startswith("SELECT") else None,
    )
    apply_bundle(dest, bundle)
    dest.commit()

    assert dest.query(Record).count() == N
    assert len(selects) < N / 10
