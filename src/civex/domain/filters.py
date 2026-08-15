"""Filter tree for record queries: AND/OR groups of field conditions.

Wire format (JSON, decoded from the `filter` query parameter):

    Leaf:  {"field": "<name>", "op": "eq", "value": ...}
    Group: {"and": [<node>, ...]} | {"or": [<node>, ...]}

Groups nest to arbitrary depth. `op` is one of OPERATORS below; `value` is
omitted (or ignored) for "is_null", must be a list for "in".
"""

from __future__ import annotations

from dataclasses import dataclass, field as _field
from typing import Any

from civex.domain.exceptions import ValidationError

OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte", "contains", "in", "is_null"}
GROUP_OPS = {"and", "or"}


@dataclass
class FilterCondition:
    field: str
    op: str
    value: Any = None


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
    value = raw.get("value")
    if op == "in" and not isinstance(value, list):
        raise ValidationError("Filter operator 'in' requires a list 'value'")
    if op == "is_null" and value is None:
        value = True
    return FilterCondition(field=field_name, op=op, value=value)


def map_fields(node: FilterNode, name_to_id: dict[str, str]) -> FilterNode:
    """Return a copy of the tree with each condition's `field` resolved
    through `name_to_id` (unresolved names pass through unchanged)."""
    if isinstance(node, FilterGroup):
        return FilterGroup(
            op=node.op, conditions=[map_fields(c, name_to_id) for c in node.conditions]
        )
    return FilterCondition(
        field=name_to_id.get(node.field, node.field), op=node.op, value=node.value
    )
