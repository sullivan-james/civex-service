"""Opaque cursors for keyset paging of record lists.

A cursor carries the sort-key values of the last record of a page (every
ORDER BY term of the listing, ending in created_at and id) plus the sort
directions it was made under. The repository resolves those into a
"strictly after this row" condition, so page N costs what page 1 does and a
concurrent insert can neither repeat nor skip a row.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from typing import Any

from civex.domain.exceptions import ValidationError

_VERSION = 1


def _encode_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"d": value.isoformat()}
    if isinstance(value, uuid.UUID):
        return {"u": str(value)}
    return value


def _decode_value(value: Any) -> Any:
    if isinstance(value, dict):
        if "d" in value:
            return datetime.fromisoformat(value["d"])
        if "u" in value:
            return uuid.UUID(value["u"])
        raise ValueError("unknown value")
    return value


def encode_cursor(key: list[Any], directions: str) -> str:
    """`directions`: one 'a' or 'd' per key term."""
    doc = {"v": _VERSION, "s": directions, "k": [_encode_value(v) for v in key]}
    raw = json.dumps(doc, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[list[Any], str]:
    """(key values, directions); ValidationError for anything not issued by
    `encode_cursor`."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        doc = json.loads(raw)
        if doc["v"] != _VERSION:
            raise ValueError("version")
        key = [_decode_value(v) for v in doc["k"]]
        directions = doc["s"]
        if not isinstance(directions, str) or len(directions) != len(key):
            raise ValueError("shape")
        return key, directions
    except (ValueError, KeyError, TypeError) as e:
        raise ValidationError("Invalid cursor") from e
