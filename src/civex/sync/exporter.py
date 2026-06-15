"""
Reads the local DB and produces a SyncBundle.

Schemas, fields, and datasets are always exported in full (they're small).
Records are exported incrementally: only rows with updated_at >= since are included.
Object sha256s referenced by exported records are collected into object_refs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from civex.db.models import AuditLog, Commit, Dataset, Field, Record, Schema
from civex.sync.bundle import SyncBundle


def export_bundle(session: Session, since: datetime | None) -> SyncBundle:
    now = datetime.now(timezone.utc)

    schemas = [_schema_row(r) for r in session.query(Schema).order_by(Schema.created_at).all()]
    fields = [_field_row(r) for r in session.query(Field).order_by(Field.created_at).all()]
    datasets = [_dataset_row(r) for r in session.query(Dataset).order_by(Dataset.created_at).all()]

    q = session.query(Record).order_by(Record.created_at)
    if since is not None:
        # SQLite stores datetimes as naive UTC strings. Strip tzinfo so the
        # SQL comparison works correctly (a tz-aware value gets serialised with
        # "+00:00" and string ordering in SQLite breaks against naive values).
        since_cmp = since.astimezone(timezone.utc).replace(tzinfo=None) if since.tzinfo else since
        q = q.filter(Record.updated_at >= since_cmp)
    records = [_record_row(r) for r in q.all()]

    unpushed_commits = (
        session.query(Commit)
        .filter(Commit.pushed_at.is_(None))
        .order_by(Commit.created_at)
        .all()
    )
    commit_ids = [c.id for c in unpushed_commits]
    audit_entries = (
        session.query(AuditLog)
        .filter(AuditLog.commit_id.in_(commit_ids))
        .order_by(AuditLog.timestamp)
        .all()
    ) if commit_ids else []

    return SyncBundle(
        version=1,
        exported_at=now.isoformat(),
        schemas=schemas,
        fields=fields,
        datasets=datasets,
        records=records,
        object_refs=_collect_object_refs(records),
        commits=[_commit_row(c) for c in unpushed_commits],
        audit_log=[_audit_row(e) for e in audit_entries],
    )


# ---------------------------------------------------------------------------
# Row serialisers
# ---------------------------------------------------------------------------

def _schema_row(r: Schema) -> dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "description": r.description,
        "parent_id": str(r.parent_id) if r.parent_id else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _field_row(r: Field) -> dict:
    return {
        "id": str(r.id),
        "schema_id": str(r.schema_id),
        "name": r.name,
        "dtype": r.dtype,
        "required": r.required,
        "restrictions": r.restrictions or {},
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _dataset_row(r: Dataset) -> dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "description": r.description,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _record_row(r: Record) -> dict:
    return {
        "id": str(r.id),
        "dataset_id": str(r.dataset_id),
        "schema_id": str(r.schema_id),
        "parent_record_id": str(r.parent_record_id) if r.parent_record_id else None,
        "data": r.data or {},
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _commit_row(r: Commit) -> dict:
    return {
        "id": str(r.id),
        "message": r.message,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "record_count": r.record_count,
        "schema_count": r.schema_count,
        "dataset_count": r.dataset_count,
        "pushed_at": r.pushed_at.isoformat() if r.pushed_at else None,
    }


def _audit_row(r: AuditLog) -> dict:
    return {
        "id": str(r.id),
        "commit_id": str(r.commit_id) if r.commit_id else None,
        "action": r.action,
        "entity_type": r.entity_type,
        "entity_id": str(r.entity_id),
        "old_data": r.old_data,
        "new_data": r.new_data,
        "timestamp": r.timestamp.isoformat() if r.timestamp else None,
    }


def _collect_object_refs(records: list[dict]) -> list[str]:
    refs: set[str] = set()
    for rec in records:
        for v in (rec.get("data") or {}).values():
            if isinstance(v, dict) and "sha256" in v:
                refs.add(v["sha256"])
    return sorted(refs)
