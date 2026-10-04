"""Where a collection's new files go, when it isn't the general write queue.

A placement names a collection's *home* volume. It only decides where content
that is not stored yet is written: a file whose content already exists on any
volume is reused where it lives, never copied again, so placement can't
duplicate data. `on_unavailable` says what happens when the home volume can't
take a write."""

from __future__ import annotations

# Fall back to the general write queue (the default: an unplugged drive should
# not make uploads fail, and a split collection is visible and repairable).
PLACEMENT_SPILL = "spill"
# Fail the upload instead of writing the collection's data anywhere else.
PLACEMENT_FAIL = "fail"

PLACEMENT_POLICIES = (PLACEMENT_SPILL, PLACEMENT_FAIL)
