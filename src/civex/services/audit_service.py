"""History: reading the audit log, and undoing what it records.

The one home for both, so the web UI, the CLI and scripts agree. Entries come
back with `changes` already worked out (`domain/audit_diff.py`), and reverting
is planned and applied here -- `plan_revert` is the single rule set behind the
preview a person confirms and the revert that follows it.

A revert never writes storage itself. It goes back through `RecordService`
(`update`, `delete`, `restore`), so validation, reference checks, workflow
triggers and a fresh audit entry all happen exactly as for any other edit, and
the revert can itself be reverted.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import replace
import uuid
from collections.abc import Callable
from typing import Any

from civex.domain.audit_filter import AuditFilter
from civex.domain.audit_filters import parse_audit_filter
from civex.domain.filters import FilterCondition, FilterGroup, FilterNode
from civex.domain.audit_diff import Change, diff_entry, entry_snapshots, strip_derived
from civex.domain.dtos import (
    REVERT_APPLY,
    REVERT_CONFLICT,
    REVERT_SAME,
    REVERT_SKIPPED,
    AuditBatchDTO,
    AuditEventDTO,
    AuditLogDTO,
    RecordDTO,
    RestoreAllPlanDTO,
    RestoreAllResultDTO,
    ResolvedSchema,
    RevertFieldDTO,
    RevertPlanDTO,
    RevertResultDTO,
)
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.repositories.protocols import AuditRepository, FileObjectStore
from civex.services.dataset_service import DatasetService
from civex.services.record_service import RecordService
from civex.services.schema_service import SchemaService


# How many things a restore-all will look at, and how many rounds it will make
# to bring back records under others in the same set.
MAX_RESTORE_ALL = 5000
MAX_RESTORE_PASSES = 8


class AuditService:
    def __init__(
        self,
        audit: AuditRepository,
        schema_svc: SchemaService,
        record_svc: RecordService,
        dataset_svc: DatasetService,
        files: FileObjectStore,
        sync_conflicts: Callable[[list[uuid.UUID]], dict[uuid.UUID, list[Any]]]
        | None = None,
    ) -> None:
        # What became of each change sent to an authority (None: no sync, so
        # nothing to say). A callable, so history reads it without knowing sync.
        self._sync_conflicts = sync_conflicts
        self._audit = audit
        self._schema_svc = schema_svc
        self._records = record_svc
        self._datasets = dataset_svc
        self._files = files

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def events(
        self,
        where: Any = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 25,
        newest_first: bool = True,
    ) -> tuple[list[AuditEventDTO], int]:
        """History as events, newest first: a batch (an import, a delete that
        took a tree, a workflow run) is one event however many entries it holds,
        and any other entry is its own, with its `changes`.

        `where` is the filter tree a person builds over `AUDIT_FIELDS` (JSON text or
        already decoded), the same kind as records and runs have; `search` is text to find in what a change
        stored (a value, a file's name) or in a batch's label. An event is listed
        when any of its changes match, with how many did. A batch's entries are
        read with `page(batch_id=)`."""
        found, total = self._audit.list_events(
            AuditFilter(
                where=self._resolve(tree) if (tree := _parsed(where)) else None,
                search=search,
            ),
            limit=limit,
            offset=offset,
            newest_first=newest_first,
        )
        singles = {
            e.id: e for e in self._with_changes([ev.entry for ev in found if ev.entry])
        }
        for ev in found:
            if ev.entry is not None:
                ev.entry = singles[ev.entry.id]
        return found, total

    def _resolve(self, node: FilterNode) -> FilterNode:
        """The filter with what a person picked turned into what the repository
        tests: a collection or schema by name becomes its id (so a rename can't lose
        its history), a record id becomes that record and everything beneath it,
        live or deleted."""
        if isinstance(node, FilterGroup):
            return FilterGroup(node.op, [self._resolve(c) for c in node.conditions])
        if node.field == "collection":
            values = node.value if isinstance(node.value, list) else [node.value]
            return replace(
                node, value=[str(self._datasets.id_of(str(v))) for v in values]
            )
        if node.field == "schema":
            values = node.value if isinstance(node.value, list) else [node.value]
            return replace(
                node, value=[str(self._schema_svc.id_of(str(v))) for v in values]
            )
        if node.field == "under":
            return replace(
                node, value=[str(i) for i in self._records.subtree_ids(str(node.value))]
            )
        return node

    def batch_event(self, batch_id: uuid.UUID) -> AuditEventDTO:
        """One batch as an event, with everything in it counted."""
        batch: AuditBatchDTO | None = self._audit.get_batch(batch_id)
        if batch is None:
            raise NotFoundError(f"Batch '{batch_id}' not found")
        parts = self._audit.batch_parts(batch_id)
        return AuditEventDTO(
            id=batch.id,
            timestamp=batch.created_at,
            count=sum(p["count"] for p in parts),
            batch=batch,
            parts=parts,
        )

    def batch(self, kind: str, label: str | None = None, ref: str | None = None):
        """Everything logged inside is one event in history: a workflow run, an
        import. Joins an enclosing batch rather than starting another."""
        return self._audit.batch(kind, label, ref)

    def scope_of(self, kind: str, ref: str) -> dict[str, Any]:
        """The `page` / `count` scope for one thing's history: a `record` (id or
        prefix), a `schema` (name; its own fields' entries included, inherited
        ones not) or a `collection` (name or id). Raises NotFoundError."""
        if kind == "record":
            return {"entity_id": self._record_id(ref), "entity_type": "record"}
        if kind == "schema":
            schema = self._schema_svc.get(ref)
            return {"entity_ids": [schema.id] + [f.id for f in schema.fields]}
        if kind == "collection":
            try:
                dataset = self._datasets.get_by_id(uuid.UUID(ref))
            except ValueError:
                dataset = self._datasets.get(ref)
            return {"entity_id": dataset.id, "entity_type": "dataset"}
        raise ValidationError(f"No history for '{kind}'")

    def _record_id(self, ref: str) -> uuid.UUID:
        """A record's id from its id or a prefix of it. Its history outlives it:
        a deleted record is found by a prefix too, and one permanently deleted
        by its whole id."""
        try:
            return self._records.subtree_ids(ref)[0]
        except NotFoundError:
            try:
                whole = uuid.UUID(ref)
            except ValueError:
                whole = None
            # Permanently deleted: nothing but its history is left, so a whole id
            # with history is a record that was; one without is no record at all.
            if whole is not None and self._audit.count_audit(entity_id=whole):
                return whole
            raise NotFoundError(
                f"Record '{ref}' not found. If it was permanently deleted, "
                "give its whole id."
            ) from None

    def page(
        self,
        offset: int = 0,
        limit: int = 50,
        action: str | None = None,
        sort: str | None = None,
        **scope: Any,
    ) -> list[AuditLogDTO]:
        """One page of entries for `scope` (`entity_id`, `entity_type`,
        `entity_ids`), each with its `changes`."""
        entries = self._audit.list_audit(
            offset=offset, limit=limit, action=action, sort=sort, **scope
        )
        return self._with_changes(entries)

    def count(self, action: str | None = None, **scope: Any) -> int:
        return self._audit.count_audit(action=action, **scope)

    def get(self, ref: uuid.UUID | str) -> AuditLogDTO:
        """One entry, by id or by a short prefix of it (as the CLI lists them)."""
        entry = self._find(ref)
        return self._with_changes([entry])[0]

    def _find(self, ref: uuid.UUID | str) -> AuditLogDTO:
        if isinstance(ref, uuid.UUID):
            found = self._audit.get_audit(ref)
            matches = [found] if found else []
        else:
            try:
                found = self._audit.get_audit(uuid.UUID(ref))
                matches = [found] if found else []
            except ValueError:
                matches = self._audit.find_audit(ref)
        if not matches:
            raise NotFoundError(f"History entry '{ref}' not found")
        if len(matches) > 1:
            raise ValidationError(f"'{ref}' matches more than one history entry")
        return matches[0]

    def _with_changes(self, entries: list[AuditLogDTO]) -> list[AuditLogDTO]:
        shapes = self._schema_svc.resolver()
        now = self._where_now(entries)
        sync = (
            self._sync_conflicts([e.id for e in entries])
            if self._sync_conflicts and entries
            else {}
        )
        return [
            dataclasses.replace(
                e,
                changes=[c.to_dict() for c in self._diff(e, shapes)],
                now=now.get(e.entity_id),
                sync=[c.to_dict() for c in sync.get(e.id, [])],
            )
            for e in entries
        ]

    def _where_now(self, entries: list[AuditLogDTO]) -> dict[uuid.UUID, dict[str, Any]]:
        """Where each record, collection or schema an entry is about is now:
        live, deleted (and so restorable) or gone for good, with its name and
        `ref` (what to restore it by). One lookup per kind for the whole page."""
        where: dict[uuid.UUID, dict[str, Any]] = {}
        records = {e.entity_id: e for e in entries if e.entity_type == "record"}
        found = {r.id: r for r in self._records.labels([str(i) for i in records])}
        shapes = self._schema_svc.resolver()
        for rid, entry in records.items():
            record = found.get(rid)
            if record is None:
                # Gone for good: no name left, but the snapshot still says what
                # kind of record it was.
                old, new = entry_snapshots(entry.old_data, entry.new_data, entry.delta)
                schema_id = _schema_id(new) or _schema_id(old)
                shape = shapes(schema_id) if schema_id else None
                where[rid] = {
                    "kind": "record",
                    "status": "gone",
                    "schema_name": shape.schema.name if shape else None,
                }
            else:
                where[rid] = {
                    "kind": "record",
                    "ref": str(rid),
                    "status": "deleted" if record.deleted_at else "live",
                    "name": record.natural_name,
                    "schema_name": record.schema_name,
                    "collection": record.dataset_name,
                    "deleted_at": record.deleted_at.isoformat()
                    if record.deleted_at
                    else None,
                }
        for kind, etype, lookup in (
            ("collection", "dataset", self._datasets.find),
            ("schema", "schema", self._schema_svc.find),
        ):
            ids = {e.entity_id for e in entries if e.entity_type == etype}
            things = lookup(ids)
            for tid in ids:
                thing = things.get(tid)
                where[tid] = (
                    {"kind": kind, "status": "gone"}
                    if thing is None
                    else {
                        "kind": kind,
                        "ref": thing.name,
                        "status": "deleted" if thing.deleted_at else "live",
                        "name": thing.name,
                        "deleted_at": thing.deleted_at.isoformat()
                        if thing.deleted_at
                        else None,
                    }
                )
        field_ids = {e.entity_id for e in entries if e.entity_type == "field"}
        if field_ids:
            fields = self._schema_svc.find_fields(field_ids)
            for fid in field_ids:
                found_field = fields.get(fid)
                where[fid] = (
                    {"kind": "field", "status": "gone"}
                    if found_field is None
                    else {
                        "kind": "field",
                        "ref": str(fid),
                        "status": "deleted" if found_field[0].deleted_at else "live",
                        "name": found_field[0].name,
                        "schema_name": found_field[1],
                        "deleted_at": found_field[0].deleted_at.isoformat()
                        if found_field[0].deleted_at
                        else None,
                    }
                )
        return where

    def _diff(self, entry: AuditLogDTO, shapes) -> list[Change]:
        old, new = entry_snapshots(entry.old_data, entry.new_data, entry.delta)
        shape: ResolvedSchema | None = None
        if entry.entity_type == "record":
            schema_id = _schema_id(new) or _schema_id(old)
            shape = shapes(schema_id) if schema_id else None
            old, new = _by_field_name(old, shape), _by_field_name(new, shape)
        changes = diff_entry(entry.entity_type, entry.action, old, new)
        if shape is None:
            return changes
        # Schema order, as on the record form, not alphabetical. A field since
        # renamed or deleted has no place there and no label or type to show.
        order = {rf.field.name: i for i, rf in enumerate(shape.fields)}
        for change in changes:
            field = shape.by_name.get(change.field)
            if field is not None:
                change.label, change.dtype = field.display_name, field.dtype
            elif change.field in shape.deleted_by_id:
                gone = shape.deleted_by_id[change.field]
                change.label, change.dtype = gone.field.display_name, gone.field.dtype
                change.deleted = {
                    "status": "deleted",
                    "id": change.field,
                    "schema_name": gone.schema_name,
                    "deleted_at": gone.field.deleted_at.isoformat()
                    if gone.field.deleted_at
                    else None,
                }
            elif _is_uuid(change.field):
                # A field id nothing resolves any more: deleted for good.
                change.label = "(deleted field)"
                change.deleted = {"status": "gone", "id": change.field}
        return sorted(changes, key=lambda c: (order.get(c.field, len(order)), c.field))

    # ------------------------------------------------------------------
    # Restoring what is deleted
    # ------------------------------------------------------------------

    def plan_restore_all(
        self,
        where: Any = None,
        search: str | None = None,
        batch_id: uuid.UUID | str | None = None,
    ) -> RestoreAllPlanDTO:
        """What restoring everything deleted that a filter matches would do,
        without doing it. The filter is the one history is browsed with; only
        things that are deleted now, and whose history says they were deleted,
        count. With `batch_id`, only what that one bulk delete took (a record
        and everything beneath it, say), so it can be undone as the one event
        it was."""
        collections, schemas, fields, records, truncated = self._deleted_matching(
            where, search, batch_id
        )
        blocked = 0
        for schema_name, field_id in fields:
            plan = self._schema_svc.restore_field_plan(schema_name, field_id)
            b = plan.blocked_by
            covered = b is not None and b.kind == "schema" and b.name in schemas
            if plan.reason or (b is not None and not covered):
                blocked += 1
        # Whether each can come back, and what comes back with it, is worked out
        # for all of them together: a record at a time was a dozen queries each.
        wanted = self._records.plan_restore_set(records, set(collections), set(schemas))
        blocked += len(wanted.blocked)
        restores = len(wanted.coming)
        restores += sum(self._datasets.restore_plan(n).records for n in collections)
        restores += sum(self._schema_svc.restore_plan(n).records for n in schemas)
        return RestoreAllPlanDTO(
            len(collections),
            len(schemas),
            len(records),
            restores,
            blocked,
            truncated,
            fields=len(fields),
        )

    def restore_all(
        self,
        where: Any = None,
        search: str | None = None,
        batch_id: uuid.UUID | str | None = None,
    ) -> RestoreAllResultDTO:
        """Restore everything deleted that a filter matches, as one event in
        history. Collections and schemas first, then records parent-first; a
        record still under something deleted that is not in the set stays
        deleted and is counted as blocked."""
        collections, schemas, fields, records, _ = self._deleted_matching(
            where, search, batch_id
        )
        restored = came_back = 0
        field_blocked = 0
        with self._audit.batch("restore", "Restore all"):
            for name in collections:
                came_back += self._datasets.restore_plan(name).records
                self._datasets.restore(name)
                restored += 1
            for name in schemas:
                came_back += self._schema_svc.restore_plan(name).records
                self._schema_svc.restore(name)
                restored += 1
            for schema_name, field_id in fields:
                try:
                    self._schema_svc.restore_field(schema_name, field_id)
                except (NotFoundError, ValidationError):
                    field_blocked += 1  # its name was taken, or it is already back
                    continue
                restored += 1
            pending = list(records)
            # A record under another in the set comes back with it, or once it
            # has: go round until nothing more can. Each round restores every
            # record that nothing deleted holds back, all together.
            for _ in range(MAX_RESTORE_PASSES):
                if not pending:
                    break
                done = self._records.restore_set(pending)
                restored += done.restored
                came_back += done.came_back
                pending = done.left
                if not done.restored:
                    break
        return RestoreAllResultDTO(restored, came_back, len(pending) + field_blocked)

    def _deleted_matching(
        self,
        where: Any,
        search: str | None,
        batch_id: uuid.UUID | str | None = None,
    ) -> tuple[list[str], list[str], list[tuple[str, uuid.UUID]], list[str], bool]:
        """Names of the deleted collections, names of the deleted schemas, the
        deleted fields as (schema name, field id) and ids of the deleted records
        a history filter matches (and whether there were more than were looked
        at)."""
        tree = _parsed(where)
        scope: list[FilterNode] = [
            FilterCondition("now", "eq", "deleted"),
            FilterCondition("change", "eq", "delete"),
        ]
        if tree is not None:
            scope.insert(0, self._resolve(tree))
        batch = _as_uuid(batch_id, "batch") if batch_id else None
        things, truncated = self._audit.entities(
            AuditFilter(where=FilterGroup("and", scope), search=search, batch_id=batch),
            MAX_RESTORE_ALL,
        )
        ids = {
            t: {i for kind, i in things if kind == t}
            for t in ("dataset", "schema", "field")
        }
        collections = sorted(
            d.name for d in self._datasets.find(ids["dataset"]).values() if d.deleted_at
        )
        schemas = sorted(
            s.name
            for s in self._schema_svc.find(ids["schema"]).values()
            if s.deleted_at
        )
        fields = sorted(
            (schema_name, field.id)
            for field, schema_name in self._schema_svc.find_fields(
                ids["field"]
            ).values()
            if field.deleted_at
        )
        records = [str(i) for kind, i in things if kind == "record"]
        return collections, schemas, fields, records, truncated

    # ------------------------------------------------------------------
    # Reverting
    # ------------------------------------------------------------------

    def plan_revert(
        self, audit_id: uuid.UUID | str, fields: list[str] | None = None
    ) -> RevertPlanDTO:
        """What undoing this entry would do, without doing it.

        An `update` puts fields back (all it changed, or just `fields`); a
        `delete` restores the record; a `create` deletes it. A field edited
        since the entry is a conflict and is put back only when forced.
        Nothing but record changes can be reverted yet, since undoing a
        schema change could destroy data."""
        entry = self.get(audit_id)
        plan = RevertPlanDTO(
            audit_id=entry.id,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            kind=None,
        )
        if entry.entity_type != "record":
            plan.blocked = "Only changes to records can be reverted."
            return plan
        if entry.action not in ("update", "create", "delete"):
            plan.blocked = f"A '{entry.action}' entry can't be reverted."
            return plan

        found = self._records.labels([str(entry.entity_id)])
        record = found[0] if found else None
        if record is None:
            plan.blocked = "This record no longer exists."
            return plan
        deleted = record.deleted_at is not None

        if entry.action == "delete":
            plan.kind = "restore"
            if not deleted:
                plan.blocked = "This record is not deleted."
            else:
                restore = self._records.restore_plan(str(entry.entity_id))
                plan.blocked = restore.blocked_message
                plan.blocker = restore.blocked_by
        elif entry.action == "create":
            plan.kind = "delete"
            if deleted:
                plan.blocked = "This record is already deleted."
        else:
            plan.kind = "update"
            if deleted:
                plan.blocked = "This record is deleted. Restore it first."
            else:
                plan.fields = self._plan_fields(entry, record, fields)
        return plan

    def revert(
        self,
        audit_id: uuid.UUID | str,
        fields: list[str] | None = None,
        force: bool = False,
    ) -> RevertResultDTO:
        """Undo this entry, as `plan_revert` described. Conflicting fields are
        left alone unless `force`. Raises ValidationError when there is
        nothing to do or the record won't accept the old values."""
        plan = self.plan_revert(audit_id, fields)
        if plan.blocked:
            raise ValidationError(plan.blocked)
        if not plan.can_apply:
            raise ValidationError("Nothing to revert: every field is already as it was")
        record_id = str(plan.entity_id)
        result = RevertResultDTO(plan.audit_id, plan.entity_id, plan.kind or "")

        if plan.kind == "restore":
            self._records.restore(record_id)
        elif plan.kind == "delete":
            self._records.delete(record_id)
        else:
            put_back = [
                f
                for f in plan.fields
                if f.status == REVERT_APPLY or (force and f.status == REVERT_CONFLICT)
            ]
            if not put_back:
                raise ValidationError(
                    "Every field was edited since. Revert anyway to overwrite them."
                )
            # The record is replaced whole, so start from what it holds now.
            data = dict(self._records.get(record_id).data)
            for f in put_back:
                if f.target is None:
                    data.pop(f.field, None)
                else:
                    data[f.field] = f.target
            self._records.update(record_id, data)
            result.applied = [f.field for f in put_back]
        return result

    def _plan_fields(
        self, entry: AuditLogDTO, record: RecordDTO, wanted: list[str] | None
    ) -> list[RevertFieldDTO]:
        changes = {c["field"]: c for c in entry.changes}
        if wanted is not None:
            unknown = [name for name in wanted if name not in changes]
            if unknown:
                raise ValidationError(
                    f"This entry did not change: {', '.join(unknown)}"
                )
            changes = {name: changes[name] for name in wanted}
        shape = self._schema_svc.resolver()(record.schema_id)
        return [
            self._plan_field(change, record.data, shape) for change in changes.values()
        ]

    def _plan_field(
        self,
        change: dict[str, Any],
        current_data: dict[str, Any],
        shape: ResolvedSchema | None,
    ) -> RevertFieldDTO:
        name = change["field"]
        current = strip_derived(current_data.get(name))
        target = change["before"]
        plan = RevertFieldDTO(
            field=name,
            label=change["label"],
            dtype=change["dtype"],
            current=current,
            target=target,
            status=REVERT_APPLY,
        )
        if shape is None or name not in shape.by_name:
            plan.status = REVERT_SKIPPED
            plan.reason = "This field no longer exists."
        elif _blank(current) and _blank(target) or current == target:
            plan.status = REVERT_SAME
        elif missing := self._missing_files(target):
            plan.status = REVERT_SKIPPED
            plan.reason = (
                f"The file {missing} has been cleaned up and can't be put back."
            )
        elif current != change["after"] and not (
            _blank(current) and _blank(change["after"])
        ):
            plan.status = REVERT_CONFLICT
            plan.reason = "Edited since this change."
        return plan

    def _missing_files(self, value: Any) -> str | None:
        """The name of a file in `value` whose content is gone, if any."""
        refs = [value] if isinstance(value, dict) else value
        if not isinstance(refs, list):
            return None
        for ref in refs:
            if (
                isinstance(ref, dict)
                and ref.get("sha256")
                and not self._files.exists(ref["sha256"])
            ):
                return str(ref.get("filename") or ref["sha256"])
        return None


