"""Sync's storage: the project's identity and cursor, who may sync, what an
authority has been sent, the conflicts to review, and the history entries sync
moves. Also the one place a *snapshot* of a schema, field, collection, view or
record is read back out of the database or written into it with its own id, which
is how a change made on one machine is reproduced on another."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import BigInteger, func, text, update
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from civex.db.models import (
    AuditBatch,
    AuditLog,
    Dataset,
    DatasetSchema,
    Field,
    Record,
    Schema,
    SyncConflict,
    SyncDevice,
    SyncMeta,
    SyncOp,
    View,
    _UTCDateTime,
)
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.domain.sync import (
    OpResult,
    SyncBatchInfo,
    SyncConflictDTO,
    SyncDeviceDTO,
    SyncEntry,
    SyncMetaDTO,
)
from civex.repositories.local.dataset_repo import _to_dtos as _dataset_dtos
from civex.repositories.local.record_repo import _to_dto as _record_dto
from civex.repositories.local.schema_repo import _field_to_dto, _schema_to_dto
from civex.repositories.local.view_repo import _to_dto as _view_dto

_MODELS: dict[str, Any] = {
    "schema": Schema,
    "field": Field,
    "dataset": Dataset,
    "view": View,
    "record": Record,
}
# A column PostgreSQL maintains itself (a trigger); never written from a snapshot.
_NOT_WRITTEN = frozenset({"search_vector"})


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class LocalSyncRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    @contextmanager
    def savepoint(self) -> Iterator[None]:
        """Everything written inside is kept or dropped together. A rule the
        database enforces (a name already taken, a parent that is not there)
        undoes it and comes out as a ValidationError saying so; the writes
        outside, earlier in the same transaction, are untouched."""
        nested = self._s.begin_nested()
        try:
            yield
            self._s.flush()
            nested.commit()
        except (IntegrityError, DataError) as e:
            # Even when the failed flush has already ended it: until it is rolled
            # back the session refuses further work.
            nested.rollback()
            raise ValidationError(_brief(e)) from e
        except BaseException:
            nested.rollback()
            raise

    # ------------------------------------------------------------------
    # The project's sync row
    # ------------------------------------------------------------------

    def _meta_row(self) -> SyncMeta:
        row = self._s.get(SyncMeta, 1)
        if row is None:  # a database that predates the migration's insert
            row = SyncMeta(id=1, project_id=uuid.uuid4(), head_seq=0, cursor=0)
            self._s.add(row)
            self._s.flush()
        return row

    def meta(self) -> SyncMetaDTO:
        row = self._meta_row()
        return SyncMetaDTO(
            project_id=row.project_id,
            head_seq=row.head_seq,
            cursor=row.cursor,
            seeded_by=row.seeded_by,
            last_synced_at=_iso(row.last_synced_at),
            last_error=row.last_error,
            last_error_at=_iso(row.last_error_at),
        )

    def set_project_id(self, project_id: uuid.UUID) -> None:
        self._meta_row().project_id = project_id
        self._s.flush()

    def set_cursor(self, seq: int) -> None:
        self._meta_row().cursor = seq
        self._s.flush()

    def set_seeded_by(self, device_id: str) -> None:
        self._meta_row().seeded_by = device_id
        self._s.flush()

    def next_hub_seq(self) -> int:
        """The next number, taken atomically: the counter is incremented in the
        database, never read and written back, so two writers can't hand out the
        same one."""
        self._meta_row()
        self._s.execute(
            update(SyncMeta)
            .where(SyncMeta.id == 1)
            .values(head_seq=SyncMeta.head_seq + 1)
        )
        self._s.expire_all()
        return self._meta_row().head_seq

    def head_seq(self) -> int:
        return self._meta_row().head_seq

    def record_outcome(self, error: str | None) -> None:
        row = self._meta_row()
        now = datetime.now(timezone.utc)
        if error is None:
            row.last_synced_at = now
            row.last_error = None
            row.last_error_at = None
        else:
            row.last_error = error[:2000]
            row.last_error_at = now
        self._s.flush()

    # ------------------------------------------------------------------
    # Devices (authority)
    # ------------------------------------------------------------------

    def add_device(self, name: str, token_hash: str) -> SyncDeviceDTO:
        row = SyncDevice(name=name, token_hash=token_hash)
        self._s.add(row)
        self._s.flush()
        return _device_dto(row)

    def list_devices(self) -> list[SyncDeviceDTO]:
        rows = self._s.query(SyncDevice).order_by(SyncDevice.created_at).all()
        return [_device_dto(r) for r in rows]

    def device_named(self, name: str) -> SyncDeviceDTO | None:
        row = self._s.query(SyncDevice).filter_by(name=name).first()
        return _device_dto(row) if row else None

    def device_by_token_hash(self, token_hash: str) -> SyncDeviceDTO | None:
        row = (
            self._s.query(SyncDevice)
            .filter_by(token_hash=token_hash)
            .filter(SyncDevice.revoked_at.is_(None))
            .first()
        )
        return _device_dto(row) if row else None

    def revoke_device(self, name: str) -> bool:
        row = self._s.query(SyncDevice).filter_by(name=name).first()
        if row is None or row.revoked_at is not None:
            return False
        row.revoked_at = datetime.now(timezone.utc)
        self._s.flush()
        return True

    def bind_device(self, id: uuid.UUID, device_id: str) -> None:
        row = self._s.get(SyncDevice, id)
        if row is not None:
            row.device_id = device_id
            self._s.flush()

    def touch_device(self, id: uuid.UUID) -> None:
        row = self._s.get(SyncDevice, id)
        if row is not None:
            row.last_seen_at = datetime.now(timezone.utc)
            self._s.flush()

    # ------------------------------------------------------------------
    # What an authority has been sent
    # ------------------------------------------------------------------

    def get_op(self, op_id: uuid.UUID) -> OpResult | None:
        row = self._s.get(SyncOp, op_id)
        if row is None:
            return None
        return OpResult(
            op_id=row.op_id,
            status=row.status,
            message=row.message,
            conflicts=list(row.conflicts or []),
            hub_seq=row.hub_seq,
        )

    def save_op(
        self,
        entry: SyncEntry,
        result: OpResult,
        device_id: str | None,
        device_name: str | None,
    ) -> None:
        self._s.add(
            SyncOp(
                op_id=entry.id,
                device_id=device_id,
                device_name=device_name,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                status=result.status,
                message=result.message,
                conflicts=result.conflicts,
                hub_seq=result.hub_seq,
            )
        )
        self._s.flush()

    def drop_op(self, op_id: uuid.UUID) -> None:
        """Forget an op that is to be tried again (it was deferred)."""
        row = self._s.get(SyncOp, op_id)
        if row is not None:
            self._s.delete(row)
            self._s.flush()

    # ------------------------------------------------------------------
    # Conflicts
    # ------------------------------------------------------------------

    def add_conflict(
        self,
        *,
        kind: str,
        entity_type: str,
        entity_id: uuid.UUID,
        field: str | None,
        yours: Any,
        theirs: Any,
        op_id: uuid.UUID | None,
        device_name: str | None,
        message: str | None,
    ) -> SyncConflictDTO:
        row = SyncConflict(
            kind=kind,
            entity_type=entity_type,
            entity_id=entity_id,
            field=field,
            yours=yours,
            theirs=theirs,
            op_id=op_id,
            device_name=device_name,
            message=message,
        )
        self._s.add(row)
        self._s.flush()
        return _conflict_dto(row)

    def has_conflict(self, op_id: uuid.UUID, field: str | None, kind: str) -> bool:
        return (
            self._s.query(SyncConflict.id)
            .filter_by(op_id=op_id, field=field, kind=kind)
            .first()
            is not None
        )

    def list_conflicts(
        self, status: str | None = "open", limit: int = 200, offset: int = 0
    ) -> list[SyncConflictDTO]:
        q = self._s.query(SyncConflict)
        if status:
            q = q.filter_by(status=status)
        rows = q.order_by(SyncConflict.created_at.desc()).offset(offset).limit(limit)
        return [_conflict_dto(r) for r in rows]

    def count_conflicts(self, status: str | None = "open") -> int:
        q = self._s.query(func.count(SyncConflict.id))
        if status:
            q = q.filter(SyncConflict.status == status)
        return q.scalar() or 0

    def get_conflict(self, id: uuid.UUID) -> SyncConflictDTO | None:
        row = self._s.get(SyncConflict, id)
        return _conflict_dto(row) if row else None

    def resolve_conflict(self, id: uuid.UUID, resolution: str) -> None:
        row = self._s.get(SyncConflict, id)
        if row is None:
            raise NotFoundError(f"Conflict '{id}' not found")
        row.status = "resolved"
        row.resolution = resolution
        row.resolved_at = datetime.now(timezone.utc)
        self._s.flush()

    # ------------------------------------------------------------------
    # Things, by snapshot
    # ------------------------------------------------------------------

    def entity_count(self) -> int:
        """How many schemas, fields, collections, views and records there are,
        deleted ones included: zero is an empty project."""
        return sum(
            self._s.query(func.count(model.id)).scalar() or 0
            for model in _MODELS.values()
        )

    def snapshot(self, kind: str, id: uuid.UUID) -> dict[str, Any] | None:
        """One thing as it is now, in the shape a history entry stores."""
        row = self._s.get(_MODELS[kind], id)
        if row is None:
            return None
        return self._dicts(kind, [row])[0]

    def snapshots_page(
        self, kind: str, offset: int, limit: int
    ) -> list[dict[str, Any]]:
        model = _MODELS[kind]
        rows = (
            self._s.query(model)
            .order_by(model.created_at, model.id)
            .offset(offset)
            .limit(limit)
            .all()
        )
        return self._dicts(kind, rows)

    def _dicts(self, kind: str, rows: list[Any]) -> list[dict[str, Any]]:
        if kind == "schema":
            return [_schema_to_dto(r).to_dict() for r in rows]
        if kind == "field":
            return [_field_to_dto(r).to_dict() for r in rows]
        if kind == "dataset":
            return [d.to_dict() for d in _dataset_dtos(self._s, rows, with_count=False)]
        if kind == "view":
            return [_view_dto(r).to_dict() for r in rows]
        return [_record_dto(r).to_dict() for r in rows]

    def apply_snapshot(self, kind: str, snap: dict[str, Any]) -> None:
        """Make the thing in `snap` exist as it describes, with its own id."""
        model = _MODELS[kind]
        columns = {
            c.name: c for c in model.__table__.columns if c.name not in _NOT_WRITTEN
        }
        values = {
            name: _coerce(columns[name], value)
            for name, value in snap.items()
            if name in columns
        }
        row = self._s.get(model, values["id"])
        if row is None:
            row = model(**values)
            self._s.add(row)
        else:
            for name, value in values.items():
                setattr(row, name, value)
        self._s.flush()
        if kind == "dataset" and "schema_ids" in snap:
            self._set_schema_links(row, snap["schema_ids"])

    def _set_schema_links(self, dataset: Dataset, schema_ids: list[str]) -> None:
        wanted = {uuid.UUID(i) for i in schema_ids}
        have = {link.schema_id for link in dataset.schema_links}
        if wanted == have:
            return
        known = {
            sid for (sid,) in self._s.query(Schema.id).filter(Schema.id.in_(wanted))
        }
        dataset.schema_links = [
            DatasetSchema(dataset_id=dataset.id, schema_id=sid) for sid in known
        ]
        self._s.flush()

    def soft_delete(self, kind: str, id: uuid.UUID, stamp: datetime) -> None:
        """Delete as a person's delete does, but stamped `stamp`: a schema or
        collection takes its live records with it, stamped the same."""
        row = self._s.get(_MODELS[kind], id)
        if row is None or getattr(row, "deleted_at", None) is not None:
            return
        row.deleted_at = stamp
        if kind == "schema":
            self._s.query(Record).filter(
                Record.schema_id == id, Record.deleted_at.is_(None)
            ).update({"deleted_at": stamp}, synchronize_session=False)
        elif kind == "dataset":
            self._s.query(Record).filter(
                Record.dataset_id == id, Record.deleted_at.is_(None)
            ).update({"deleted_at": stamp}, synchronize_session=False)
        self._s.flush()
        self._s.expire_all()

    def restore(self, kind: str, id: uuid.UUID) -> None:
        """Undo a delete as a person's restore does: a schema or collection
        brings back the records stamped with its own moment, and no others."""
        row = self._s.get(_MODELS[kind], id)
        if row is None:
            return
        stamp = getattr(row, "deleted_at", None)
        row.deleted_at = None
        if stamp is not None and kind == "schema":
            self._s.query(Record).filter(
                Record.schema_id == id, Record.deleted_at == stamp
            ).update({"deleted_at": None}, synchronize_session=False)
        elif stamp is not None and kind == "dataset":
            self._s.query(Record).filter(
                Record.dataset_id == id, Record.deleted_at == stamp
            ).update({"deleted_at": None}, synchronize_session=False)
        self._s.flush()
        self._s.expire_all()

    def delete_view(self, id: uuid.UUID) -> None:
        row = self._s.get(View, id)
        if row is not None:
            self._s.delete(row)
            self._s.flush()

    def purge(self, kind: str, id: uuid.UUID) -> None:
        """Remove a thing for good, with what goes with it, exactly as a
        person's permanent delete does (the other repositories own those
        cascades, so they are used rather than repeated)."""
        from civex.repositories.local.dataset_repo import LocalDatasetRepository
        from civex.repositories.local.record_repo import LocalRecordRepository
        from civex.repositories.local.schema_repo import LocalSchemaRepository

        if kind == "schema":
            LocalSchemaRepository(self._s).purge(id)
        elif kind == "dataset":
            LocalDatasetRepository(self._s).purge(id)
        elif kind == "record":
            LocalRecordRepository(
                self._s, is_postgres=self._s.get_bind().dialect.name == "postgresql"
            ).purge_many([id])
        elif kind == "view":
            self.delete_view(id)
        elif kind == "field":
            row = self._s.get(Field, id)
            if row is not None:
                self._s.delete(row)
        self._s.flush()
        self._s.expire_all()

    # ------------------------------------------------------------------
    # History entries, as sync moves them
    # ------------------------------------------------------------------

    def has_entry(self, id: uuid.UUID) -> bool:
        return self._s.get(AuditLog, id) is not None

    def pending_entries(self, limit: int) -> list[SyncEntry]:
        """Changes made here that the authority has not been sent, oldest first."""
        rows = (
            self._s.query(AuditLog)
            .filter(AuditLog.sync_state == "pending", AuditLog.hub_seq.is_(None))
            .order_by(AuditLog.timestamp, text("rowid"))
            .limit(limit)
            .all()
        )
        return self._entries(rows)

    def count_pending(self) -> int:
        return (
            self._s.query(func.count(AuditLog.id))
            .filter(AuditLog.sync_state == "pending", AuditLog.hub_seq.is_(None))
            .scalar()
            or 0
        )

    def dirty_entities(self) -> set[tuple[str, uuid.UUID]]:
        """Things with a change here still waiting to be sent: what a pull must
        not overwrite."""
        rows = (
            self._s.query(AuditLog.entity_type, AuditLog.entity_id)
            .filter(AuditLog.sync_state == "pending", AuditLog.hub_seq.is_(None))
            .distinct()
        )
        return {(t, i) for t, i in rows}

    def mark_sent(self, results: list[OpResult]) -> None:
        for result in results:
            row = self._s.get(AuditLog, result.op_id)
            if row is None:
                continue
            if result.status == "rejected":
                row.sync_state = "rejected"
            elif result.status != "deferred":
                row.sync_state = "synced"
                if result.hub_seq is not None:
                    row.hub_seq = result.hub_seq
        self._s.flush()

    def mark_seq(self, entry_id: uuid.UUID, seq: int) -> None:
        """The authority has numbered a change made here: it is theirs now too."""
        row = self._s.get(AuditLog, entry_id)
        if row is not None:
            row.hub_seq = seq
            if row.sync_state == "pending":
                row.sync_state = "synced"
            self._s.flush()

    def latest_hlc(self) -> str | None:
        return self._s.query(func.max(AuditLog.hlc)).scalar()

    def mark_all_synced(self) -> None:
        """Everything so far is covered by a snapshot the authority holds."""
        self._s.execute(
            update(AuditLog)
            .where(AuditLog.sync_state == "pending")
            .values(sync_state="synced")
            .execution_options(synchronize_session=False)
        )
        self._s.expire_all()

    def insert_entry(
        self, entry: SyncEntry, *, hub_seq: int | None, state: str = "synced"
    ) -> None:
        """Keep an entry made elsewhere in this project's history, as it was."""
        batch_id = None
        if entry.batch is not None:
            batch_id = entry.batch.id
            if self._s.get(AuditBatch, batch_id) is None:
                self._s.add(
                    AuditBatch(
                        id=batch_id,
                        kind=entry.batch.kind,
                        label=entry.batch.label,
                        ref=entry.batch.ref,
                        created_at=_parse(entry.batch.created_at),
                    )
                )
                self._s.flush()
        self._s.add(
            AuditLog(
                id=entry.id,
                action=entry.action,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                old_data=entry.old_data,
                new_data=entry.new_data,
                timestamp=_parse(entry.timestamp),
                batch_id=batch_id,
                actor=entry.actor,
                device_id=uuid.UUID(entry.device_id) if entry.device_id else None,
                hlc=entry.hlc,
                hub_seq=hub_seq,
                sync_state=state,
            )
        )
        self._s.flush()

    def sequence_local_entries(self) -> int:
        """Authority: number the changes made on this instance itself, in the
        order they were made, so they join the feed. Returns how many."""
        rows = (
            self._s.query(AuditLog)
            .filter(AuditLog.hub_seq.is_(None), AuditLog.sync_state == "pending")
            .order_by(AuditLog.timestamp, text("rowid"))
            .all()
        )
        for row in rows:
            row.hub_seq = self.next_hub_seq()
            row.sync_state = "synced"
        self._s.flush()
        return len(rows)

    def entries_after(self, seq: int, limit: int) -> tuple[list[SyncEntry], bool]:
        """Numbered entries past `seq`, in order, and whether more follow."""
        rows = (
            self._s.query(AuditLog)
            .filter(AuditLog.hub_seq > seq)
            .order_by(AuditLog.hub_seq)
            .limit(limit + 1)
            .all()
        )
        more = len(rows) > limit
        return self._entries(rows[:limit]), more

    def _entries(self, rows: list[AuditLog]) -> list[SyncEntry]:
        batch_ids = {r.batch_id for r in rows if r.batch_id}
        batches = (
            {
                b.id: SyncBatchInfo(
                    id=b.id,
                    kind=b.kind,
                    label=b.label,
                    ref=b.ref,
                    created_at=_iso(b.created_at) or "",
                )
                for b in self._s.query(AuditBatch).filter(AuditBatch.id.in_(batch_ids))
            }
            if batch_ids
            else {}
        )
        ids = [r.id for r in rows]
        superseded = (
            {
                op_id
                for (op_id,) in self._s.query(SyncOp.op_id).filter(
                    SyncOp.op_id.in_(ids), SyncOp.status.in_(("merged", "conflict"))
                )
            }
            if ids
            else set()
        )
        return [
            SyncEntry(
                id=r.id,
                action=r.action,
                entity_type=r.entity_type,
                entity_id=r.entity_id,
                old_data=r.old_data,
                new_data=r.new_data,
                timestamp=_iso(r.timestamp) or "",
                actor=r.actor,
                device_id=str(r.device_id) if r.device_id else None,
                hlc=r.hlc,
                batch=batches.get(r.batch_id) if r.batch_id else None,
                hub_seq=r.hub_seq,
                superseded=r.id in superseded,
            )
            for r in rows
        ]


