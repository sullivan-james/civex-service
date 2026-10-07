"""A collection's home drive, and the one rule for copies.

A placement names a collection's *home* volume: its new files are written
there, and **a home keeps a copy of every file its collection uses**. A file
two collections use, each homed on its own drive, is on both drives, so each
collection is whole on its own drive. Content is otherwise stored once: a file
already stored is reused where it is, and a drive that is no collection's home
never gets a second copy. `on_unavailable` says what happens when the home
volume can't take a write."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping

# Fall back to the general write queue (the default: an unplugged drive should
# not make uploads fail, and a split collection is visible and repairable).
PLACEMENT_SPILL = "spill"
# Fail the upload instead of writing the collection's data anywhere else.
PLACEMENT_FAIL = "fail"

PLACEMENT_POLICIES = (PLACEMENT_SPILL, PLACEMENT_FAIL)

# What getting a file onto a drive does (`file_step`).
STEP_THERE = "there"  # a copy is on the drive already
STEP_MOVE = "move"  # moved: the copy it came from goes
STEP_COPY = "copy"  # copied: the copy it came from stays, on a home that needs it
STEP_NOWHERE = "nowhere"  # no copy is recorded here


def homes_keeping(collections: Iterable[str], homes: Mapping[str, str]) -> set[str]:
    """The drives that keep a copy of a file these collections use: their
    homes (`homes`: collection id -> home drive)."""
    return {homes[c] for c in collections if c in homes}


def file_step(
    copies: Collection[str], targets: Collection[str], keeping: Collection[str]
) -> tuple[str, str | None]:
    """How a file gets onto one of `targets`, from its `copies` (the drives
    holding it, the one to copy from first): (step, the drive it comes from).
    Copied rather than moved when that drive is a home that keeps it
    (`keeping`, from `homes_keeping`). The one rule behind a move's preview and
    the move itself."""
    if any(v in targets for v in copies):
        return STEP_THERE, None
    if not copies:
        return STEP_NOWHERE, None
    source = next(iter(copies))
    return (STEP_COPY if source in keeping else STEP_MOVE), source
