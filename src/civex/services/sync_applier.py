"""Reproducing a change made elsewhere: the one place a snapshot or a delete
from another machine becomes rows here.

It writes state, not steps. An entry carries the thing as it was after the
change, so applying it twice, or after a later one, leaves the same result;
that is what lets sync repeat and recover. Deleting and restoring follow the
same cascades a person's do (a deleted schema takes its records), and a
permanent delete takes the thing's history with it, as it does when a person
makes it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from civex.domain.sync import SyncEntry
from civex.repositories.protocols import AuditRepository, SyncRepository


def stamp_of(entry: SyncEntry) -> datetime:
    """The moment a delete stamps what it deletes with. The deleting device
    uses one instant for the stamp and for its entries' time, so the entry's own
    time *is* the stamp: everything a bulk delete took shares it, a restore of
    the group finds them as one, and every device ends with the same dates."""
    parsed = datetime.fromisoformat(entry.timestamp)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class SyncApplier:
    def __init__(self, repo: SyncRepository, audit: AuditRepository) -> None:
        self._repo = repo
        self._audit = audit

    def head(self, kind: str, entity_id: uuid.UUID) -> dict[str, Any] | None:
        return self._repo.snapshot(kind, entity_id)

    def apply_state(
        self, kind: str, entity_id: uuid.UUID, state: dict[str, Any]
    ) -> None:
        """Make the thing exactly `state`. If it is deleted here and `state` is
        not, it is restored first, so what was deleted with it comes back too."""
        current = self._repo.snapshot(kind, entity_id)
        if current and current.get("deleted_at") and not state.get("deleted_at"):
            self._repo.restore(kind, entity_id)
        self._repo.apply_snapshot(kind, state)

    def apply_delete(self, kind: str, entity_id: uuid.UUID, stamp: datetime) -> None:
        if kind == "view":
            self._repo.delete_view(entity_id)
        else:
            self._repo.soft_delete(kind, entity_id, stamp)

    def apply_purge(self, kind: str, entity_id: uuid.UUID) -> None:
        if kind == "record":
            self._audit.forget_records([entity_id])
        elif kind == "schema":
            self._audit.forget_records_matching(f'"schema_id": "{entity_id}"')
        elif kind == "dataset":
            self._audit.forget_records_matching(f'"dataset_id": "{entity_id}"')
        self._repo.purge(kind, entity_id)

    def apply_entry(self, entry: SyncEntry) -> None:
        """Do what an entry from the authority says."""
        if entry.action in ("create", "update", "restore") and entry.new_data:
            self.apply_state(entry.entity_type, entry.entity_id, entry.new_data)
        elif entry.action == "delete":
            self.apply_delete(entry.entity_type, entry.entity_id, stamp_of(entry))
        elif entry.action == "purge":
            self.apply_purge(entry.entity_type, entry.entity_id)
