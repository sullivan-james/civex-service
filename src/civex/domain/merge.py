"""Three-way merge of an entity's snapshot: how sync settles concurrent edits.

An edit arrives as `incoming`, made on top of `base` (the state its author last
saw); `head` is what the authority holds now. Field by field:

- the edit did not touch the field            -> keep head;
- head still has what the author started from -> take the edit;
- head already has the edited value           -> nothing to do;
- head changed it to something else           -> **conflict**: head stays, and
  the edit's value is kept aside for a person to review.

A record's values (`data`, keyed by field id) are merged per field; every other
attribute is one value, however structured. Pure: no database, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_MISSING: Any = object()

# Bookkeeping, not edits: the caller decides these (a delete or restore is a
# lifecycle event, not a field change).
LIFECYCLE_KEYS = frozenset({"id", "created_at", "updated_at", "deleted_at"})
# Attributes that are a dict of independent values, merged one value at a time.
NESTED_KEYS = frozenset({"data"})
# Derived from other attributes, so never merged on their own.
DERIVED_KEYS = frozenset({"schemas", "record_count"})


@dataclass
class FieldConflict:
    """One value both sides changed. `field` is the attribute, or for a record
    `data.<field id>`."""

    field: str
    base: Any
    head: Any
    incoming: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "base": _out(self.base),
            "head": _out(self.head),
            "incoming": _out(self.incoming),
        }


@dataclass
class MergeResult:
    state: dict[str, Any]  # the merged snapshot
    conflicts: list[FieldConflict] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)  # what differs from head now


def merge(
    base: dict[str, Any] | None, head: dict[str, Any], incoming: dict[str, Any]
) -> MergeResult:
    """Merge `incoming` (made on `base`) onto `head`. `base` None means the edit
    has no known starting point, as for a create: every value it sets that head
    already holds differently is a conflict."""
    base = base or {}
    state = dict(head)
    conflicts: list[FieldConflict] = []
    changed: list[str] = []

    keys = (set(base) | set(head) | set(incoming)) - LIFECYCLE_KEYS - DERIVED_KEYS
    for key in sorted(keys):
        if key in NESTED_KEYS and _is_mapping(base, head, incoming, key):
            merged, nested_conflicts, nested_changed = _merge_values(
                base.get(key) or {}, head.get(key) or {}, incoming.get(key) or {}, key
            )
            conflicts += nested_conflicts
            if nested_changed:
                state[key] = merged
                changed += nested_changed
            continue
        outcome = _decide(
            base.get(key, _MISSING),
            head.get(key, _MISSING),
            incoming.get(key, _MISSING),
        )
        if outcome is _KEEP:
            continue
        if outcome is _CONFLICT:
            conflicts.append(
                FieldConflict(
                    key,
                    _none(base.get(key, _MISSING)),
                    _none(head.get(key, _MISSING)),
                    _none(incoming.get(key, _MISSING)),
                )
            )
            continue
        _put(state, key, outcome)
        changed.append(key)
    return MergeResult(state, conflicts, changed)


def _merge_values(
    base: dict[str, Any], head: dict[str, Any], incoming: dict[str, Any], prefix: str
) -> tuple[dict[str, Any], list[FieldConflict], list[str]]:
    merged = dict(head)
    conflicts: list[FieldConflict] = []
    changed: list[str] = []
    for key in sorted(set(base) | set(head) | set(incoming)):
        outcome = _decide(
            base.get(key, _MISSING),
            head.get(key, _MISSING),
            incoming.get(key, _MISSING),
        )
        if outcome is _KEEP:
            continue
        path = f"{prefix}.{key}"
        if outcome is _CONFLICT:
            conflicts.append(
                FieldConflict(
                    path,
                    _none(base.get(key, _MISSING)),
                    _none(head.get(key, _MISSING)),
                    _none(incoming.get(key, _MISSING)),
                )
            )
            continue
        _put(merged, key, outcome)
        changed.append(path)
    return merged, conflicts, changed


_KEEP = object()
_CONFLICT = object()


def _decide(base: Any, head: Any, incoming: Any) -> Any:
    """What one value becomes: `_KEEP` (leave head), `_CONFLICT`, or the value
    to take (`_MISSING` meaning the edit removed it)."""
    if _same(incoming, base):  # the edit did not touch it
        return _KEEP
    if _same(head, incoming):  # already there
        return _KEEP
    if _same(head, base):  # head untouched since the edit began
        return incoming
    return _CONFLICT


def _put(target: dict[str, Any], key: str, value: Any) -> None:
    if value is _MISSING:
        target.pop(key, None)
    else:
        target[key] = value


def _is_mapping(*snapshots: Any) -> bool:
    *dicts, key = snapshots
    return all(isinstance(d.get(key) or {}, dict) for d in dicts)


def _same(a: Any, b: Any) -> bool:
    if a is _MISSING or b is _MISSING:
        return a is b
    return a == b  # 1 == 1.0 and key order is irrelevant, as in JSON


def _none(value: Any) -> Any:
    return None if value is _MISSING else value


def _out(value: Any) -> Any:
    return value
