"""
Applies a SyncBundle to a local database session (last-write-wins).

Schemas, fields, and datasets are upserted by UUID (insert if new; update if changed).
Records use LWW: incoming row replaces local only when its updated_at is newer.
Objects are never transferred here — only their sha256 hashes in object_refs.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from civex.db.models import AuditLog, Commit, Dataset, Field, Record, Schema
from civex.sync.bundle import SyncBundle


def apply_bundle(session: Session, bundle: SyncBundle) -> None:
    _upsert_schemas(session, bundle.schemas)
    _upsert_fields(session, bundle.fields)
    _upsert_datasets(session, bundle.datasets)
    _upsert_records(session, bundle.records)
    _upsert_commits(session, bundle.commits)
    _upsert_audit_log(session, bundle.audit_log)
    session.flush()


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------

def _upsert_schemas(session: Session, rows: list[dict]) -> None:
    for d in rows:
        uid = uuid.UUID(d["id"])
        existing = session.get(Schema, uid)
        if existing is None:
            session.add(Schema(
                id=uid,
                name=d["name"],
                description=d.get("description"),
                parent_id=uuid.UUID(d["parent_id"]) if d.get("parent_id") else None,
                created_at=_parse_dt(d.get("created_at")),
            ))
        else:
            existing.name = d["name"]
            existing.description = d.get("description")
            existing.parent_id = uuid.UUID(d["parent_id"]) if d.get("parent_id") else None


def _upsert_fields(session: Session, rows: list[dict]) -> None:
    for d in rows:
        uid = uuid.UUID(d["id"])
        existing = session.get(Field, uid)
        if existing is None:
            session.add(Field(
                id=uid,
                schema_id=uuid.UUID(d["schema_id"]),
                name=d["name"],
                dtype=d["dtype"],
                required=d.get("required", False),
                restrictions=d.get("restrictions") or {},
                created_at=_parse_dt(d.get("created_at")),
            ))
        else:
            existing.name = d["name"]
            existing.dtype = d["dtype"]
            existing.required = d.get("required", False)
            existing.restrictions = d.get("restrictions") or {}


def _upsert_datasets(session: Session, rows: list[dict]) -> None:
    for d in rows:
        uid = uuid.UUID(d["id"])
        existing = session.get(Dataset, uid)
        if existing is None:
            session.add(Dataset(
                id=uid,
                name=d["name"],
                description=d.get("description"),
                created_at=_parse_dt(d.get("created_at")),
            ))
        else:
            existing.name = d["name"]
            existing.description = d.get("description")


def _upsert_records(session: Session, rows: list[dict]) -> None:
    # Sort: null parent_record_id first so FK-enforcing DBs don't choke.
    sorted_rows = sorted(rows, key=lambda r: (r.get("parent_record_id") is not None, r.get("created_at") or ""))
    for d in sorted_rows:
        uid = uuid.UUID(d["id"])
        incoming_updated = _parse_dt(d.get("updated_at"))
        existing = session.get(Record, uid)
        if existing is None:
            session.add(Record(
                id=uid,
                dataset_id=uuid.UUID(d["dataset_id"]),
                schema_id=uuid.UUID(d["schema_id"]),
                parent_record_id=uuid.UUID(d["parent_record_id"]) if d.get("parent_record_id") else None,
                data=d.get("data") or {},
                created_at=_parse_dt(d.get("created_at")),
                updated_at=incoming_updated,
            ))
        else:
            local_updated = existing.updated_at
            if local_updated and local_updated.tzinfo is None:
                local_updated = local_updated.replace(tzinfo=timezone.utc)
            if incoming_updated and (local_updated is None or incoming_updated > local_updated):
                existing.data = d.get("data") or {}
                existing.updated_at = incoming_updated


def _upsert_commits(session: Session, rows: list[dict]) -> None:
    now = datetime.now(timezone.utc)
    for d in rows:
        uid = uuid.UUID(d["id"])
        existing = session.get(Commit, uid)
        if existing is None:
            session.add(Commit(
                id=uid,
                message=d.get("message"),
                created_at=_parse_dt(d.get("created_at")) or now,
                record_count=d.get("record_count", 0),
                schema_count=d.get("schema_count", 0),
                dataset_count=d.get("dataset_count", 0),
                pushed_at=now,
            ))
        else:
            if not existing.pushed_at:
                existing.pushed_at = now


def _upsert_audit_log(session: Session, rows: list[dict]) -> None:
    for d in rows:
        uid = uuid.UUID(d["id"])
        if session.get(AuditLog, uid) is None:
            session.add(AuditLog(
                id=uid,
                commit_id=uuid.UUID(d["commit_id"]) if d.get("commit_id") else None,
                action=d["action"],
                entity_type=d["entity_type"],
                entity_id=uuid.UUID(d["entity_id"]),
                old_data=d.get("old_data"),
                new_data=d.get("new_data"),
                timestamp=_parse_dt(d.get("timestamp")) or datetime.now(timezone.utc),
            ))


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
