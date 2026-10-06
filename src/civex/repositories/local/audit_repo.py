from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    String,
    and_,
    case,
    cast,
    delete,
    func,
    not_,
    or_,
    select,
)
from sqlalchemy.orm import Session

from contextlib import contextmanager
from typing import Iterator

from civex.db.models import AuditBatch, AuditLog, Dataset, Field, Record, Schema
from civex.domain.audit_diff import stored_form, tombstone
from civex.domain.hlc import tick as hlc_tick
from civex.domain.audit_filter import AuditFilter
from civex.domain.exceptions import ValidationError
from civex.domain.filters import FilterCondition, FilterGroup, FilterNode
from civex.repositories.local._dates import utc
from civex.domain.dtos import AuditBatchDTO, AuditEventDTO, AuditLogDTO
from civex.repositories.local._bucketing import day_bucket
from civex.repositories.local._ids import prefix_span
from civex.repositories.protocols import AuditEventRow


def _mentions(text: str):
    """Entries whose stored values name this id: a child's parent, a record's
    collection, a reference. Finds records since purged, which are no longer
    rows to list by id. A delta entry holds a changed value in `delta`."""
    return or_(
        cast(AuditLog.old_data, String).contains(text),
        cast(AuditLog.new_data, String).contains(text),
        cast(AuditLog.delta, String).contains(text),
    )


def _names_schema(text: str):
    """Snapshots whose `schema_id` is this schema: its records, fields, views."""
    needle = f'"schema_id": "{text}"'
    return or_(
        cast(AuditLog.old_data, String).contains(needle),
        cast(AuditLog.new_data, String).contains(needle),
    )


def _how():
    """How a change came about: on its own, or as part of what kind of batch."""
    kind = (
        select(AuditBatch.kind)
        .where(AuditBatch.id == AuditLog.batch_id)
        .correlate(AuditLog)
        .scalar_subquery()
    )
    return case((AuditLog.batch_id.is_(None), "single"), else_=kind)


def _now_is(state: str):
    """The record, collection, schema or field a change is about is live,
    deleted (restorable) or gone. Changes to anything else (a view) are none of
    these, so a filter on it leaves them out."""
    parts = []
    for entity_type, table in (
        ("record", Record),
        ("dataset", Dataset),
        ("schema", Schema),
        ("field", Field),
    ):
        about = AuditLog.entity_type == entity_type
        if state == "live":
            test = AuditLog.entity_id.in_(
                select(table.id).where(table.deleted_at.is_(None))
            )
        elif state == "deleted":
            test = AuditLog.entity_id.in_(
                select(table.id).where(table.deleted_at.is_not(None))
            )
        else:
            test = AuditLog.entity_id.not_in(select(table.id))
        parts.append(and_(about, test))
    return or_(*parts)


def _is_in(column, op: str, value: Any):
    """eq / ne / in over one column, as the filter builder offers them."""
    match op:
        case "eq":
            return column == value
        case "ne":
            return column != value
        case "in":
            return column.in_(value)
    raise ValidationError(f"Unsupported operator '{op}'")


def _scoped(op: str, values: list, one):
    """A condition built per value (`one(value)`), for the fields whose test is
    not one column: in any of them (eq/in), or in none (ne)."""
    found = or_(*[one(v) for v in values])
    return not_(found) if op == "ne" else found