def _parsed(where: Any) -> FilterNode | None:
    """A history filter as given (JSON text or already decoded) checked and
    parsed; None when there is none. Anything malformed is a ValidationError."""
    if where is None or where == "":
        return None
    if isinstance(where, str):
        try:
            where = json.loads(where)
        except json.JSONDecodeError as e:
            raise ValidationError(f"History filter isn't valid JSON: {e}")
    return parse_audit_filter(where)


def _schema_id(snapshot: dict[str, Any] | None) -> uuid.UUID | None:
    try:
        return uuid.UUID((snapshot or {})["schema_id"])
    except (KeyError, ValueError, TypeError):
        return None


def _as_uuid(value: uuid.UUID | str, what: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise ValidationError(f"'{value}' is not a valid {what} id")


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _by_field_name(
    snapshot: dict[str, Any] | None, shape: ResolvedSchema | None
) -> dict[str, Any] | None:
    """A record snapshot with its values keyed by the field's name *now*.
    Entries store field ids, so a rename can't separate an entry from its
    field; an older entry that kept names is left as it is. An id that belongs
    to a deleted field is left as the id (a live field may since have taken
    its name) and `_diff` labels it."""
    if snapshot is None or shape is None or not snapshot.get("data"):
        return snapshot
    data = {shape.id_to_name.get(k, k): v for k, v in snapshot["data"].items()}
    return {**snapshot, "data": data}


def _blank(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}
