"""Finding record-to-record references inside a record's `data`."""

from __future__ import annotations

import functools
import uuid
from typing import Any


def _as_uuid(value: Any) -> uuid.UUID | None:
    # (`uuid.UUID` takes 32 hex digits with hyphens, braces or `urn:uuid:`
    # around them: nothing shorter than 32 or longer than 45 characters is one,
    # and the length check is far cheaper than the exception.)
    if not isinstance(value, str) or not 32 <= len(value) <= 45:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


# A record's keys are its field ids: a few, the same on every record.
_field_id = functools.lru_cache(maxsize=4096)(_as_uuid)


def collect_record_refs(data: Any) -> set[tuple[uuid.UUID, uuid.UUID]]:
    """Every (field id, target record id) a record's stored `data` holds.

    Stored data is keyed by field UUID (see RecordService._names_to_ids), and a
    `reference` holds one id string, a `reference_list` a list of them -- so a
    top-level key that is a UUID, holding a UUID string or a list of them, is
    a reference without looking up the field's type. A text field that merely
    holds a UUID shows up too; readers join `fields` on dtype to tell them
    apart."""
    refs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    if not isinstance(data, dict):
        return refs
    for key, value in data.items():
        field_id = _field_id(key) if isinstance(key, str) else None
        if field_id is None:
            continue
        for item in value if isinstance(value, list) else [value]:
            target = _as_uuid(item)
            if target is not None:
                refs.add((field_id, target))
    return refs