def _condition(leaf: FilterCondition):
    field, op, value = leaf.field, leaf.op, leaf.value
    match field:
        case "when":
            return _is_when(op, utc(value))
        case "kind":
            return _is_in(AuditLog.entity_type, op, value)
        case "change":
            return _is_in(AuditLog.action, op, value)
        case "how":
            return _is_in(_how(), op, value)
        case "collection":
            # Values are collection ids by now: AuditService turns the names a
            # person picks into ids, so a rename can't lose their history.
            return _scoped(
                op,
                value if isinstance(value, list) else [value],
                lambda cid: or_(
                    AuditLog.entity_id == uuid.UUID(str(cid)), _mentions(str(cid))
                ),
            )
        case "schema":
            # Values are schema ids by now (AuditService resolves the names). A
            # record, a field and a view each carry their schema's id; the
            # schema's own entries are found by their own id.
            return _scoped(
                op,
                value if isinstance(value, list) else [value],
                lambda sid: or_(
                    AuditLog.entity_id == uuid.UUID(str(sid)),
                    _names_schema(str(sid)),
                ),
            )
        case "under":
            # The value is the record's id followed by every record beneath it,
            # resolved by AuditService.
            ids = [uuid.UUID(str(v)) for v in value]
            return or_(AuditLog.entity_id.in_(ids), _mentions(str(ids[0])))
        case "now":
            return _scoped(op, value if isinstance(value, list) else [value], _now_is)
    raise ValidationError(f"Unknown history field '{field}'")


def _is_when(op: str, when: datetime):
    match op:
        case "gt":
            return AuditLog.timestamp > when
        case "gte":
            return AuditLog.timestamp >= when
        case "lt":
            return AuditLog.timestamp < when
        case "lte":
            return AuditLog.timestamp <= when
    raise ValidationError(f"Unsupported operator '{op}'")


def _tree(node: FilterNode):
    if isinstance(node, FilterGroup):
        parts = [_tree(c) for c in node.conditions]
        return and_(*parts) if node.op == "and" else or_(*parts)
    return _condition(node)


