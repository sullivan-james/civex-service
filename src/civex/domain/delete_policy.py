"""When a delete needs more than a click to confirm.

One decision for every delete the app offers, made by the server so the
thresholds live in one place: a plain confirm (the delete is undoable from
Recently Deleted) for most deletes, typed confirmation only for a large one.
A delete's size counts everything that goes with it, so a cascade is judged by
its whole extent: a few records with many beneath them are large.
"""

from __future__ import annotations

from typing import Literal

DeleteTier = Literal["plain", "type"]

# More records than this, counting everything beneath the chosen ones, needs
# the confirmation typed.
TYPED_CONFIRM_ABOVE = 25


def delete_tier(total: int) -> DeleteTier:
    """The confirmation a delete taking `total` records in all asks for."""
    return "type" if total > TYPED_CONFIRM_ABOVE else "plain"
