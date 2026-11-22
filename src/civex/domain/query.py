"""The one description of "which records" that every read path shares.

`RecordQuery` is what callers write -- names, JSON filter trees, view-style
sort lists -- and `ResolvedQuery` is what a `RecordService` turns it into for
the repository: ids, parsed `FilterNode`s, `SortKey`s. The collection list,
a record's descendants, a saved view, exports, counts and the AI tools all
run through this pair, so a filter means the same thing everywhere.
"""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass, field as _field
from typing import Any

from civex.domain.field_descriptors import FIELD_TYPES
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
    # Field names to look in for `search` (None: every searchable field).
    # Requires `schema`, like `where`.
    search_fields: list[str] | None = None
    # [{"field": name, "direction": "asc"|"desc"}, ...]
    sort: list[dict[str, Any]] | None = None

    def for_kind(self, schema: str) -> RecordQuery:
        """The same query run for another kind of record (the kinds beneath a
        record, or beneath what a filter chose). `search_fields` name fields
        of this query's own kind, so another kind searches all of its own."""
        return dataclasses.replace(
            self,
            schema=schema,
            search_fields=self.search_fields if schema == self.schema else None,
        )


# Values of these types are never matched by a text search
# (`FieldTypeDescriptor.searchable`). Everything else is matched by its value:
# a number by its text, a list by its items, a file by its name.
UNSEARCHED_DTYPES = frozenset(t.type for t in FIELD_TYPES.values() if not t.searchable)

# A search term this long or longer that reads as hex also matches records
# whose id starts with it (a pasted id finds its record); shorter, "e4" would
# find one record in 256 for no reason anyone could see.
ID_PREFIX_MIN = 4

#: What a list may be sorted by besides a kind's fields, and the only sorts a
#: list of every kind takes (a field means something only within its kind):
#: the record's kind, its collection, when it was last changed or made.
META_SORTS = ("@kind", "@collection", "@updated_at", "@created_at")


@dataclass(frozen=True)
class TextSearch:
    """A search term and the fields it looks in, resolved: what the search
    box, the reference pickers, the jump-to box and the AI tools all ask the
    repository for. A match is a case-insensitive substring of a value of one
    of `field_ids` (never a key, a file's hash or size, or a geometry), or a
    record id starting with `term`."""

    term: str
    # The field ids whose values are searched: the searchable fields of the
    # kinds listed, or the ones a person picked.
    field_ids: tuple[str, ...] = ()


@dataclass
class ResolvedQuery:
    dataset_id: uuid.UUID | None = None
    schema_id: uuid.UUID | None = None
    parent_record_id: uuid.UUID | None = None
    # (ancestor record id, hops from the queried schema up to that record's)
    within: tuple[uuid.UUID, int] | None = None
    # Every kind beneath a record (`within` with no kind listed): (that
    # record's id, how many levels the deepest kind beneath it is down).
    beneath: tuple[uuid.UUID, int] | None = None
    field_filters: list[tuple[str, str]] = _field(default_factory=list)
    search: TextSearch | None = None
    filter_tree: FilterNode | None = None
    sort: list[SortKey] | None = None
