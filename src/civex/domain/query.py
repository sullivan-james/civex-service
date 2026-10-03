"""The one description of "which records" that every read path shares.

`RecordQuery` is what callers write -- names, JSON filter trees, view-style
sort lists -- and `ResolvedQuery` is what a `RecordService` turns it into for
the repository: ids, parsed `FilterNode`s, `SortKey`s. The collection list,
a record's descendants, a saved view, exports, counts and the AI tools all
run through this pair, so a filter means the same thing everywhere.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field as _field
from typing import Any

from civex.domain.filters import FilterNode, SortKey


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
