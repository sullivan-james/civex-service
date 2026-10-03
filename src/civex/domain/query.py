"""The one description of "which records" that every read path shares.

`RecordQuery` is what callers write -- names, JSON filter trees, view-style
sort lists -- and `ResolvedQuery` is what a `RecordService` turns it into for
the repository: ids, parsed `FilterNode`s, `SortKey`s. The collection list,
a record's descendants, a saved view, exports, counts and the AI tools all
run through this pair, so a filter means the same thing everywhere.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass, field as _field
from typing import Any

from civex.domain.exceptions import ValidationError
from civex.domain.filters import (
    FilterCondition,
    FilterNode,
    SortKey,
    leaves,
    parse_filter_tree,
)


@dataclass
class RecordQuery:
    dataset: str | None = None  # None: across every collection
    schema: str | None = None
    # Record id (or prefix): only records of `schema` that descend from it, at
    # any depth (an encounter's selections, not just its recordings).
    # Requires `schema`.
    within: str | None = None
    # Record id (or prefix): direct children only, whatever their schema.
    parent_record_id: str | None = None
    filter_tree: dict[str, Any] | None = None  # civex.domain.filters wire shape
    # Legacy "field=value" equality terms, AND-combined with `filter_tree`.
    where: list[str] = _field(default_factory=list)
    search: str | None = None
    # [{"field": name, "direction": "asc"|"desc"}, ...]
    sort: list[dict[str, Any]] | None = None


@dataclass
class ResolvedQuery:
    dataset_id: uuid.UUID | None = None
    schema_id: uuid.UUID | None = None
    parent_record_id: uuid.UUID | None = None
    # (ancestor record id, hops from the queried schema up to that record's)
    within: tuple[uuid.UUID, int] | None = None
    field_filters: list[tuple[str, str]] = _field(default_factory=list)
    search: str | None = None
    filter_tree: FilterNode | None = None
    sort: list[SortKey] | None = None


@dataclass
class TableQuery:
    """Filter, sort and search over a flat table of named columns (workflow
    runs, the audit log). It reuses the record explorer's wire shapes -- the
    same AND/OR filter tree and `field:direction` sort terms -- so one builder
    on the frontend drives both. A leaf may only name a column, never a
    `schema`: there is no hierarchy to reach through."""

    filter_tree: dict[str, Any] | None = None  # civex.domain.filters wire shape
    sort: list[dict[str, Any]] | None = None  # [{"field", "direction"}, ...]
    search: str | None = None

    def resolve(self, columns: Collection[str]) -> "ResolvedTable":
        """Parse against the table's columns; anything else is a ValidationError."""
        tree: FilterNode | None = None
        if self.filter_tree:
            tree = parse_filter_tree(self.filter_tree)
            for leaf in leaves(tree):
                _check_column(leaf, columns)
        order: list[tuple[str, bool]] = []
        for entry in self.sort or []:
            name = str(entry.get("field") or "")
            direction = entry.get("direction") or "asc"
            if name not in columns or entry.get("schema"):
                raise ValidationError(f"Cannot sort by '{name}'")
            if direction not in ("asc", "desc"):
                raise ValidationError(f"Unknown sort direction '{direction}'")
            order.append((name, direction == "desc"))
        return ResolvedTable(filter_tree=tree, sort=order, search=self.search or None)


def _check_column(leaf: FilterCondition, columns: Collection[str]) -> None:
    if leaf.schema or leaf.field not in columns:
        raise ValidationError(
            f"Cannot filter on '{leaf.field}'. Available: {', '.join(sorted(columns))}"
        )


@dataclass
class ResolvedTable:
    filter_tree: FilterNode | None = None
    # (column, descending)
    sort: list[tuple[str, bool]] = _field(default_factory=list)
    search: str | None = None
