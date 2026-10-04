"""What an audit entry changed, as a list of before/after pairs.

Pure: it reads the `old_data` / `new_data` snapshots an entry carries and
nothing else. It is the one place a history entry is turned into a diff, so
the web UI, the CLI and any script see the same changes.

A record's snapshot holds its values under `data`, keyed by field name. Every
other entity (schema, field, collection, view) is a flat dict of attributes.
Anything that is bookkeeping rather than a change (ids, timestamps) is left
out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from civex.domain.dtos import DERIVED_FILE_KEYS

# Attributes that say nothing about what was edited.
_IGNORED_ATTRIBUTES = frozenset({"id", "created_at", "deleted_at", "schema_id"})


@dataclass
class Change:
    """One field (or attribute) whose value differs between two snapshots.

    `before` / `after` are None when the value was absent on that side, so a
    create is all-None befores and a delete all-None afters. `label` and
    `dtype` are not known here; whoever has the schema fills them in."""

    field: str
    before: Any = None
    after: Any = None
    label: str | None = None
    dtype: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "label": self.label,
            "dtype": self.dtype,
            "before": self.before,
            "after": self.after,
        }


def diff_entry(
    entity_type: str,
    action: str,
    old: dict[str, Any] | None,
    new: dict[str, Any] | None,
) -> list[Change]:
    """The changes `action` made to an `entity_type`, from its two snapshots.

    A restore changes nothing but the deleted marker, so it has no changes.
    A delete or purge reports what was lost, as values going to None."""
    if action == "restore":
        return []
    if action in ("delete", "purge"):
        new = None
    if entity_type == "record":
        before, after = _record_values(old), _record_values(new)
    else:
        before, after = _attributes(old), _attributes(new)
    changes = []
    for key in sorted(set(before) | set(after)):
        was, now = strip_derived(before.get(key)), strip_derived(after.get(key))
        if was != now:
            changes.append(Change(key, was, now))
    return changes


def _record_values(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """A record snapshot's values by field name; blanks count as absent."""
    data = (snapshot or {}).get("data") or {}
    return {k: v for k, v in data.items() if not _blank(v)}


def _attributes(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    return {
        k: v
        for k, v in (snapshot or {}).items()
        if k not in _IGNORED_ATTRIBUTES and not _blank(v)
    }


def _blank(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def strip_derived(value: Any) -> Any:
    """`value` without the keys the server adds to a file reference on a read,
    so a file that was merely echoed back doesn't look edited."""
    if isinstance(value, dict):
        return {
            k: strip_derived(v) for k, v in value.items() if k not in DERIVED_FILE_KEYS
        }
    if isinstance(value, list):
        return [strip_derived(v) for v in value]
    return value


# What permanently deleting a record leaves in history: one entry saying that it
# happened, which record, and when, and nothing it held. `TOMBSTONE_KEY` is
# matched as the JSON serialiser writes it (`"tombstone": true`).
TOMBSTONE_KEY = "tombstone"
_TOMBSTONE_KEYS = (
    "id",
    "dataset_id",
    "schema_id",
    "parent_record_id",
    "created_at",
    "deleted_at",
)


def tombstone(snapshot: dict[str, Any]) -> dict[str, Any]:
    """The part of a record's snapshot that survives its permanent deletion:
    who it was and where it sat, never its values."""
    kept = {k: snapshot[k] for k in _TOMBSTONE_KEYS if k in snapshot}
    return {**kept, TOMBSTONE_KEY: True}
