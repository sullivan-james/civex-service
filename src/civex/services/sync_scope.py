"""What of the authority's feed a device may be sent.

A device acts for a person whose `Permissions` may leave some collections
unread (`ReadScope`). It must never be sent a hidden collection's data, in
any form, so each change the feed would send is looked at before it goes:

- a change to a record is judged by the collection it was in *and* the one it
  is in after. Both seen, or neither: as it is, or not at all. A record moved
  out of sight is sent as its removal (the device never learns where it went);
  one moved into sight is sent as its creation, in full (the device never had
  it), with its notes. Nothing else of what was hidden before travels.
- a note goes with its record's collection, a collection's own changes only
  when it is seen. Releases are never synced. Kinds and fields, views and the Analytics page are
  project-wide, as everywhere in civex.

Pure of storage: the lookups are handed in.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Callable
from typing import Any

from civex.domain.audit_diff import identity
from civex.domain.permissions import ReadScope, entry_collections
from civex.domain.sync import SyncEntry


def _id(value: Any) -> uuid.UUID | None:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def collections_of(entry: SyncEntry) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """The collection a record change started in and the one it ended in."""
    before, after = entry_collections(entry)
    return _id(before), _id(after)


# Kinds that belong to no collection: shared by everyone who reads the project.
# Anything not named here (or handled above) is not sent to a limited device.
_PROJECT_WIDE = frozenset({"schema", "field", "view", "dashboard"})


class FeedShaper:
    """Turns a page of the feed into the page this caller may see."""

    def __init__(
        self,
        scope: ReadScope,
        record_dataset: Callable[[uuid.UUID], uuid.UUID | None],
        record_snapshot: Callable[[uuid.UUID], dict[str, Any] | None],
        note_snapshots: Callable[[uuid.UUID], list[dict[str, Any]]],
        collection_trails: Callable[
            [set[uuid.UUID]],
            dict[uuid.UUID, list[tuple[int, uuid.UUID | None, uuid.UUID | None]]],
        ],
        legacy_through: int = 0,
    ) -> None:
        self._scope = scope
        # Entries numbered up to this were stored before they were stamped with
        # where the authority really had the record: what they say of the
        # collection is what a device claimed. They are trusted only while the
        # record is, now, somewhere the caller may read.
        self._legacy = legacy_through
        self._told: set[uuid.UUID] = set()  # records already sent as gone
        # Where each record went, change by change: `(feed number, the collection
        # it was in before when the change says, the collection after)`; a first
        # entry at 0 says where its first change found it. Many records at once:
        # one lookup per page.
        self._trails_of = collection_trails
        self._trails: dict[
            uuid.UUID, list[tuple[int, uuid.UUID | None, uuid.UUID | None]]
        ] = {}
        self._dataset_of = record_dataset
        self._snapshot = record_snapshot
        self._notes = note_snapshots

    def shape(self, entries: list[SyncEntry]) -> list[SyncEntry]:
        out: list[SyncEntry] = []
        for group in self.shape_each(entries):
            out.extend(group)
        return out

    def shape_each(self, entries: list[SyncEntry]) -> list[list[SyncEntry]]:
        """What each entry becomes (nothing, itself, or several), in order, so a
        caller can stop between two of them."""
        self._load_trails(entries)
        return [self._one(entry) for entry in entries]

    def _one(self, entry: SyncEntry) -> list[SyncEntry]:
        kind = entry.entity_type
        if kind == "record":
            return self._record(entry)
        if kind == "note":
            record = _id((entry.new_data or entry.old_data or {}).get("record_id"))
            where = self._collection_at(record, entry.hub_seq) if record else None
            if not (where and self._scope.sees(where)):
                return []
            if self._old(entry) and not (record and self._now_visible(record)):
                return []
            return [entry]
        if kind == "dataset":
            return [entry] if self._scope.sees(entry.entity_id) else []
        if kind in _PROJECT_WIDE:
            return [entry]
        return []  # a kind this does not know holds nothing it can place

    def _old(self, entry: SyncEntry) -> bool:
        return entry.hub_seq is not None and entry.hub_seq <= self._legacy

    def _now_visible(self, record: uuid.UUID) -> bool:
        where = self._dataset_of(record)
        return where is not None and self._scope.sees(where)

    def _collection_at(self, record: uuid.UUID, seq: int | None) -> uuid.UUID | None:
        """The collection a record was in when the authority numbered `seq`: a
        note is judged by it, not by where the record is now, or what was said
        about a record while it was out of sight would follow it in."""
        if record not in self._trails:
            self._load_trails_of({record})
        trail = self._trails.get(record, [])
        if seq is None or seq <= self._legacy:
            where: uuid.UUID | None = None
            for at, _before, after in trail:
                if seq is not None and at > seq:
                    break
                where = after or where
            return where or self._dataset_of(record)
        # A note made since the upgrade is placed only by changes made since it:
        # what is stored from before says what a device claimed.
        newer = [point for point in trail if point[0] > self._legacy and point[0] > 0]
        where = None
        for at, _before, after in newer:
            if at > seq:
                break
            where = after or where
        if where is not None:
            return where
        # No change since the upgrade says where it was by then. The first later
        # change that says where the record was before it, says it; failing that
        # the record is where it is now, unless a later change moved it.
        here = self._dataset_of(record)
        later = [point for point in newer if point[0] > seq]
        for _at, before, _after in later:
            if before:
                return before
        if any(after and after != here for _at, _before, after in later):
            return None
        return here

    def _load_trails(self, entries: list[SyncEntry]) -> None:
        """The notes of this page are judged by where their records were: all
        those records' trails are read in one lookup, not one each."""
        wanted: set[uuid.UUID] = set()
        for entry in entries:
            if entry.entity_type == "note":
                record = _id((entry.new_data or entry.old_data or {}).get("record_id"))
                if record is not None and record not in self._trails:
                    wanted.add(record)
        if wanted:
            self._load_trails_of(wanted)

    def _load_trails_of(self, records: set[uuid.UUID]) -> None:
        found = self._trails_of(records)
        for record in records:
            self._trails[record] = found.get(record, [])

    def _record(self, entry: SyncEntry) -> list[SyncEntry]:
        before, after = collections_of(entry)
        if before is None or after is None:
            return []  # it cannot be placed, so it cannot be shown
        if (
            self._old(entry)
            and entry.action != "purge"
            and not self._now_visible(entry.entity_id)
        ):
            # Stored as claimed, and the record is out of sight now. A device
            # that still holds it (it lags behind the upgrade) is told it is
            # gone if the entry says it was somewhere that device may read.
            if self._scope.sees(before):
                if entry.entity_id in self._told:
                    return []  # once is enough, however many old entries say it
                self._told.add(entry.entity_id)
                return [
                    dataclasses.replace(
                        entry,
                        id=uuid.uuid5(entry.id, "purge"),
                        action="purge",
                        old_data=identity(entry.old_data or entry.new_data)
                        | {"dataset_id": str(before)},
                        new_data=None,
                        delta=None,
                        superseded=False,
                    )
                ]
            return []
        saw, sees = self._scope.sees(before), self._scope.sees(after)
        if saw and sees:
            return [entry]
        if not saw and not sees:
            return []
        if saw:
            # Gone from sight: it is removed here, and nothing says where to.
            return [
                dataclasses.replace(
                    entry,
                    id=uuid.uuid5(entry.id, "purge"),
                    action="purge",
                    old_data=identity(entry.old_data or entry.new_data)
                    | {"dataset_id": str(before)},
                    new_data=None,
                    delta=None,
                    superseded=False,
                )
            ]
        # Come into sight: the device has never held it, so it gets it whole.
        whole = self._snapshot(entry.entity_id)
        there = _id(whole.get("dataset_id")) if whole else None
        if there is None or not self._scope.sees(there):
            return []  # it has moved on since, and a later change says so
        made = dataclasses.replace(
            entry,
            id=uuid.uuid5(entry.id, "create"),
            action="create",
            old_data=None,
            new_data=whole,
            delta=None,
            superseded=False,
        )
        notes = [
            dataclasses.replace(
                entry,
                id=uuid.uuid5(entry.id, str(note["id"])),
                action="create",
                entity_type="note",
                entity_id=uuid.UUID(str(note["id"])),
                old_data=None,
                new_data=note,
                delta=None,
                superseded=False,
            )
            for note in self._notes(entry.entity_id)
        ]
        return [made, *notes]