def _coerce(column: Any, value: Any) -> Any:
    """A snapshot's JSON value in the type its column holds."""
    if value is None:
        return None
    kind = column.type
    if isinstance(kind, _UTCDateTime) and isinstance(value, str):
        return _parse(value)
    if getattr(kind, "python_type", None) is uuid.UUID and isinstance(value, str):
        return uuid.UUID(value)
    if isinstance(kind, BigInteger) and isinstance(value, str):
        return int(value)
    return value


def _brief(error: Exception) -> str:
    """The first line of what the database said, without the SQL."""
    text_ = str(getattr(error, "orig", error)).strip().splitlines()
    return text_[0] if text_ else "A rule of the database was broken"


def _device_dto(row: SyncDevice) -> SyncDeviceDTO:
    return SyncDeviceDTO(
        id=row.id,
        name=row.name,
        device_id=row.device_id,
        created_at=_iso(row.created_at) or "",
        last_seen_at=_iso(row.last_seen_at),
        revoked_at=_iso(row.revoked_at),
    )


def _conflict_dto(row: SyncConflict) -> SyncConflictDTO:
    return SyncConflictDTO(
        id=row.id,
        kind=row.kind,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        field=row.field,
        yours=row.yours,
        theirs=row.theirs,
        op_id=row.op_id,
        device_name=row.device_name,
        message=row.message,
        status=row.status,
        created_at=_iso(row.created_at) or "",
        resolved_at=_iso(row.resolved_at),
        resolution=row.resolution,
    )
