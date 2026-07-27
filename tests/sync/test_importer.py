"""apply_bundle must not trust a peer's commit aggregate counts (CIVEX-173):
a buggy or hostile peer can ship a commit whose record_count/schema_count/
dataset_count don't match the audit_log entries it also sent. Counts are
recomputed locally from the entries actually received.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civex.db.models import Base, Commit
from civex.sync.bundle import SyncBundle
from civex.sync.importer import apply_bundle


def _session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'sync.db'}")
    Base.metadata.create_all(engine)
    return Session(engine)


def _audit_row(commit_id: str, entity_type: str, now: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "commit_id": commit_id,
        "action": "create",
        "entity_type": entity_type,
        "entity_id": str(uuid.uuid4()),
        "old_data": None,
        "new_data": {},
        "timestamp": now,
    }


def _bundle(commits: list[dict], audit_log: list[dict]) -> SyncBundle:
    return SyncBundle(
        version=1,
        exported_at=datetime.now(timezone.utc).isoformat(),
        from_seq=0,
        to_seq=1,
        schemas=[],
        fields=[],
        datasets=[],
        records=[],
        commits=commits,
        audit_log=audit_log,
    )


def test_commit_counts_are_recomputed_from_received_entries_not_the_wire_value(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path)
    commit_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Wire says 12 records / 5 schemas / 5 datasets, but only 2 record entries
    # and 1 dataset entry actually shipped with this commit.
    commit_dict = {
        "id": commit_id,
        "seq": 1,
        "message": "m",
        "created_at": now,
        "record_count": 12,
        "schema_count": 5,
        "dataset_count": 5,
        "pushed_at": None,
    }
    audit_rows = [
        _audit_row(commit_id, "record", now),
        _audit_row(commit_id, "record", now),
        _audit_row(commit_id, "dataset", now),
    ]

    apply_bundle(session, _bundle([commit_dict], audit_rows))
    session.commit()

    row = session.get(Commit, uuid.UUID(commit_id))
    assert row is not None
    assert row.record_count == 2
    assert row.schema_count == 0
    assert row.dataset_count == 1


def test_field_entries_count_toward_schema_count(tmp_path: Path) -> None:
    session = _session(tmp_path)
    commit_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    commit_dict = {
        "id": commit_id,
        "seq": 1,
        "message": None,
        "created_at": now,
        "record_count": 0,
        "schema_count": 0,
        "dataset_count": 0,
        "pushed_at": None,
    }
    audit_rows = [
        _audit_row(commit_id, "schema", now),
        _audit_row(commit_id, "field", now),
        _audit_row(commit_id, "field", now),
    ]

    apply_bundle(session, _bundle([commit_dict], audit_rows))
    session.commit()

    row = session.get(Commit, uuid.UUID(commit_id))
    assert row is not None
    assert row.schema_count == 3


def test_entries_belonging_to_a_different_commit_are_not_counted(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path)
    commit_id = str(uuid.uuid4())
    other_commit_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    commit_dict = {
        "id": commit_id,
        "seq": 1,
        "message": None,
        "created_at": now,
        "record_count": 0,
        "schema_count": 0,
        "dataset_count": 0,
        "pushed_at": None,
    }
    audit_rows = [
        _audit_row(commit_id, "record", now),
        _audit_row(other_commit_id, "record", now),
        _audit_row(other_commit_id, "record", now),
    ]

    apply_bundle(session, _bundle([commit_dict], audit_rows))
    session.commit()

    row = session.get(Commit, uuid.UUID(commit_id))
    assert row is not None
    assert row.record_count == 1
