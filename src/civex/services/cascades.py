"""What deleting or restoring a schema or collection does to its records, put in
history record by record.

Deleting a schema or collection stamps its live records in one statement, and
restoring it brings back those stamped with its moment. Those records changed,
so history says so, one entry each (in the same action, so they travel with the
schema's or collection's own entry and are taken with it, or not). Without
them, each copy of a project would work out the cascade from what it held, and
copies that held different things, or took changes in another order, would end
with records deleted on one and live on another.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from civex.repositories.protocols import AuditRepository, RecordRepository

States = dict[uuid.UUID, datetime | None]


def record_states(
    records: RecordRepository,
    *,
    schema_id: uuid.UUID | None = None,
    dataset_id: uuid.UUID | None = None,
) -> States:
    """When each record of a schema or collection was deleted (None: live)."""
    return records.deleted_states(schema_id=schema_id, dataset_id=dataset_id)


def changed_records(
    records: RecordRepository,
    before: States,
    *,
    schema_id: uuid.UUID | None = None,
    dataset_id: uuid.UUID | None = None,
) -> list[tuple[uuid.UUID, datetime | None, datetime | None]]:
    """(record, deleted before, deleted after) for each record whose deleted
    state is not what it was."""
    after = records.deleted_states(schema_id=schema_id, dataset_id=dataset_id)
    return [
        (rid, was, after.get(rid))
        for rid, was in before.items()
        if after.get(rid) != was
    ]


def log_cascade(
    records: RecordRepository,
    audit: AuditRepository | None,
    before: States,
    *,
    schema_id: uuid.UUID | None = None,
    dataset_id: uuid.UUID | None = None,
) -> None:
    """History for each record the delete or restore just made changed."""
    if audit is None:
        return
    changed = changed_records(
        records, before, schema_id=schema_id, dataset_id=dataset_id
    )
    if not changed:
        return
    now = {r.id: r.to_dict() for r in records.list_by_ids([c[0] for c in changed])}
    for rid, was, became in changed:
        snapshot = now.get(rid)
        if snapshot is None:
            continue
        if became is not None:  # deleted with it
            audit.log_change(
                "delete",
                "record",
                rid,
                {**snapshot, "deleted_at": None},
                None,
                timestamp=became,
            )
        else:  # back with it
            audit.log_change(
                "restore",
                "record",
                rid,
                {**snapshot, "deleted_at": was.isoformat() if was else None},
                snapshot,
            )
