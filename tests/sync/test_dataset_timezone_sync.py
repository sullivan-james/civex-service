"""Dataset timezones ride along in sync bundles, and a bundle from a peer that
predates them must not wipe a locally set zone."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civex.db.models import Base, Dataset
from civex.domain.dtos import DatasetDTO
from civex.sync.bundle import SyncBundle
from civex.sync.importer import apply_bundle


def _session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'sync.db'}")
    Base.metadata.create_all(engine)
    return Session(engine)


def _bundle(datasets: list[dict]) -> SyncBundle:
    return SyncBundle(
        version=1,
        exported_at=datetime.now(timezone.utc).isoformat(),
        from_seq=0,
        to_seq=1,
        schemas=[],
        fields=[],
        datasets=datasets,
        records=[],
        commits=[],
        audit_log=[],
    )


def _row(dataset_id: uuid.UUID, **extra: object) -> dict:
    return {
        "id": str(dataset_id),
        "name": "study",
        "description": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "deleted_at": None,
        **extra,
    }


def test_dto_roundtrip_and_missing_key() -> None:
    row = _row(uuid.uuid4(), timezone="America/Chicago")
    assert DatasetDTO.from_dict(row).timezone == "America/Chicago"
    assert DatasetDTO.from_dict(row).to_dict()["timezone"] == "America/Chicago"
    legacy = _row(uuid.uuid4())
    assert "timezone" not in legacy
    assert DatasetDTO.from_dict(legacy).timezone is None


def test_import_creates_dataset_with_timezone(tmp_path: Path) -> None:
    s = _session(tmp_path)
    did = uuid.uuid4()
    apply_bundle(s, _bundle([_row(did, timezone="Asia/Kolkata")]))
    s.commit()
    assert s.get(Dataset, did).timezone == "Asia/Kolkata"


def test_import_updates_timezone(tmp_path: Path) -> None:
    s = _session(tmp_path)
    did = uuid.uuid4()
    apply_bundle(s, _bundle([_row(did, timezone="Asia/Kolkata")]))
    apply_bundle(s, _bundle([_row(did, timezone="America/Chicago")]))
    s.commit()
    assert s.get(Dataset, did).timezone == "America/Chicago"


def test_bundle_without_the_key_does_not_clear_a_local_zone(tmp_path: Path) -> None:
    s = _session(tmp_path)
    did = uuid.uuid4()
    apply_bundle(s, _bundle([_row(did, timezone="America/Chicago")]))
    apply_bundle(s, _bundle([_row(did)]))  # old peer: no "timezone" key
    s.commit()
    assert s.get(Dataset, did).timezone == "America/Chicago"


def test_bundle_with_explicit_null_clears_it(tmp_path: Path) -> None:
    s = _session(tmp_path)
    did = uuid.uuid4()
    apply_bundle(s, _bundle([_row(did, timezone="America/Chicago")]))
    apply_bundle(s, _bundle([_row(did, timezone=None)]))
    s.commit()
    assert s.get(Dataset, did).timezone is None
