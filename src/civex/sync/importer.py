"""
Applies a SyncBundle to a local database session (last-write-wins for records).

Schemas, fields, and datasets are upserted by UUID.
Records use LWW: incoming row replaces local only when its updated_at is newer.
Deleted record IDs are removed from the local DB.
Objects are never transferred here — only their sha256 hashes in object_refs.
"""
from __future__ import annotations

import uuid
from datetime import timezone

from sqlalchemy.orm import Session

from civex.db.models import AuditLog, Commit, Dataset, Field, Record, Schema
from civex.domain.dtos import (
    AuditLogDTO,
    CommitDTO,
    DatasetDTO,
    FieldDTO,
    RecordDTO,
    SchemaDTO,
)
from civex.sync.bundle import SyncBundle


def apply_bundle(session: Session, bundle: SyncBundle) -> None:
    _upsert_schemas(session, bundle.schemas)
    _upsert_fields(session, bundle.fields)
    _upsert_datasets(session, bundle.datasets)
    _upsert_records(session, bundle.records)
    _delete_records(session, bundle.deleted_record_ids)
    _upsert_commits(session, bundle.commits)
    _upsert_audit_log(session, bundle.audit_log)
    session.flush()


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------

def _upsert_schemas(session: Session, rows: list[dict]) -> None:
    for d in rows:
        dto = SchemaDTO.from_dict(d)
        existing = session.get(Schema, dto.id)
        if existing is None:
            session.add(Schema(
                id=dto.id,
                name=dto.name,
                description=dto.description,
                parent_id=dto.parent_id,
                created_at=dto.created_at,
            ))
        else:
            existing.name = dto.name
            existing.description = dto.description
            existing.parent_id = dto.parent_id


def _upsert_fields(session: Session, rows: list[dict]) -> None:
    for d in rows:
        dto = FieldDTO.from_dict(d)
        existing = session.get(Field, dto.id)
        if existing is None:
            session.add(Field(
                id=dto.id,
                schema_id=dto.schema_id,
                name=dto.name,
                dtype=dto.dtype,
                required=dto.required,
                restrictions=dto.restrictions,
                created_at=dto.created_at,
            ))
        else:
            existing.name = dto.name
            existing.dtype = dto.dtype
            existing.required = dto.required
            existing.restrictions = dto.restrictions


def _upsert_datasets(session: Session, rows: list[dict]) -> None:
    for d in rows:
        dto = DatasetDTO.from_dict(d)
        existing = session.get(Dataset, dto.id)
        if existing is None:
            session.add(Dataset(
                id=dto.id,
                name=dto.name,
                description=dto.description,
                created_at=dto.created_at,
            ))
        else:
            existing.name = dto.name
            existing.description = dto.description


def _upsert_records(session: Session, rows: list[dict]) -> None:
    # Sort: null parent_record_id first so FK-enforcing DBs don't choke.
    sorted_rows = sorted(rows, key=lambda r: (r.get("parent_record_id") is not None, r.get("created_at") or ""))
    for d in sorted_rows:
        dto = RecordDTO.from_dict(d)
        existing = session.get(Record, dto.id)
        if existing is None:
            session.add(Record(
                id=dto.id,
                dataset_id=dto.dataset_id,
                schema_id=dto.schema_id,
                parent_record_id=dto.parent_record_id,
                data=dto.data,
                created_at=dto.created_at,
                updated_at=dto.updated_at,
            ))
        else:
            local_updated = existing.updated_at
            if local_updated and local_updated.tzinfo is None:
                local_updated = local_updated.replace(tzinfo=timezone.utc)
            incoming_updated = dto.updated_at
            if incoming_updated and (local_updated is None or incoming_updated > local_updated):
                existing.data = dto.data
                existing.updated_at = incoming_updated


def _delete_records(session: Session, record_ids: list[str]) -> None:
    for rid in record_ids:
        row = session.get(Record, uuid.UUID(rid))
        if row:
            session.delete(row)


def _upsert_commits(session: Session, rows: list[dict]) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    for d in rows:
        dto = CommitDTO.from_dict(d)
        existing = session.get(Commit, dto.id)
        if existing is None:
            session.add(Commit(
                id=dto.id,
                seq=dto.seq,
                message=dto.message,
                created_at=dto.created_at,
                record_count=dto.record_count,
                schema_count=dto.schema_count,
                dataset_count=dto.dataset_count,
                pushed_at=now,
            ))
        else:
            if not existing.pushed_at:
                existing.pushed_at = now


def _upsert_audit_log(session: Session, rows: list[dict]) -> None:
    from datetime import datetime, timezone
    # now = datetime.now(timezone.utc)
    for d in rows:
        dto = AuditLogDTO.from_dict(d)
        if session.get(AuditLog, dto.id) is None:
            session.add(AuditLog(
                id=dto.id,
                commit_id=dto.commit_id,
                action=dto.action,
                entity_type=dto.entity_type,
                entity_id=dto.entity_id,
                old_data=dto.old_data,
                new_data=dto.new_data,
                timestamp=dto.timestamp,
            ))
