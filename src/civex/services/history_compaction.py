"""Converting history written before deltas (v1.2.0 and earlier) to deltas.

An edit used to be stored as two whole copies of the thing; it is now stored as
what changed (`audit_diff.stored_form`). Entries already written are converted
here, a batch at a time, after the project is opened: never in a migration,
which runs when a project is first opened and would make that hang on a large
history.

Each entry is checked before it is rewritten: what it says it changed must
read the same afterwards (`diff_entry` of both forms). One that wouldn't is
marked checked and kept whole (`format` 3), never touched again. Nothing is
remembered between batches: what is left is simply what is still whole, so
stopping at any point loses nothing and the next run carries on.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from civex.domain.audit_diff import diff_entry, entry_snapshots, stored_form
from civex.repositories.local.db_space import DbSpace, LocalDbSpace
from civex.repositories.protocols import AuditRepository

DELTA = 2
KEPT_WHOLE = 3
BATCH = 500


@dataclass
class CompactionStep:
    converted: int  # stored as deltas in this step
    kept: int  # checked and kept whole in this step
    remaining: int  # still to look at after it


class HistoryCompactionService:
    def __init__(self, audit: AuditRepository, space: LocalDbSpace) -> None:
        self._audit = audit
        self._space = space
        # Where this run has got to (by id). In memory only: what is left is
        # what is still whole, so a new run simply starts at the beginning.
        self._after: uuid.UUID | None = None

    def space(self) -> DbSpace | None:
        """The database file and the room inside it a reclaim would give back
        (None where the database manages its own space)."""
        return self._space.space()

    def reclaim(self) -> None:
        """Give the free room back (SQLite's VACUUM). Never automatic: it needs
        about the file's size in free disk while it runs."""
        self._space.reclaim()

    def remaining(self) -> int:
        return self._audit.count_whole_edits()

    def step(self, limit: int = BATCH) -> CompactionStep:
        """Convert up to `limit` entries (the caller commits)."""
        converted = kept = 0
        batch = self._audit.whole_edits(limit, self._after)
        if batch:
            self._after = batch[-1].id
        for entry in batch:
            old_data, new_data, delta, form = stored_form(
                entry.old_data, entry.new_data
            )
            before = diff_entry(
                entry.entity_type, entry.action, entry.old_data, entry.new_data
            )
            after = diff_entry(
                entry.entity_type,
                entry.action,
                *entry_snapshots(old_data, new_data, delta),
            )
            if delta is not None and form == DELTA and after == before:
                self._audit.store_as_delta(entry.id, new_data, delta, DELTA)
                converted += 1
            else:
                self._audit.store_as_delta(entry.id, None, None, KEPT_WHOLE)
                kept += 1
        return CompactionStep(converted, kept, self.remaining())
