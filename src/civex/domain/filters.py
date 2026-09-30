"""Filter tree for record queries: AND/OR groups of field conditions.

Wire format (JSON, decoded from the `filter` query parameter):

    Leaf:  {"field": "<name>", "op": "eq", "value": ..., "schema": "<name>"?}
    Group: {"and": [<node>, ...]} | {"or": [<node>, ...]}

Groups nest to arbitrary depth. `op` is one of OPERATORS below; `value` is
omitted (or ignored) for "is_null", must be a list for "in".

A leaf tests a field of the record being queried unless it names another
`schema`: an ancestor schema (the record's parent, grandparent, ...) tests
that ancestor record's field; a descendant schema matches when the record has
*any* descendant of that schema satisfying the condition. A bare field name
owned by an ancestor schema (inherited) resolves to that ancestor, because a
child record stores only its own fields.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field as _field
from typing import Any, Literal

from civex.domain.exceptions import ValidationError

OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte", "contains", "in", "is_null"}
GROUP_OPS = {"and", "or"}


@dataclass(frozen=True)
class Relation:
    """Where the record a leaf tests sits relative to the record queried:
    itself, `hops` parents up, or (down) any descendant of `schema_id`."""

    direction: Literal["self", "up", "down"] = "self"
    hops: int = 0
    # "down" only: the descendant schema whose records are tested. The schema
    # chain is a tree, so this alone pins the path from the queried record.
    schema_id: uuid.UUID | None = None


SELF = Relation()


@dataclass
class FilterCondition:
    field: str
    op: str
    value: Any = None
    # Wire: the schema whose field this is (None = the queried schema, or the
    # ancestor that owns an inherited name). Resolved into `rel` by the
    # service; repositories only ever read `rel`.
    schema: str | None = None
    rel: Relation = SELF


@dataclass
class FilterGroup:
    op: str  # "and" | "or"
    conditions: list["FilterNode"] = _field(default_factory=list)


FilterNode = FilterCondition | FilterGroup


def parse_filter_tree(raw: Any) -> FilterNode:
    """Parse a JSON-decoded filter tree into FilterCondition/FilterGroup nodes.

    Raises ValidationError on any structural problem (unknown operator, wrong
    shape, non-list "in" value, ...).
    """
    if not isinstance(raw, dict):
        raise ValidationError(
            f"Filter node must be an object, got {type(raw).__name__}"
        )

    group_keys = GROUP_OPS & raw.keys()
    if group_keys:
        if len(raw) != 1:
            raise ValidationError(
                f"Filter group must have exactly one key ('and' or 'or'), got {sorted(raw)}"
            )
        (op,) = group_keys
        children = raw[op]
        if not isinstance(children, list) or not children:
            raise ValidationError(f"Filter group '{op}' must be a non-empty list")
        return FilterGroup(op=op, conditions=[parse_filter_tree(c) for c in children])

    if "field" not in raw or "op" not in raw:
        raise ValidationError(
            "Filter condition must have 'field' and 'op' keys, or be an 'and'/'or' group"
        )
    field_name = raw["field"]
    if not isinstance(field_name, str) or not field_name:
        raise ValidationError("Filter condition 'field' must be a non-empty string")
    op = raw["op"]
    if op not in OPERATORS:
        raise ValidationError(
            f"Unknown filter operator '{op}'. Must be one of: {', '.join(sorted(OPERATORS))}"
        )
    schema_name = raw.get("schema")
    if schema_name is not None and (
        not isinstance(schema_name, str) or not schema_name
    ):
        raise ValidationError("Filter condition 'schema' must be a non-empty string")
    value = raw.get("value")
    if op == "in" and not isinstance(value, list):
        raise ValidationError("Filter operator 'in' requires a list 'value'")
    if op == "is_null" and value is None:
        value = True
    return FilterCondition(field=field_name, op=op, value=value, schema=schema_name)


def map_leaves(node: FilterNode, fn: Any) -> FilterNode:
    """Return a copy of the tree with `fn` applied to every condition."""
    if isinstance(node, FilterGroup):
        return FilterGroup(
            op=node.op, conditions=[map_leaves(c, fn) for c in node.conditions]
        )
    return fn(node)


def leaves(node: FilterNode) -> list[FilterCondition]:
    """Every condition in the tree, depth-first."""
    if isinstance(node, FilterGroup):
        return [leaf for c in node.conditions for leaf in leaves(c)]
    return [node]


@dataclass(frozen=True)
class SortKey:
    """One ORDER BY term over a record field, already resolved to the
    stored (field-UUID) key. `numeric` picks numeric over text comparison."""

    field_id: str
    numeric: bool = False
    descending: bool = False
    # An ancestor's field ("up") or the record's own ("self"); sorting by a
    # descendant's field is ill-defined (many per record) and never built.
    rel: Relation = SELF
