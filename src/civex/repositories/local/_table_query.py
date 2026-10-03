"""Apply a `TableQuery` (filter tree, sort, search) to a SQLAlchemy query over
plain columns. The operators and the AND/OR folding are the same ones the
record repository uses on JSON fields (`compare`, `fold_group`), so a filter
means the same thing on every table."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import String, and_, cast, or_

from civex.domain.exceptions import ValidationError
from civex.domain.filters import FilterCondition, FilterGroup, FilterNode
from civex.domain.query import ResolvedTable, TableQuery


def compare(col: Any, op: str, value: Any) -> Any:
    """`col <op> value` for the six ordering operators."""
    if op == "eq":
        return col == value
    if op == "ne":
        return col != value
    if op == "gt":
        return col > value
    if op == "gte":
        return col >= value
    if op == "lt":
        return col < value
    if op == "lte":
        return col <= value
    raise ValidationError(f"Unsupported filter operator '{op}'")


def fold_group(node: FilterNode, leaf: Callable[[FilterCondition], Any]) -> Any:
    """The SQL for a tree: groups folded with AND/OR, `leaf` for conditions."""
    if isinstance(node, FilterGroup):
        clauses = [fold_group(c, leaf) for c in node.conditions]
        return and_(*clauses) if node.op == "and" else or_(*clauses)
    return leaf(node)


def _coerce(col: Any, value: Any) -> Any:
    """An ISO string compared with a timestamp column becomes a datetime, so
    SQLite (which stores 'YYYY-MM-DD HH:MM:SS') orders it correctly."""
    try:
        is_datetime = col.type.python_type is datetime
    except NotImplementedError:
        return value
    if is_datetime and isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValidationError(f"'{value}' is not a date or time")
    return value


def _column_leaf(node: FilterCondition, columns: Mapping[str, Any]) -> Any:
    col = columns[node.field]
    if node.op == "is_null":
        return col.is_(None) if node.value else col.isnot(None)
    if node.op == "contains":
        return cast(col, String).ilike(f"%{node.value}%")
    if node.op == "in":
        return col.in_([_coerce(col, v) for v in node.value])
    return compare(col, node.op, _coerce(col, node.value))


def apply_table_query(
    q: Any,
    table: TableQuery | None,
    columns: Mapping[str, Any],
    search_columns: tuple[str, ...] = (),
) -> tuple[Any, list[Any], ResolvedTable]:
    """The query narrowed by the filter and search, plus ORDER BY terms (nulls
    last either way) and the resolved query. Count with the narrowed query;
    list with the terms."""
    resolved = (table or TableQuery()).resolve(columns.keys())
    if resolved.filter_tree is not None:
        q = q.filter(
            fold_group(resolved.filter_tree, lambda n: _column_leaf(n, columns))
        )
    if resolved.search and search_columns:
        q = q.filter(
            or_(
                *[
                    cast(columns[c], String).ilike(f"%{resolved.search}%")
                    for c in search_columns
                ]
            )
        )
    terms: list[Any] = []
    for name, descending in resolved.sort:
        col = columns[name]
        terms.append(col.is_(None))
        terms.append(col.desc() if descending else col.asc())
    return q, terms, resolved
