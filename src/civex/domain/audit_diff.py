"""What an audit entry changed, as a list of before/after pairs.

Pure: it reads the `old_data` / `new_data` snapshots an entry carries and
nothing else. It is the one place a history entry is turned into a diff, so
the web UI, the CLI and any script see the same changes.

A record's snapshot holds its values under `data`, keyed by field id (older
entries by name; `AuditService` turns either into current names before it asks
for a diff). Every other entity (schema, field, collection, view) is a flat dict of attributes.
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
    # Set when the field has since been deleted: {status: deleted | gone, id,
    # schema_name, deleted_at}. `deleted` fields can be restored; `gone` ones
    # (permanently deleted) can't.
    deleted: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "label": self.label,
            "dtype": self.dtype,
            "before": self.before,
            "after": self.after,
            "deleted": self.deleted,
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


# -- Entries that store only what changed (`format` 2) ---------------------------
#
# A history entry is either two whole snapshots (`format` 1: `old_data` and
# `new_data`) or a `delta`: for each value that changed, what it was and what it
# became, plus the thing's identity in `new_data`. `make_delta` turns two
# snapshots into a delta, `apply_delta` puts one onto a snapshot, and
# `entry_snapshots` reads either kind back as two snapshots holding (for a
# delta) just what changed. Everything that reads an entry goes through
# `entry_snapshots`, so nothing has to know which kind it is reading.

# A record's values are one value each, under `data.<field id>`; every other
# attribute is one value however it is structured (as `merge` treats them).
_NESTED = "data"
# What a delta entry keeps of the thing, whatever changed: enough to say what it
# was and where it sits (a title, a collection, a parent, a schema) and to be
# found by the history filters that look for an id inside an entry.
IDENTITY_KEYS = frozenset(
    {
        "id",
        "name",
        "label",
        "schema_id",
        "dataset_id",
        "parent_id",
        "parent_record_id",
        "dtype",  # a field's: how its values (and restrictions) read
        # Whether it was deleted when changed: an edit to something live that
        # meets a delete elsewhere keeps it; one made to something already
        # deleted (a template rewritten in a deleted schema) must not revive it.
        "deleted_at",
    }
)
BEFORE, AFTER = "before", "after"


def identity(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """The part of a snapshot a delta entry keeps (see `IDENTITY_KEYS`)."""
    return {k: v for k, v in (snapshot or {}).items() if k in IDENTITY_KEYS}


def make_delta(
    old: dict[str, Any] | None, new: dict[str, Any] | None
) -> dict[str, dict[str, Any]]:
    """What differs between two snapshots of a thing: `{path: {"before": x,
    "after": y}}`, a side left out where the value is absent on it. Complete:
    `apply_delta(old, make_delta(old, new)) == new`. Bookkeeping (dates) is
    included, since an entry must reproduce the thing exactly; it is the diff
    (`diff_entry`) that leaves bookkeeping out, not the delta."""
    old, new = old or {}, new or {}
    delta: dict[str, dict[str, Any]] = {}
    for key in sorted(set(old) | set(new)):
        was, now = old.get(key, _ABSENT), new.get(key, _ABSENT)
        if key == _NESTED and _mapping_or_absent(was) and _mapping_or_absent(now):
            inner_old = {} if was is _ABSENT else was or {}
            inner_new = {} if now is _ABSENT else now or {}
            for sub in sorted(set(inner_old) | set(inner_new)):
                _note(
                    delta,
                    f"{_NESTED}.{sub}",
                    inner_old.get(sub, _ABSENT),
                    inner_new.get(sub, _ABSENT),
                )
            if (was is _ABSENT) != (now is _ABSENT) or (was is None) != (now is None):
                # `data` itself appeared, went or became null: say so, or the
                # values alone would put back a `{}` that wasn't there.
                _note(delta, _NESTED, _shape(was), _shape(now))
            continue
        _note(delta, key, was, now)
    return delta


def apply_delta(
    snapshot: dict[str, Any] | None, delta: dict[str, dict[str, Any]], side: str = AFTER
) -> dict[str, Any]:
    """`snapshot` with each value in `delta` set to its `side` (`"after"` to go
    forward, `"before"` to go back), or removed where that side is absent."""
    out = dict(snapshot or {})
    if isinstance(out.get(_NESTED), dict):
        out[_NESTED] = dict(out[_NESTED])
    shape = delta.get(_NESTED)
    if shape is not None:
        _set(out, _NESTED, _from_shape(shape, side))
    for path, change in delta.items():
        if path == _NESTED:
            continue
        top, sub = _split(path)
        if sub is None:
            _set(out, top, change.get(side, _ABSENT) if side in change else _ABSENT)
            continue
        inner = out.get(top)
        if not isinstance(inner, dict):
            if side not in change:
                continue
            inner = out[top] = {}
        _set(inner, sub, change[side] if side in change else _ABSENT)
    return out


def entry_snapshots(
    old_data: dict[str, Any] | None,
    new_data: dict[str, Any] | None,
    delta: dict[str, dict[str, Any]] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """An entry's two sides, however it was stored. A whole-snapshot entry is
    returned as it is; a delta entry as its identity plus, on each side, the
    values that changed (nothing that stayed the same is known, and a diff
    doesn't need it)."""
    if delta is None:
        return old_data, new_data
    who = identity(new_data)
    return apply_delta(who, delta, BEFORE), apply_delta(who, delta, AFTER)


_ABSENT: Any = object()


def _note(delta: dict[str, dict[str, Any]], path: str, was: Any, now: Any) -> None:
    if was is not _ABSENT and now is not _ABSENT and was == now:
        if type(was) is type(now):
            return
    elif was is _ABSENT and now is _ABSENT:
        return
    change: dict[str, Any] = {}
    if was is not _ABSENT:
        change[BEFORE] = was
    if now is not _ABSENT:
        change[AFTER] = now
    delta[path] = change


def _mapping_or_absent(value: Any) -> bool:
    return value is _ABSENT or value is None or isinstance(value, dict)


def _shape(value: Any) -> Any:
    """How `data` itself stands, apart from its values: absent, null or a dict
    (recorded as `{}`; the values are their own paths)."""
    if value is _ABSENT or value is None:
        return value
    return {}


def _from_shape(change: dict[str, Any], side: str) -> Any:
    if side not in change:
        return _ABSENT
    return None if change[side] is None else {}


def _split(path: str) -> tuple[str, str | None]:
    if path.startswith(_NESTED + "."):
        return _NESTED, path[len(_NESTED) + 1 :]
    return path, None


def _set(target: dict[str, Any], key: str, value: Any) -> None:
    if value is _ABSENT:
        target.pop(key, None)
    else:
        target[key] = value


def stored_form(
    old: dict[str, Any] | None, new: dict[str, Any] | None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, int]:
    """How a change from `old` to `new` is stored: `(old_data, new_data, delta,
    format)`. A change between two states (an edit, a restore) keeps only what
    changed, plus the thing's identity; a create keeps the thing as made and a
    delete the thing as it was (one copy, so what was lost can be shown), since
    there is no other side to take a difference from. The one rule every writer
    of history follows."""
    if old is None or new is None:
        return old, new, None, 1
    return None, identity(new), make_delta(old, new), 2
