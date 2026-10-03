"""The query-string contract shared by every endpoint that selects records:
the collection list, the schema-wide list, exports, counts and bulk delete.
One dependency, one `RecordQuery` -- so a filter means the same thing on all
of them (see civex.domain.query)."""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import HTTPException, Query

from civex.domain.query import RecordQuery, TableQuery


def _parse_sort(terms: list[str]) -> list[dict[str, Any]] | None:
    entries = []
    for term in terms:
        name, _, direction = term.partition(":")
        schema_name, dot, field_name = name.rpartition(".")
        entry: dict[str, Any] = {
            "field": field_name if dot else name,
            "direction": direction or "asc",
        }
        if dot:
            entry["schema"] = schema_name
        entries.append(entry)
    return entries or None


def _load_filter(raw: str | None) -> dict[str, Any] | None:
    try:
        return json.loads(raw) if raw else None
    except json.JSONDecodeError as e:
        raise HTTPException(422, detail=f"Invalid 'filter' JSON: {e}")


def table_query(
    filter_: Optional[str] = Query(
        default=None,
        alias="filter",
        description="JSON-encoded filter tree over the table's columns: the "
        "same AND/OR shape as the record 'filter', but a condition names only "
        "a column (no 'schema'). Which columns: the table's own listing.",
    ),
    sort: list[str] = Query(
        default=[],
        description="Repeatable 'column[:asc|desc]'. Nulls sort last.",
    ),
    search: Optional[str] = Query(
        default=None, description="Case-insensitive text match, where supported."
    ),
) -> TableQuery:
    """The query-string contract for tables of runs and audit entries. The same
    `filter` and `sort` spelling as the record lists, so one builder drives both."""
    return TableQuery(
        filter_tree=_load_filter(filter_),
        sort=_parse_sort(sort),
        search=search or None,
    )


def record_query(
    schema: Optional[str] = Query(
        default=None, description="Only records of this schema."
    ),
    within: Optional[str] = Query(
        default=None,
        description="Record id (or prefix): only records of 'schema' that "
        "descend from it, at any depth -- an encounter's selections, not just "
        "its recordings. Requires 'schema'.",
    ),
    parent_record_id: Optional[str] = Query(
        default=None,
        description="Record id (or prefix): direct children only, of any schema.",
    ),
    search: Optional[str] = Query(
        default=None, description="Full-text search across all field values"
    ),
    where: list[str] = Query(
        default=[],
        description="Simple equality filter, repeatable: 'field=value'. "
        "AND-combined with each other and with 'filter'. Kept for backwards "
        "compatibility -- prefer 'filter' for anything beyond plain equality.",
    ),
    filter_: Optional[str] = Query(
        default=None,
        alias="filter",
        description="JSON-encoded filter tree, AND/OR groups of field "
        "conditions. "
        'Leaf: {"field": "<name>", "op": "eq"|"ne"|"gt"|"gte"|'
        '"lt"|"lte"|"contains"|"in"|"is_null", "value": ..., "schema": '
        '"<name>"?}. '
        'Group: {"and": [<node>, ...]} or {"or": [<node>, ...]}, nestable. '
        "'value' must be a list for 'in' and is optional (default true) for "
        "'is_null'. A leaf tests the listed schema's own field unless it "
        "names another 'schema': an ancestor's (tests the parent/grandparent "
        "record) or a descendant's (matches records having ANY such "
        "descendant that satisfies it). An inherited field name resolves to "
        "the ancestor that owns it. Example: "
        '{"and": [{"field": "status", "op": "eq", "value": "active"}, '
        '{"schema": "selection", "field": "selection_table", "op": "is_null"}]}',
    ),
    sort: list[str] = Query(
        default=[],
        description="Repeatable '[schema.]field[:asc|desc]'. Nulls sort last "
        "either way. Needs 'schema'; 'schema.' names an ancestor whose field "
        "to sort by.",
    ),
) -> RecordQuery:
    tree = _load_filter(filter_)
    return RecordQuery(
        schema=schema or None,
        within=within or None,
        parent_record_id=parent_record_id or None,
        search=search or None,
        where=where,
        filter_tree=tree,
        sort=_parse_sort(sort),
    )
