"""Uniqueness policies: which field combinations no two records may share.

A schema carries a list of *keys*, each a list of its own field ids. Two live
records of the schema clash on a key when every field of the key holds the
same value *and* they sit in the same place: under the same parent record,
or, for a top-level record, in the same collection. A record with a blank value
in any of a key's fields isn't constrained by that key (as in SQL, blanks don't
clash; `required` is how a field is made mandatory).

Pure and framework-free: the rule for what counts as blank, which types can
form a key, and how a key's values are read from a record's data.
"""

from __future__ import annotations

from typing import Any

# Types whose values compare as plain scalars. Files, geometries and the list
# types have no single obvious notion of "the same value".
UNIQUE_DTYPES = frozenset(
    {
        "integer",
        "float",
        "string",
        "boolean",
        "date",
        "datetime",
        "enum",
        "url",
        "reference",
    }
)


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def key_values(data: dict[str, Any], field_ids: list[str]) -> list[Any] | None:
    """The values of a key in a record's id-keyed `data`, or None when any is
    blank (the record isn't constrained by this key)."""
    values = [data.get(fid) for fid in field_ids]
    if any(is_blank(v) for v in values):
        return None
    return values


def normalise_keys(keys: list[list[str]]) -> list[list[str]]:
    """Drop repeats (the same fields in any order are one key) keeping the
    first spelling; a key's fields keep the order they were given in."""
    seen: set[frozenset[str]] = set()
    out: list[list[str]] = []
    for key in keys:
        marker = frozenset(key)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(list(key))
    return out
