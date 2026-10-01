"""
Reads the local DB and produces a SyncBundle.

Schemas, fields, and datasets are always exported in full (they are small and
schema/field updates are not always individually audited).

Records are exported commit-driven: only records that appear in audit log entries
belonging to commits with seq > since_seq are included.  Deleted records are sent
as IDs only (the row is gone) in deleted_record_ids.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from civex.db.models import (
    AuditLog,
    Commit,
    Dataset,
    DatasetSchema,
    Field,
    Record,
    Schema,
)
from civex.domain.dtos import (
    AuditLogDTO,
    CommitDTO,
    DatasetDTO,
    FieldDTO,
    RecordDTO,
    SchemaDTO,
)
from civex.sync.bundle import SyncBundle


def export_bundle(session: Session, since_seq: int = 0) -> SyncBundle:
    now = datetime.now(timezone.utc)

    schemas = [
        SchemaDTO(
            id=r.id,
            name=r.name,
            description=r.description,
            parent_id=r.parent_id,
            created_at=r.created_at or now,
        ).to_dict()
        for r in session.query(Schema)
        .filter(Schema.deleted_at.is_(None))
        .order_by(Schema.created_at)
        .all()
    ]
    fields = [
        FieldDTO(
            id=r.id,
            schema_id=r.schema_id,
            name=r.name,
            dtype=r.dtype,
            required=r.required,
            restrictions=r.restrictions or {},
            created_at=r.created_at or now,
        ).to_dict()
        for r in session.query(Field).order_by(Field.created_at).all()
    ]
    datasets = [
        DatasetDTO(
            id=r.id,
            name=r.name,
            description=r.description,
            record_count=0,
            created_at=r.created_at or now,
            timezone=r.timezone,
            scope=r.scope,
            schemas=sorted(
                name
                for (name,) in session.query(Schema.name)
                .join(DatasetSchema, DatasetSchema.schema_id == Schema.id)
                .filter(DatasetSchema.dataset_id == r.id)
            ),
        ).to_dict()
        for r in session.query(Dataset)
        .filter(Dataset.deleted_at.is_(None))
        .order_by(Dataset.created_at)
        .all()
    ]

    # Commits not yet seen by the receiver.
    new_commits = (
        session.query(Commit).filter(Commit.seq > since_seq).order_by(Commit.seq).all()
    )
    commit_ids = [c.id for c in new_commits]
    last_seq = new_commits[-1].seq if new_commits else since_seq
    to_seq = last_seq if last_seq is not None else since_seq

    # Audit entries that belong to those commits.
    audit_entries = (
        session.query(AuditLog)
        .filter(AuditLog.commit_id.in_(commit_ids))
        .order_by(AuditLog.timestamp)
        .all()
        if commit_ids
        else []
    )

    # Record audit entries that deleted a record, in the bundle order.
    deleted_record_ids = [
        str(e.entity_id)
        for e in audit_entries
        if e.entity_type == "record" and e.action == "delete"
    ]

    # The records those commits created or updated, selected by a subquery on
    # the audit entries rather than an IN (...) of every id: a big push would
    # otherwise exceed SQLite's bound-variable limit and fail outright.
    live_in_commits = (
        select(AuditLog.entity_id)
        .where(
            AuditLog.commit_id.in_(commit_ids),
            AuditLog.entity_type == "record",
            AuditLog.action != "delete",
        )
        .scalar_subquery()
        if commit_ids
        else None
    )
    records = [
        RecordDTO(
            id=r.id,
            dataset_id=r.dataset_id,
            schema_id=r.schema_id,
            schema_name="",
            parent_record_id=r.parent_record_id,
            data=cast(dict[str, Any], _sanitize_nan(r.data or {})),
            created_at=r.created_at or now,
            updated_at=r.updated_at or now,
        ).to_dict()
        for r in (
            session.query(Record)
            .filter(Record.id.in_(live_in_commits), Record.deleted_at.is_(None))
            .all()
            if live_in_commits is not None
            else []
        )
    ]

    return SyncBundle(
        version=1,
        exported_at=now.isoformat(),
        from_seq=since_seq,
        to_seq=to_seq,
        schemas=schemas,
        fields=fields,
        datasets=datasets,
        records=records,
        deleted_record_ids=deleted_record_ids,
        object_refs=_collect_object_refs(records),
        commits=[
            CommitDTO(
                id=c.id,
                seq=c.seq,
                message=c.message,
                created_at=c.created_at or now,
                record_count=c.record_count,
                schema_count=c.schema_count,
                dataset_count=c.dataset_count,
                pushed_at=c.pushed_at,
            ).to_dict()
            for c in new_commits
        ],
        audit_log=[
            AuditLogDTO(
                id=e.id,
                commit_id=e.commit_id,
                action=e.action,
                entity_type=e.entity_type,
                entity_id=e.entity_id,
                old_data=cast("dict[str, Any] | None", _sanitize_nan(e.old_data)),
                new_data=cast("dict[str, Any] | None", _sanitize_nan(e.new_data)),
                timestamp=e.timestamp or now,
            ).to_dict()
            for e in audit_entries
        ],
    )


def _sanitize_nan(obj: object) -> object:
    """Replace float NaN/Inf with None so the value is valid JSONB on PostgreSQL."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_nan(v) for v in obj]
    return obj


def _collect_object_refs(records: list[dict]) -> list[str]:
    refs: set[str] = set()
    for rec in records:
        for v in (rec.get("data") or {}).values():
            if isinstance(v, dict) and "sha256" in v:
                refs.add(v["sha256"])
    return sorted(refs)
