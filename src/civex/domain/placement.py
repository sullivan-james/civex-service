"""A collection's home drive, and the one rule for what a move does to a file.

A placement names a collection's *home* volume: its new files are written
there. `on_unavailable` says what happens when the home volume can't take a
write.

A file may be stored on several drives, and each record's file points at
exactly one of those copies (`file_references.volume`, a `Pointer` here). A
move changes pointers: the ones it covers (`Scope`) are pointed at the target,
the file is copied there if it isn't already, and a copy the move leaves with
nothing pointing at it is removed. So a copy other records still point at
stays (the file is copied, not moved), and moving onto a drive that already
has the content copies nothing (de-duplication).

A release owns the files it cites too, pointing at the copy its records used
when it was made. A release never holds a copy in place by itself during a
move: its pointer goes with the records it shares the copy with once every
record pointing at that copy is moving (`moving`), and stays with those that
stay otherwise. Emptying a drive takes every pointer at it, releases'
included."""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable
from dataclasses import dataclass

# Fall back to the general write queue (the default: an unplugged drive should
# not make uploads fail, and a split collection is visible and repairable).
PLACEMENT_SPILL = "spill"
# Fail the upload instead of writing the collection's data anywhere else.
PLACEMENT_FAIL = "fail"

PLACEMENT_POLICIES = (PLACEMENT_SPILL, PLACEMENT_FAIL)

# What getting a file onto a drive does (`file_step`).
STEP_THERE = "there"  # a copy is on the drive already
STEP_MOVE = "move"  # moved: the copy it came from goes
STEP_COPY = "copy"  # copied: the copy it came from stays, others point at it
STEP_NOWHERE = "nowhere"  # no copy is recorded here


@dataclass(frozen=True)
class Pointer:
    """One row of `file_references`: which copy (`volume`, None when there is
    none here) an owner (a record, live or deleted, a workflow run or a
    release) uses."""

    id: uuid.UUID
    sha256: str
    volume: str | None
    record_id: uuid.UUID | None
    collection_id: str | None
    live: bool
    release_id: uuid.UUID | None = None


@dataclass(frozen=True)
class Scope:
    """Which pointers a move covers: those on drives being emptied (`drives`),
    or the live records of some collections (`collections`), or some records
    (`records`) and releases (`releases`), or, with none of those, every owner
    of the files."""

    drives: frozenset[str] = frozenset()
    collections: frozenset[str] = frozenset()
    records: frozenset[str] = frozenset()
    releases: frozenset[str] = frozenset()

    def covers(self, p: Pointer) -> bool:
        if self.drives:
            return p.volume in self.drives
        if not (self.collections or self.records or self.releases):
            return True
        if p.release_id is not None:
            return str(p.release_id) in self.releases
        if self.collections:
            return p.live and p.collection_id in self.collections
        return p.record_id is not None and str(p.record_id) in self.records


def moving(pointers: Iterable[Pointer], scope: Scope) -> list[Pointer]:
    """The pointers (of one file) a move points at its target: those the scope
    covers, and a release's pointer at a copy that every other owner pointing
    at it is leaving (so the release follows its records, and never keeps a
    copy behind by itself). A release's pointer at a copy some record stays
    on stays too."""
    owners = list(pointers)
    covered = [p for p in owners if scope.covers(p)]
    ids = {p.id for p in covered}
    left = {p.volume for p in owners if p.release_id is None and p.id not in ids}
    vacated = {p.volume for p in covered if p.volume} - left
    return covered + [
        p
        for p in owners
        if p.release_id is not None and p.id not in ids and p.volume in vacated
    ]


def keeping(pointers: Iterable[Pointer], scope: Scope) -> set[str]:
    """The drives whose copy must stay: those an owner the move doesn't move
    (`moving`) points at. A deleted record counts (it can be restored)."""
    owners = list(pointers)
    moved = {p.id for p in moving(owners, scope)}
    return {p.volume for p in owners if p.volume and p.id not in moved}


def file_step(
    copies: Collection[str], targets: Collection[str], keeping: Collection[str]
) -> tuple[str, str | None]:
    """How a file gets onto one of `targets`, from its `copies` (the drives
    holding it, the one to copy from first): (step, the drive it comes from).
    Copied rather than moved when other owners point at that copy
    (`keeping`). The one rule behind a move's preview and the move itself."""
    if any(v in targets for v in copies):
        return STEP_THERE, None
    if not copies:
        return STEP_NOWHERE, None
    source = next(iter(copies))
    return (STEP_COPY if source in keeping else STEP_MOVE), source
