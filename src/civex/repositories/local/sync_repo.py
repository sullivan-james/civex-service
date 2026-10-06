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

from sqlalchemy import BigInteger, and_, func, or_, select, update
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from civex.db.models import (
    AuditBatch,
    AuditLog,
    Dataset,
    DatasetSchema,
    Field,
    FileReference,
    Record,
    RecordReference,
    Schema,
    SyncConflict,
    SyncDevice,
    SyncMeta,
    SyncOp,
    View,
    _UTCDateTime,
)
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.domain.audit_diff import entry_snapshots
from civex.domain.merge import value_at
from civex.domain.sync import (
    OpResult,
    SyncBatchInfo,
    SyncConflictDTO,
    SyncDeviceDTO,
    SyncEntry,
    SyncMetaDTO,
    parse_snapshot_cursor,
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


# The order changes were made in here: the number the database gave each entry
# as it was written (`AuditLog.local_seq`), not its time, since a clock can step
# back and send a child before its parent (refused for good). Entries from
# before the number existed have none and come first, by time.
_WRITE_ORDER = (
    func.coalesce(AuditLog.local_seq, 0),
    AuditLog.timestamp,
    AuditLog.id,
)


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
            history_from=row.history_from,
            feed_floor=row.feed_floor or 0,
        )

    def set_history_from(self, seq: int | None) -> None:
        self._meta_row().history_from = seq
        self._s.flush()

    def history_fetched_upto(self, upto: int) -> int:
        """The last number up to `upto` whose entry is held here: where
        fetching the history from before joining carries on from."""
        return (
            self._s.query(func.max(AuditLog.hub_seq))
            .filter(AuditLog.hub_seq <= upto)
            .scalar()
            or 0
        )

    def referenced_shas(self, after: str, limit: int) -> list[str]:
        """Hashes of the files live records cite, in hash order, `limit` of them
        after `after`. The catalog is kept up to date as records are written, so
        what a device still owes its authority is worked out from it each time
        rather than remembered."""
        rows = self._s.execute(
            select(FileReference.sha256)
            .where(FileReference.record_id.is_not(None), FileReference.sha256 > after)
            .distinct()
            .order_by(FileReference.sha256)
            .limit(limit)
        )
        return [sha for (sha,) in rows]

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

    def lock_feed(self) -> None:
        """Hold the feed's counter until this transaction ends, so whoever
        takes it next waits: a row lock on PostgreSQL, the write lock on
        SQLite (a write that changes nothing still takes it)."""
        self._meta_row()
        self._s.execute(
            update(SyncMeta).where(SyncMeta.id == 1).values(head_seq=SyncMeta.head_seq)
        )

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
        base: Any = None,
        theirs_actor: str | None = None,
        theirs_at: str | None = None,
    ) -> SyncConflictDTO:
        row = SyncConflict(
            kind=kind,
            entity_type=entity_type,
            entity_id=entity_id,
            field=field,
            yours=yours,
            theirs=theirs,
            base=base,
            theirs_actor=theirs_actor,
            theirs_at=_parse(theirs_at),
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
        self,
        status: str | None = "open",
        limit: int = 200,
        offset: int = 0,
        entity_id: uuid.UUID | None = None,
    ) -> list[SyncConflictDTO]:
        q = self._s.query(SyncConflict)
        if status:
            q = q.filter_by(status=status)
        if entity_id:
            q = q.filter(SyncConflict.entity_id == entity_id)
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

    def last_change(
        self, kind: str, entity_id: uuid.UUID, path: str | None
    ) -> tuple[str | None, str | None]:
        """Who last changed a value of a thing, and when (actor, ISO time): the
        latest numbered entry whose before and after differ at `path`, or the
        latest entry of any kind when `path` is None. What a conflict says about
        the value that stayed."""
        rows = (
            self._s.query(AuditLog)
            .filter(
                AuditLog.entity_type == kind,
                AuditLog.entity_id == entity_id,
                # The state the authority settles on is written under this name:
                # it is nobody's edit.
                or_(AuditLog.actor.is_(None), AuditLog.actor != "sync"),
            )
            .order_by(*(c.desc() for c in _WRITE_ORDER))
            .limit(50)
            .all()
        )
        for row in rows:
            old, new = entry_snapshots(row.old_data, row.new_data, row.delta)
            if path is None or value_at(old, path) != value_at(new, path):
                return row.actor, _iso(row.timestamp)
        return None, None

    def resolve_conflict(self, id: uuid.UUID, resolution: str) -> None:
        row = self._s.get(SyncConflict, id)
        if row is None:
            raise NotFoundError(f"Conflict '{id}' not found")
        row.status = "resolved"
        row.resolution = resolution
        row.resolved_at = datetime.now(timezone.utc)
        self._s.flush()

    def conflicts_of_ops(self, op_ids: list[uuid.UUID]) -> list[SyncConflictDTO]:
        """Every conflict, open or settled, that came from one of these changes."""
        if not op_ids:
            return []
        rows = (
            self._s.query(SyncConflict)
            .filter(SyncConflict.op_id.in_(op_ids))
            .order_by(SyncConflict.created_at)
        )
        return [_conflict_dto(r) for r in rows]

    def find_open_conflicts(
        self,
        *,
        ids: list[uuid.UUID] | None = None,
        kind: str | None = None,
        entity_id: uuid.UUID | None = None,
    ) -> list[SyncConflictDTO]:
        """Every open conflict matching all that is given, oldest first and with no
        page limit (a bulk settle must reach them all, not the first screenful)."""
        q = self._s.query(SyncConflict).filter_by(status="open")
        if ids is not None:
            q = q.filter(SyncConflict.id.in_(ids))
        if kind:
            q = q.filter(SyncConflict.kind == kind)
        if entity_id:
            q = q.filter(SyncConflict.entity_id == entity_id)
        return [_conflict_dto(r) for r in q.order_by(SyncConflict.created_at)]

    def resolve_conflicts(self, ids: list[uuid.UUID], resolution: str) -> int:
        """Mark open conflicts settled, in one statement. Returns how many were."""
        if not ids:
            return 0
        n = (
            self._s.query(SyncConflict)
            .filter(SyncConflict.id.in_(ids), SyncConflict.status == "open")
            .update(
                {
                    "status": "resolved",
                    "resolution": resolution,
                    "resolved_at": datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
        )
        self._s.flush()
        return n

    def reopen_conflicts(self, ids: list[uuid.UUID], resolution: str) -> int:
        """Open conflicts that were settled with `resolution` again. Returns how
        many were."""
        if not ids:
            return 0
        n = (
            self._s.query(SyncConflict)
            .filter(
                SyncConflict.id.in_(ids),
                SyncConflict.status == "resolved",
                SyncConflict.resolution == resolution,
            )
            .update(
                {"status": "open", "resolution": None, "resolved_at": None},
                synchronize_session=False,
            )
        )
        self._s.flush()
        return n

    # ------------------------------------------------------------------
    # Things, by snapshot
    # ------------------------------------------------------------------

    def entity_count(self) -> int:
        """How many schemas, fields, collections, views and records there are,
        deleted ones included: zero is an empty project."""
        return sum(self.entity_counts().values())

    def entity_counts(self) -> dict[str, int]:
        """How many of each kind there are, deleted ones included."""
        return {
            kind: self._s.query(func.count(model.id)).scalar() or 0
            for kind, model in _MODELS.items()
        }

    def snapshot(self, kind: str, id: uuid.UUID) -> dict[str, Any] | None:
        """One thing as it is now, in the shape a history entry stores."""
        row = self._s.get(_MODELS[kind], id)
        if row is None:
            return None
        return self._dicts(kind, [row])[0]

    def snapshots_page(
        self, kind: str, after: str | None, limit: int
    ) -> list[dict[str, Any]]:
        """Up to `limit` things of `kind` in the order they were made, starting
        after the `snapshot_cursor` `after` (None: from the first)."""
        model = _MODELS[kind]
        query = self._s.query(model)
        if after:
            created, id_ = parse_snapshot_cursor(after)
            at, rid = _parse(created), uuid.UUID(id_)
            query = query.filter(
                or_(
                    model.created_at > at,
                    and_(model.created_at == at, model.id > rid),
                )
            )
        rows = query.order_by(model.created_at, model.id).limit(limit).all()
        return self._dicts(kind, rows)

    def record_seed_order(self) -> list[str]:
        """Every record's id, each after the records it needs to exist first: the
        one it sits under and the ones it refers to. Ties (and any records that
        refer to each other in a circle, which nothing can put first) keep
        creation order. A record that is deleted needs only its parent: nothing
        checks what it points at."""
        rows = (
            self._s.query(Record.id, Record.parent_record_id, Record.deleted_at)
            .order_by(Record.created_at, Record.id)
            .yield_per(2000)
        )
        position: dict[uuid.UUID, int] = {}
        parent: dict[uuid.UUID, uuid.UUID | None] = {}
        deleted: set[uuid.UUID] = set()
        for rid, parent_id, deleted_at in rows:
            position[rid] = len(position)
            parent[rid] = parent_id
            if deleted_at is not None:
                deleted.add(rid)

        needs: dict[uuid.UUID, set[uuid.UUID]] = {rid: set() for rid in position}
        for rid, parent_id in parent.items():
            if parent_id in position:
                needs[rid].add(parent_id)
        for rid, target in self._s.query(
            RecordReference.record_id, RecordReference.target_id
        ).yield_per(5000):
            if rid in position and rid not in deleted and target in position:
                needs[rid].add(target)
            # (a reference to itself, or to nothing here, needs nothing)
        for rid in position:
            needs[rid].discard(rid)

        waiting_on: dict[uuid.UUID, int] = {r: len(n) for r, n in needs.items()}
        needed_by: dict[uuid.UUID, list[uuid.UUID]] = {}
        for rid, n in needs.items():
            for dep in n:
                needed_by.setdefault(dep, []).append(rid)

        import heapq

        ready = [position[r] for r, w in waiting_on.items() if w == 0]
        heapq.heapify(ready)
        by_position = {i: r for r, i in position.items()}
        order: list[uuid.UUID] = []
        placed: set[uuid.UUID] = set()
        while ready:
            rid = by_position[heapq.heappop(ready)]
            order.append(rid)
            placed.add(rid)
            for dependant in needed_by.get(rid, ()):
                waiting_on[dependant] -= 1
                if waiting_on[dependant] == 0:
                    heapq.heappush(ready, position[dependant])
        # A circle of references: nothing can go first, so send them as made.
        order.extend(r for r in sorted(position, key=position.get) if r not in placed)  # type: ignore[arg-type]
        return [str(r) for r in order]

    def record_snapshots(self, ids: list[str]) -> list[dict[str, Any]]:
        """The records with these ids, as snapshots, in the order given."""
        wanted = [uuid.UUID(i) for i in ids]
        found = {
            r.id: r for r in self._s.query(Record).filter(Record.id.in_(wanted)).all()
        }
        return self._dicts("record", [found[i] for i in wanted if i in found])

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
            if "updated_at" in values:
                # Written even when it equals what is there: otherwise a change
                # to the other columns lets the column's on-update default stamp
                # it with this machine's clock, and the copies drift apart.
                flag_modified(row, "updated_at")
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
        if row is None:
            return
        if getattr(row, "deleted_at", None) is not None:
            # Already deleted here (by a cascade worked out from what this copy
            # held): take the stamp it was deleted with where the entry is
            # from, so every copy ends with the same one. What went with it
            # stays as it is: its own entries say where it stands.
            if kind == "record" and _parse(row.deleted_at.isoformat()) != stamp:
                row.deleted_at = stamp
                flag_modified(row, "updated_at")
                self._s.flush()
            return
        row.deleted_at = stamp
        if kind == "record":
            # A delete is not an edit: written explicitly, or the column's
            # on-update default would stamp it with this machine's clock.
            flag_modified(row, "updated_at")
        if kind == "schema":
            self._s.query(Record).filter(
                Record.schema_id == id, Record.deleted_at.is_(None)
            ).update(
                {"deleted_at": stamp, "updated_at": Record.updated_at},
                synchronize_session=False,
            )
        elif kind == "dataset":
            self._s.query(Record).filter(
                Record.dataset_id == id, Record.deleted_at.is_(None)
            ).update(
                {"deleted_at": stamp, "updated_at": Record.updated_at},
                synchronize_session=False,
            )
        self._s.flush()
        self._s.expire_all()

    def restore(self, kind: str, id: uuid.UUID) -> None:
        """Undo a delete as a person's restore does: a schema or collection
        brings back what its own restore brings back (the other repositories
        own those rules, so they are used rather than repeated)."""
        from civex.repositories.local.dataset_repo import LocalDatasetRepository
        from civex.repositories.local.schema_repo import LocalSchemaRepository

        row = self._s.get(_MODELS[kind], id)
        if row is None:
            return
        if kind == "schema":
            LocalSchemaRepository(self._s).restore(id)
        elif kind == "dataset":
            LocalDatasetRepository(self._s).restore(id)
        else:
            row.deleted_at = None
            if kind == "record":
                flag_modified(row, "updated_at")
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

    def get_entry(self, id: uuid.UUID) -> SyncEntry | None:
        row = self._s.get(AuditLog, id)
        return self._entries([row])[0] if row is not None else None

    def has_entry(self, id: uuid.UUID) -> bool:
        return self._s.get(AuditLog, id) is not None

    def pending_entries(self, limit: int) -> list[SyncEntry]:
        """Changes made here that the authority has not been sent, oldest first:
        `limit` of them, and the rest of the action the last one belongs to, so
        an action is never split across two pushes (it is taken whole or not)."""
        pending = self._s.query(AuditLog).filter(
            AuditLog.sync_state == "pending", AuditLog.hub_seq.is_(None)
        )
        rows = pending.order_by(*_WRITE_ORDER).limit(limit).all()
        if len(rows) == limit and rows[-1].op_id is not None:
            seen = {r.id for r in rows}
            rows += [
                r
                for r in pending.filter(AuditLog.op_id == rows[-1].op_id)
                .order_by(*_WRITE_ORDER)
                .all()
                if r.id not in seen
            ]
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
                if result.status in ("merged", "conflict"):
                    row.apply_state = "superseded"
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

    def all_ids(self, kind: str) -> set[str]:
        """Every id of `kind` held here, deleted ones included."""
        model = _MODELS[kind]
        return {str(i) for (i,) in self._s.query(model.id)}

    def existing_ids(self, kind: str, ids: set[str]) -> set[str]:
        """Which of these ids are things of `kind` here, deleted or not."""
        if not ids:
            return set()
        model = _MODELS[kind]
        wanted = [uuid.UUID(i) for i in ids]
        return {str(i) for (i,) in self._s.query(model.id).filter(model.id.in_(wanted))}

    def begin_seed(self) -> None:
        """Set aside the changes a seed covers: those not yet sent when the
        first attempt began. A seed run again after an interruption keeps the
        first attempt's set (any left are still `seeding`), so a change made in
        between is still sent on its own."""
        started = (
            self._s.query(AuditLog.id).filter(AuditLog.sync_state == "seeding").first()
        )
        if started is None:
            self._s.execute(
                update(AuditLog)
                .where(AuditLog.sync_state == "pending", AuditLog.hub_seq.is_(None))
                .values(sync_state="seeding")
                .execution_options(synchronize_session=False)
            )
            self._s.expire_all()

    def finish_seed(self) -> None:
        """The seed went in: what it covered counts as sent."""
        self._s.execute(
            update(AuditLog)
            .where(AuditLog.sync_state == "seeding")
            .values(sync_state="synced")
            .execution_options(synchronize_session=False)
        )
        self._s.expire_all()

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
        self,
        entry: SyncEntry,
        *,
        hub_seq: int | None,
        state: str = "synced",
        apply_state: str = "applied",
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
                delta=entry.delta,
                format=2 if entry.delta is not None else 1,
                op_id=uuid.UUID(entry.op) if entry.op else None,
                timestamp=_parse(entry.timestamp),
                batch_id=batch_id,
                actor=entry.actor,
                device_id=uuid.UUID(entry.device_id) if entry.device_id else None,
                hlc=entry.hlc,
                hub_seq=hub_seq,
                sync_state=state,
                apply_state=apply_state,
            )
        )
        self._s.flush()

    def held_entries(self) -> list[SyncEntry]:
        """Changes from the authority kept but not applied yet, oldest first."""
        rows = (
            self._s.query(AuditLog)
            .filter(AuditLog.apply_state == "held")
            .order_by(AuditLog.hub_seq)
            .all()
        )
        return self._entries(rows)

    def mark_applied(self, entry_ids: list[uuid.UUID]) -> None:
        if entry_ids:
            self._s.execute(
                update(AuditLog)
                .where(AuditLog.id.in_(entry_ids))
                .values(apply_state="applied")
                .execution_options(synchronize_session=False)
            )
            self._s.expire_all()

    def entries_of_action(self, op: str) -> list[SyncEntry]:
        """The entries one action wrote here, in the order written."""
        rows = (
            self._s.query(AuditLog)
            .filter(AuditLog.op_id == uuid.UUID(op))
            .order_by(*_WRITE_ORDER)
            .all()
        )
        return self._entries(rows)

    def numbered_entries(
        self, kind: str, entity_id: uuid.UUID, from_seq: int
    ) -> list[SyncEntry]:
        """A thing's numbered entries from `from_seq` on that the authority did
        not supersede, in its order: the steps that take the thing to where the
        authority has it."""
        rows = (
            self._s.query(AuditLog)
            .filter(
                AuditLog.entity_type == kind,
                AuditLog.entity_id == entity_id,
                AuditLog.hub_seq >= from_seq,
                AuditLog.apply_state != "superseded",
            )
            .order_by(AuditLog.hub_seq)
            .all()
        )
        return self._entries(rows)

    def sequence_local_entries(self) -> int:
        """Authority: number the changes made on this instance itself, in the
        order they were made, so they join the feed. Returns how many."""
        rows = (
            self._s.query(AuditLog)
            .filter(AuditLog.hub_seq.is_(None), AuditLog.sync_state == "pending")
            .order_by(*_WRITE_ORDER)
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
                delta=r.delta,
                op=str(r.op_id) if r.op_id else None,
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
        base=row.base,
        theirs_actor=row.theirs_actor,
        theirs_at=_iso(row.theirs_at),
        status=row.status,
        created_at=_iso(row.created_at) or "",
        resolved_at=_iso(row.resolved_at),
        resolution=row.resolution,
    )
