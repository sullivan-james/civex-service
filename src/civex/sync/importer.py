"""
Applies a SyncBundle to a local database session (last-write-wins for records).

Schemas, fields, and datasets are upserted by UUID.
Records use LWW: incoming row replaces local only when its updated_at is newer.
Deleted record IDs are removed from the local DB.
Objects are never transferred here — only their sha256 hashes in object_refs.
"""

from __future__ import annotations

import uuid
from typing import Any
from datetime import timezone

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


def apply_bundle(session: Session, bundle: SyncBundle) -> None:
    _upsert_schemas(session, bundle.schemas)
    _upsert_fields(session, bundle.fields)
    _upsert_datasets(session, bundle.datasets)
    _upsert_records(session, bundle.records)
    _delete_records(session, bundle.deleted_record_ids)
    _upsert_commits(session, bundle.commits, bundle.audit_log)
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
            # Fall back to name lookup — handles re-created schemas with new UUIDs.
            existing = session.query(Schema).filter_by(name=dto.name).first()
        if existing is None:
            session.add(
                Schema(
                    id=dto.id,
                    name=dto.name,
                    description=dto.description,
                    parent_id=dto.parent_id,
                    created_at=dto.created_at,
                )
            )
        else:
            existing.description = dto.description
            existing.parent_id = dto.parent_id


def _upsert_fields(session: Session, rows: list[dict]) -> None:
    for d in rows:
        dto = FieldDTO.from_dict(d)
        existing = session.get(Field, dto.id)
        if existing is None:
            # Fall back to (schema_id, name) lookup — handles re-created fields with new UUIDs.
            existing = (
                session.query(Field)
                .filter_by(schema_id=dto.schema_id, name=dto.name)
                .first()
            )
        if existing is None:
            session.add(
                Field(
                    id=dto.id,
                    schema_id=dto.schema_id,
                    name=dto.name,
                    dtype=dto.dtype,
                    required=dto.required,
                    restrictions=dto.restrictions,
                    created_at=dto.created_at,
                )
            )
        else:
            existing.dtype = dto.dtype
            existing.required = dto.required
            existing.restrictions = dto.restrictions


# Ids per IN (...) when looking rows up in bulk -- well under SQLite's
# bound-variable limit.
_CHUNK = 500


def _existing(session: Session, model: Any, ids: list[uuid.UUID]) -> dict:
    """The `model` rows among `ids`, by id -- a lookup per chunk rather than a
    `session.get` (and a SELECT) per row of a bundle."""
    found: dict = {}
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start : start + _CHUNK]
        for row in session.query(model).filter(model.id.in_(chunk)):
            found[row.id] = row
    return found


def _upsert_datasets(session: Session, rows: list[dict]) -> None:
    for d in rows:
        dto = DatasetDTO.from_dict(d)
        existing = session.get(Dataset, dto.id)
        if existing is None:
            existing = session.query(Dataset).filter_by(name=dto.name).first()
        if existing is None:
            session.add(
                Dataset(
                    id=dto.id,
                    name=dto.name,
                    description=dto.description,
                    timezone=dto.timezone,
                    scope=dto.scope,
                    created_at=dto.created_at,
                )
            )
            session.flush()
            existing = session.get(Dataset, dto.id)
        else:
            existing.name = dto.name
            existing.description = dto.description
            # A bundle from a peer that predates timezones has no key at all;
            # don't let that read as "cleared" and wipe a locally set zone.
            if "timezone" in d:
                existing.timezone = dto.timezone
            if "scope" in d:
                existing.scope = dto.scope
        # Same for the schema list: only a peer that sends one replaces ours.
        if "schemas" in d and existing is not None:
            schema_ids = [
                sid
                for (sid,) in session.query(Schema.id).filter(
                    Schema.name.in_(dto.schemas)
                )
            ]
            existing.schema_links = [
                DatasetSchema(dataset_id=existing.id, schema_id=sid)
                for sid in schema_ids
            ]


def _upsert_records(session: Session, rows: list[dict]) -> None:
    # Sort: null parent_record_id first so FK-enforcing DBs don't choke.
    sorted_rows = sorted(
        rows,
        key=lambda r: (
            r.get("parent_record_id") is not None,
            r.get("created_at") or "",
        ),
    )
    dtos = [RecordDTO.from_dict(d) for d in sorted_rows]
    present = _existing(session, Record, [dto.id for dto in dtos])
    for dto in dtos:
        existing = present.get(dto.id)
        if existing is None:
            session.add(
                Record(
                    id=dto.id,
                    dataset_id=dto.dataset_id,
                    schema_id=dto.schema_id,
                    parent_record_id=dto.parent_record_id,
                    data=dto.data,
                    created_at=dto.created_at,
                    updated_at=dto.updated_at,
                )
            )
        else:
            local_updated = existing.updated_at
            if local_updated and local_updated.tzinfo is None:
                local_updated = local_updated.replace(tzinfo=timezone.utc)
            incoming_updated = dto.updated_at
            if incoming_updated and (
                local_updated is None or incoming_updated > local_updated
            ):
                existing.data = dto.data
                existing.updated_at = incoming_updated


def _delete_records(session: Session, record_ids: list[str]) -> None:
    for row in _existing(session, Record, [uuid.UUID(r) for r in record_ids]).values():
        session.delete(row)


def _upsert_commits(
    session: Session, rows: list[dict], audit_log_rows: list[dict]
) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    counts = _commit_counts(audit_log_rows)
    for d in rows:
        dto = CommitDTO.from_dict(d)
        existing = session.get(Commit, dto.id)
        if existing is None:
            record_count, schema_count, dataset_count = counts.get(
                str(dto.id), (0, 0, 0)
            )
            session.add(
                Commit(
                    id=dto.id,
                    seq=dto.seq,
                    message=dto.message,
                    created_at=dto.created_at,
                    record_count=record_count,
                    schema_count=schema_count,
                    dataset_count=dataset_count,
                    pushed_at=now,
                )
            )
        else:
            if not existing.pushed_at:
                existing.pushed_at = now


def _commit_counts(audit_log_rows: list[dict]) -> dict[str, tuple[int, int, int]]:
    """Each commit's (record, schema, dataset) counts, recomputed from the
    entries it actually shipped with rather than trusting the counts a peer put
    on the wire (CIVEX-173) -- a commit and all of its audit_log entries always
    travel together in the same bundle (see exporter.export_bundle), so this is
    a complete recount, not a partial one. One pass over the entries, not one
    per commit."""
    tally: dict[str, list[int]] = {}
    for e in audit_log_rows:
        counts = tally.setdefault(str(e.get("commit_id")), [0, 0, 0])
        if e["entity_type"] == "record":
            counts[0] += 1
        elif e["entity_type"] in ("schema", "field"):
            counts[1] += 1
        elif e["entity_type"] == "dataset":
            counts[2] += 1
    return {k: (v[0], v[1], v[2]) for k, v in tally.items()}


def _upsert_audit_log(session: Session, rows: list[dict]) -> None:
    dtos = [AuditLogDTO.from_dict(d) for d in rows]
    present = _existing(session, AuditLog, [dto.id for dto in dtos])
    for dto in dtos:
        if dto.id not in present:
            session.add(
                AuditLog(
                    id=dto.id,
                    commit_id=dto.commit_id,
                    action=dto.action,
                    entity_type=dto.entity_type,
                    entity_id=dto.entity_id,
                    old_data=dto.old_data,
                    new_data=dto.new_data,
                    timestamp=dto.timestamp,
                )
            )