class LocalAuditRepository:
    def __init__(
        self,
        session: Session,
        actor: str | None = None,
        device_id: uuid.UUID | None = None,
    ) -> None:
        self._s = session
        # Who is writing: stamped on every entry made through this repository.
        self._actor = actor
        # Which device, once this project syncs: stamped with a clock value that
        # sorts in causal order (see domain/hlc).
        self._device_id = device_id
        self._last_hlc: str | None = None
        # The batch the next writes belong to. A batch opened with `batch()` is
        # only created once something is written into it, so one that turns out
        # to touch nothing leaves no trace.
        self._batch_id: uuid.UUID | None = None
        self._batch_spec: tuple[str, str | None, str | None] | None = None

    # ------------------------------------------------------------------
    # Batches
    # ------------------------------------------------------------------

    @contextmanager
    def batch(
        self, kind: str, label: str | None = None, ref: str | None = None
    ) -> Iterator[None]:
        """Everything logged inside belongs to one batch. Inside another batch
        (or one joined with `join_batch`) it simply joins that one, so a
        workflow run that deletes a tree is still the run's one event."""
        if self._batch_id is not None or self._batch_spec is not None:
            yield
            return
        self._batch_spec = (kind, label, ref)
        try:
            yield
        finally:
            self._batch_spec = None
            self._batch_id = None

    def open_batch(
        self, kind: str, label: str | None = None, ref: str | None = None
    ) -> AuditBatchDTO:
        """Create a batch now, for a caller that does its work over several
        requests (a browser import) and sends the id with each."""
        row = AuditBatch(
            kind=kind, label=label, ref=ref, created_at=datetime.now(timezone.utc)
        )
        self._s.add(row)
        self._s.flush()
        return _batch_dto(row)

    def join_batch(self, batch_id: uuid.UUID) -> bool:
        """Log everything that follows into an existing batch. False, and
        nothing changes, if there is no such batch."""
        if self._s.get(AuditBatch, batch_id) is None:
            return False
        self._batch_id = batch_id
        return True

    def get_batch(self, batch_id: uuid.UUID) -> AuditBatchDTO | None:
        row = self._s.get(AuditBatch, batch_id)
        return _batch_dto(row) if row else None

    def _next_hlc(self) -> str | None:
        """The clock stamp for the next entry: None until this project syncs."""
        if self._device_id is None:
            return None
        if self._last_hlc is None:
            self._last_hlc = self._s.query(func.max(AuditLog.hlc)).scalar()
        wall_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        self._last_hlc = hlc_tick(self._last_hlc, wall_ms)
        return self._last_hlc

    def _current_batch(self) -> uuid.UUID | None:
        if self._batch_id is None and self._batch_spec is not None:
            kind, label, ref = self._batch_spec
            self._batch_id = self.open_batch(kind, label, ref).id
        return self._batch_id

    # ------------------------------------------------------------------
    # Write-side (satisfies AuditRepository protocol — called by services)
    # ------------------------------------------------------------------

    def log_change(
        self,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID,
        old_data: dict[str, Any] | None,
        new_data: dict[str, Any] | None,
        timestamp: datetime | None = None,
    ) -> None:
        """`timestamp` is when it happened, now unless the caller says: a delete
        passes the moment it stamps what it deletes with, so the entry and the
        stamp are one instant and every device that applies the entry stamps
        exactly the same."""
        old_data, new_data, delta, form = stored_form(old_data, new_data)
        self._s.add(
            AuditLog(
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                old_data=old_data,
                new_data=new_data,
                delta=delta,
                format=form,
                timestamp=timestamp or datetime.now(timezone.utc),
                batch_id=self._current_batch(),
                actor=self._actor,
                device_id=self._device_id,
                hlc=self._next_hlc(),
            )
        )

    def event_counts_by_period(
        self,
        start: datetime | None,
        end: datetime | None,
        entity_type: str | None = None,
        action: str | None = None,
    ) -> list[AuditEventRow]:
        """Audit entries per day, broken out by action and entity_type --
        backs the activity-over-time widget. `entity_type`/`action` narrow
        to a single value each; the breakdown itself is never collapsed."""
        day = day_bucket(AuditLog.timestamp)
        q = self._s.query(
            day, AuditLog.action, AuditLog.entity_type, func.count(AuditLog.id)
        )
        if start is not None:
            q = q.filter(AuditLog.timestamp >= start)
        if end is not None:
            q = q.filter(AuditLog.timestamp < end)
        if entity_type is not None:
            q = q.filter(AuditLog.entity_type == entity_type)
        if action is not None:
            q = q.filter(AuditLog.action == action)
        rows = (
            q.group_by(day, AuditLog.action, AuditLog.entity_type).order_by(day).all()
        )
        return [
            (d, action, entity_type, count) for d, action, entity_type, count in rows
        ]

    def get_audit(self, audit_id: uuid.UUID) -> AuditLogDTO | None:
        row = self._s.get(AuditLog, audit_id)
        return _audit_dto(row) if row else None

    def find_audit(self, prefix: str) -> list[AuditLogDTO]:
        """Entries whose id starts with `prefix`, at most two: enough to tell
        none, one and ambiguous apart."""
        span = prefix_span(prefix)
        if span is None:
            return []
        rows = self._s.query(AuditLog).filter(AuditLog.id.between(*span)).limit(2)
        return [_audit_dto(r) for r in rows]

    def list_audit(
        self,
        limit: int = 50,
        offset: int = 0,
        sort: str | None = None,
        **filters: Any,
    ) -> list[AuditLogDTO]:
        """Entries matching `AuditFilter(**filters)`, newest first unless `sort`
        (`timestamp` or `action`, then `:asc` / `:desc`) says otherwise."""
        q = self._audit_query(AuditFilter(**filters))
        name, _, direction = (sort or "").partition(":")
        col = {"timestamp": AuditLog.timestamp, "action": AuditLog.action}.get(name)
        terms = [] if col is None else [col.asc() if direction == "asc" else col.desc()]
        return [
            _audit_dto(r)
            for r in q.order_by(*terms, AuditLog.timestamp.desc())
            .offset(offset)
            .limit(limit)
            .all()
        ]

    def count_audit(self, **filters: Any) -> int:
        return self._audit_query(AuditFilter(**filters)).count()

    def list_events(
        self,
        f: AuditFilter,
        limit: int = 25,
        offset: int = 0,
        newest_first: bool = True,
    ) -> tuple[list[AuditEventDTO], int]:
        """History as events: a batch is one event however many entries it
        holds, any other entry is its own. Filters match entries; an event is
        listed when any of its entries match, with how many did."""
        base = self._audit_query(f)
        group = func.coalesce(AuditLog.batch_id, AuditLog.id)
        latest = func.max(AuditLog.timestamp)
        total = base.with_entities(func.count(func.distinct(group))).scalar() or 0
        rows = (
            base.with_entities(group, latest, func.count(AuditLog.id))
            .group_by(group)
            .order_by(latest.desc() if newest_first else latest.asc(), group)
            .offset(offset)
            .limit(limit)
            .all()
        )
        keys = [r[0] for r in rows]
        batches = {
            b.id: _batch_dto(b)
            for b in self._s.query(AuditBatch).filter(AuditBatch.id.in_(keys))
        }
        entries = {
            e.id: _audit_dto(e)
            for e in self._s.query(AuditLog).filter(
                AuditLog.id.in_([k for k in keys if k not in batches])
            )
        }
        parts = self._parts(base, list(batches))
        # A batch is made in one go by one person: any of its entries' actors.
        batch_actor: dict[uuid.UUID | None, str | None] = {}
        if batches:
            for bid, who in (
                self._s.query(AuditLog.batch_id, func.min(AuditLog.actor))
                .filter(AuditLog.batch_id.in_(list(batches)))
                .group_by(AuditLog.batch_id)
            ):
                batch_actor[bid] = who
        events = [
            AuditEventDTO(
                id=key,
                timestamp=ts,
                count=n,
                entry=entries.get(key),
                batch=batches.get(key),
                parts=parts.get(key, []),
                actor=(entries[key].actor if key in entries else batch_actor.get(key)),
            )
            for key, ts, n in rows
        ]
        return events, total

    # ------------------------------------------------------------------
    # Forgetting records that were permanently deleted
    # ------------------------------------------------------------------

    def _holds_values(self) -> list:
        """An entry that is not a tombstone: it is still a record's history."""
        marker = '"tombstone": true'
        return [
            not_(func.coalesce(cast(AuditLog.old_data, String), "").contains(marker)),
            not_(func.coalesce(cast(AuditLog.new_data, String), "").contains(marker)),
        ]

    def _is_tombstone(self):
        marker = '"tombstone": true'
        return or_(
            func.coalesce(cast(AuditLog.old_data, String), "").contains(marker),
            func.coalesce(cast(AuditLog.new_data, String), "").contains(marker),
        )

    def _forget(self, *conditions) -> int:
        """Delete every record entry matching `conditions` that is not a
        tombstone, then any batch left with nothing in it."""
        entries = self._s.execute(
            delete(AuditLog)
            .where(AuditLog.entity_type == "record", *self._holds_values(), *conditions)
            .execution_options(synchronize_session=False)
        ).rowcount  # type: ignore[attr-defined]
        if entries:
            self._drop_empty_batches()
        self._s.expire_all()
        return entries or 0

    def _drop_empty_batches(self) -> int:
        used = select(AuditLog.batch_id).where(AuditLog.batch_id.is_not(None))
        return (
            self._s.execute(
                delete(AuditBatch)
                .where(AuditBatch.id.not_in(used))
                .execution_options(synchronize_session=False)
            ).rowcount  # type: ignore[attr-defined]
            or 0
        )

    def forget_records(self, ids: list[uuid.UUID]) -> int:
        """Delete every entry about these records: all the history there is of
        them, once they are permanently deleted. The caller then logs a
        tombstone for each (a `purge` entry holding only who they were)."""
        gone = 0
        for start in range(0, len(ids), 500):
            gone += self._forget(AuditLog.entity_id.in_(ids[start : start + 500]))
        return gone

    def forget_records_matching(self, needle: str) -> int:
        """Delete every record entry whose snapshot contains `needle`: a
        collection's or schema's records, once it is permanently deleted and
        they went with it. Its own purge entry is the tombstone."""
        return self._forget(
            or_(
                cast(AuditLog.old_data, String).contains(needle),
                cast(AuditLog.new_data, String).contains(needle),
            )
        )

    def _orphaned(self):
        return (
            AuditLog.entity_type == "record",
            AuditLog.entity_id.not_in(select(Record.id)),
        )

    def count_orphaned_records(self) -> int:
        """Entries still holding values of records that no longer exist: what
        permanently deleting them used to leave behind."""
        return (
            self._s.query(AuditLog)
            .filter(*self._orphaned(), *self._holds_values())
            .count()
        )

    def forget_orphaned_records(self) -> int:
        """Delete the entries `count_orphaned_records` counts, leaving each
        record one tombstone made from what its history held of who it was."""
        removed = 0
        while True:
            rows = (
                self._s.query(AuditLog)
                .filter(*self._orphaned(), *self._holds_values())
                .order_by(AuditLog.entity_id)
                .limit(500)
                .all()
            )
            if not rows:
                return removed
            by_record: dict[uuid.UUID, list[AuditLog]] = {}
            for row in rows:
                by_record.setdefault(row.entity_id, []).append(row)
            # Every entry of the last record in the chunk may not have been
            # read yet: leave it for the next round.
            last = rows[-1].entity_id
            if len(rows) == 500 and len(by_record) > 1:
                by_record.pop(last)
            for record_id, entries in by_record.items():
                snapshot: dict[str, Any] = next(
                    (
                        e.old_data or e.new_data or {}
                        # A purge's tombstone, else a whole snapshot (a create
                        # or delete) before an edit, which keeps only identity.
                        for e in sorted(
                            entries,
                            key=lambda e: (
                                e.action != "purge",
                                e.action not in ("create", "delete"),
                            ),
                        )
                        if e.old_data or e.new_data
                    ),
                    {"id": str(record_id)},
                )
                has_tombstone = (
                    self._s.query(AuditLog)
                    .filter(
                        AuditLog.entity_type == "record",
                        AuditLog.entity_id == record_id,
                        self._is_tombstone(),
                    )
                    .count()
                    > 0
                )
                for entry in entries:
                    self._s.delete(entry)
                    removed += 1
                if not has_tombstone:
                    self._s.add(
                        AuditLog(
                            action="purge",
                            entity_type="record",
                            entity_id=record_id,
                            old_data=tombstone(snapshot),
                            new_data=None,
                            timestamp=max(e.timestamp for e in entries),
                            actor=self._actor,
                        )
                    )
            self._s.flush()
            self._drop_empty_batches()

    def _prunable(self, before: datetime, protect_unsynced: bool) -> list:
        """The conditions for an entry that may be removed: older than `before`,
        not about something that can still be restored, and (with a remote) not
        waiting to be synced."""
        conditions: list = [
            AuditLog.timestamp < before,
            not_(_now_is("deleted")),
        ]
        if protect_unsynced:
            conditions.append(AuditLog.sync_state != "pending")
        return conditions

    def count_prunable(
        self, before: datetime, protect_unsynced: bool
    ) -> dict[str, int]:
        """How many entries `prune` would remove, and how many older ones it
        would keep and why."""
        older = self._s.query(AuditLog).filter(AuditLog.timestamp < before)
        removable = (
            self._s.query(AuditLog)
            .filter(*self._prunable(before, protect_unsynced))
            .count()
        )
        restorable = older.filter(_now_is("deleted")).count()
        unsynced = older.count() - restorable - removable
        return {
            "entries": removable,
            "kept_restorable": restorable,
            "kept_unsynced": max(unsynced, 0),
        }

    def prune(self, before: datetime, protect_unsynced: bool) -> tuple[int, int]:
        """Remove the entries `count_prunable` counted, and any batch left with
        none. Returns (entries, batches) removed."""
        ids = select(AuditLog.id).where(*self._prunable(before, protect_unsynced))
        entries = self._s.execute(
            delete(AuditLog)
            .where(AuditLog.id.in_(ids))
            .execution_options(synchronize_session=False)
        ).rowcount  # type: ignore[attr-defined]
        batches = self._drop_empty_batches()
        self._s.expire_all()
        return entries or 0, batches

    def entities(
        self, f: AuditFilter, limit: int
    ) -> tuple[list[tuple[str, uuid.UUID]], bool]:
        """The distinct things (type, id) the matching entries are about, newest
        first, at most `limit`; and whether there were more."""
        rows = (
            self._audit_query(f)
            .with_entities(AuditLog.entity_type, AuditLog.entity_id)
            .group_by(AuditLog.entity_type, AuditLog.entity_id)
            .order_by(func.max(AuditLog.timestamp).desc())
            .limit(limit + 1)
            .all()
        )
        return [(t, i) for t, i in rows[:limit]], len(rows) > limit

    def batch_parts(self, batch_id: uuid.UUID) -> list[dict]:
        """What a batch holds, by kind of thing and action, with counts."""
        base = self._s.query(AuditLog)
        return self._parts(base, [batch_id]).get(batch_id, [])

    def _parts(self, base, batch_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
        parts: dict[uuid.UUID, list[dict]] = {}
        if not batch_ids:
            return parts
        rows = (
            base.filter(AuditLog.batch_id.in_(batch_ids))
            .with_entities(
                AuditLog.batch_id,
                AuditLog.entity_type,
                AuditLog.action,
                func.count(AuditLog.id),
            )
            .group_by(AuditLog.batch_id, AuditLog.entity_type, AuditLog.action)
            .all()
        )
        for bid, etype, act, n in rows:
            parts.setdefault(bid, []).append(
                {"entity_type": etype, "action": act, "count": n}
            )
        for found in parts.values():
            found.sort(key=lambda p: (-p["count"], p["entity_type"]))
        return parts

    def _audit_query(self, f: AuditFilter):
        q = self._s.query(AuditLog)
        if f.since is not None:
            q = q.filter(AuditLog.timestamp >= f.since)
        if f.action:
            q = q.filter(AuditLog.action == f.action)
        if f.entity_ids is not None:
            q = q.filter(AuditLog.entity_id.in_(f.entity_ids))
        elif f.entity_id is not None:
            q = q.filter(AuditLog.entity_id == f.entity_id)
        if f.entity_type is not None:
            q = q.filter(AuditLog.entity_type == f.entity_type)
        if f.batch_id is not None:
            q = q.filter(AuditLog.batch_id == f.batch_id)
        if f.where is not None:
            q = q.filter(_tree(f.where))
        if f.search:
            # A text match over what the entry stored and the label of the batch
            # it belongs to: enough to find a change, not a ranked search.
            q = q.filter(
                or_(
                    cast(AuditLog.old_data, String).icontains(
                        f.search, autoescape=True
                    ),
                    cast(AuditLog.new_data, String).icontains(
                        f.search, autoescape=True
                    ),
                    cast(AuditLog.delta, String).icontains(f.search, autoescape=True),
                    AuditLog.batch_id.in_(
                        select(AuditBatch.id).where(
                            AuditBatch.label.icontains(f.search, autoescape=True)
                        )
                    ),
                )
            )
        return q


def _batch_dto(r: AuditBatch) -> AuditBatchDTO:
    return AuditBatchDTO(
        id=r.id, kind=r.kind, label=r.label, ref=r.ref, created_at=r.created_at
    )


def _audit_dto(r: AuditLog) -> AuditLogDTO:
    return AuditLogDTO(
        id=r.id,
        action=r.action,
        entity_type=r.entity_type,
        entity_id=r.entity_id,
        old_data=r.old_data,
        new_data=r.new_data,
        timestamp=r.timestamp,
        actor=r.actor,
        delta=r.delta,
        format=r.format,
    )


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
