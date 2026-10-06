"""PostgreSQL-only behaviour of the scaling work: the migration and partial
indexes apply, file_references are maintained by ORM events and cascade on
delete, the stored_objects upsert is idempotent, and SQL-side JSONB sorting
puts numbers in numeric order with nulls last.

Requires CIVEX_TEST_POSTGRES_URL (see test_search_vector_trigger.py); skipped
otherwise. SQLite equivalents of each of these are covered elsewhere.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from civex.config import StoreConfig, VolumeConfig
from civex.db.migrate import ensure_schema_current
from civex.db.models import Dataset, FileReference, Record, Schema, StoredObject
from civex.domain.filters import SortKey
from civex.domain.query import ResolvedQuery
from civex.repositories.local.file_ref_repo import LocalFileReferenceRepository
from civex.repositories.local.file_store import VolumeAwareFileObjectStore
from civex.repositories.local.record_repo import LocalRecordRepository

_PG_URL = os.environ.get("CIVEX_TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not _PG_URL,
    reason="set CIVEX_TEST_POSTGRES_URL to a scratch PostgreSQL DB to run this test",
)


@pytest.fixture()
def session():
    engine = create_engine(_PG_URL)
    ensure_schema_current(engine)
    with Session(engine) as s:
        yield s
        s.rollback()
    engine.dispose()


def _seed(session: Session) -> tuple[Dataset, Schema]:
    ds = Dataset(name=f"ds-{uuid.uuid4().hex[:8]}")
    sch = Schema(name=f"sch_{uuid.uuid4().hex[:8]}")
    session.add_all([ds, sch])
    session.flush()
    return ds, sch


def test_indexes_exist(session: Session) -> None:
    names = {
        i["name"]
        for t in ("records", "workflow_jobs", "audit_log", "step_executions")
        for i in inspect(session.get_bind()).get_indexes(t)
    }
    assert {
        "ix_records_live_dataset_created",
        "ix_records_parent",
        "ix_workflow_jobs_status_created",
        "ix_audit_log_unsynced",  # (ix_audit_log_staged went in a9d3e5f1c708)
        "ix_audit_log_hub_seq",
    } <= names
    partial = session.execute(
        text(
            "SELECT indexdef FROM pg_indexes WHERE indexname='ix_records_live_dataset_created'"
        )
    ).scalar_one()
    assert "deleted_at IS NULL" in partial


def test_file_references_follow_record_writes_and_cascade(session: Session) -> None:
    ds, sch = _seed(session)
    sha1, sha2 = "1" * 64, "2" * 64
    rec = Record(dataset_id=ds.id, schema_id=sch.id, data={"f": {"sha256": sha1}})
    session.add(rec)
    session.flush()
    refs = LocalFileReferenceRepository(session)
    assert refs.referenced_subset([sha1, sha2]) == {sha1}

    rec.data = {"f": [{"sha256": sha2}]}
    session.flush()
    assert refs.referenced_subset([sha1, sha2]) == {sha2}

    session.delete(rec)
    session.flush()  # ON DELETE CASCADE removes the reference rows
    assert refs.referenced_subset([sha1, sha2]) == set()
    assert not session.execute(
        select(FileReference).where(FileReference.sha256.in_([sha1, sha2]))
    ).first()


def test_store_inventory_upsert_is_idempotent_and_sums(
    session: Session, tmp_path: Path
) -> None:
    (tmp_path / "v").mkdir()  # an absolute volume path must already exist
    vc = VolumeConfig(name="v", path=str(tmp_path / "v"))
    store = VolumeAwareFileObjectStore(
        StoreConfig(volumes={"v": vc}, volume_queue=["v"]), tmp_path, session=session
    )
    a = store.put(b"x" * 10, "a")
    store._register("v", a.sha256, 10)  # duplicate registration: no error
    store.put(b"y" * 5, "b")
    assert store._civex_used("v") == 15
    session.execute(text("DELETE FROM stored_objects"))
    assert store.reconcile_inventory() == {"added_or_updated": 2, "removed": 0}
    assert store._civex_used("v") == 15


def test_jsonb_sort_is_numeric_with_nulls_last(session: Session) -> None:
    ds, sch = _seed(session)
    key = str(uuid.uuid4())
    for value in (9, 100, None, 10, 1):
        data = {} if value is None else {key: value}
        session.add(Record(dataset_id=ds.id, schema_id=sch.id, data=data))
    session.flush()
    repo = LocalRecordRepository(session, is_postgres=True)

    def scores(desc: bool, offset=0, limit=10):
        rows = repo.list_filtered(
            ResolvedQuery(
                dataset_id=ds.id,
                schema_id=sch.id,
                sort=[SortKey(field_id=key, numeric=True, descending=desc)],
            ),
            offset,
            limit,
        )
        return [r.data.get(key) for r in rows]

    assert scores(False) == [1, 9, 10, 100, None]
    assert scores(True) == [100, 10, 9, 1, None]
    assert scores(True, offset=2, limit=2) == [9, 1]
