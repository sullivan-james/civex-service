"""Filtering history with the same filter tree as records and runs.

The wire format and parsing are `domain/filters.py`'s: AND/OR groups of
`{"field", "op", "value"}`. Only the fields differ: a change's are the ones
declared here, once, for the repository that applies them and the UI that
builds the filter (`GET /audit/filter-fields`). A leaf naming a `schema` is
refused, as it is for runs.
"""

from __future__ import annotations

from typing import Any

from civex.domain.exceptions import ValidationError
from civex.domain.filters import FilterNode, leaves, parse_filter_tree
from civex.domain.run_filters import RunField as AuditField

KINDS = ["record", "schema", "field", "dataset", "view"]
CHANGES = ["create", "update", "delete", "restore", "purge"]
# How a change came about: on its own, or as part of a batch of this kind.
HOWS = ["single", "import", "delete", "restore", "purge", "workflow"]
# Where the record a change is about is now.
NOWS = ["live", "deleted", "gone"]

_CHOICE_OPS = ["eq", "ne", "in"]
_DATE_OPS = ["gt", "gte", "lt", "lte"]

AUDIT_FIELDS: list[AuditField] = [
    AuditField("when", "When", "datetime", "When it happened.", None, _DATE_OPS),
    AuditField("kind", "Kind", "enum", "What it was done to.", KINDS, _CHOICE_OPS),
    AuditField("change", "Change", "enum", "What was done.", CHANGES, _CHOICE_OPS),
    AuditField(
        "how",
        "How",
        "enum",
        "On its own, or as part of an import, a delete, a restore or a workflow run.",
        HOWS,
        _CHOICE_OPS,
    ),
    AuditField(
        "collection",
        "Collection",
        "string",
        "The collection it was in, including records since deleted.",
        None,
        _CHOICE_OPS,
    ),
    AuditField(
        "schema",
        "Schema",
        "string",
        "The schema: changes to the schema itself, to its fields, and to records "
        "of that type (not of schemas that inherit from it).",
        None,
        _CHOICE_OPS,
    ),
    AuditField(
        "under",
        "Under record",
        "string",
        "A record, and everything beneath it or naming it, deleted or not.",
        None,
        ["eq"],
    ),
    AuditField(
        "now",
        "Now",
        "enum",
        "Where the record is now: live, deleted (restorable) or gone for good.",
        NOWS,
        _CHOICE_OPS,
    ),
]
_BY_NAME = {f.name: f for f in AUDIT_FIELDS}


def parse_audit_filter(raw: Any) -> FilterNode:
    """Parse and check a history filter: known fields, an operator each accepts,
    no schema-qualified conditions. Raises ValidationError otherwise."""
    tree = parse_filter_tree(raw)
    for leaf in leaves(tree):
        if leaf.schema is not None:
            raise ValidationError("History filters can't name a schema.")
        spec = _BY_NAME.get(leaf.field)
        if spec is None:
            raise ValidationError(
                f"Unknown history field '{leaf.field}'. Must be one of: "
                f"{', '.join(_BY_NAME)}"
            )
        if leaf.op not in spec.operators:
            raise ValidationError(
                f"'{leaf.op}' doesn't apply to {spec.label}; use one of "
                f"{', '.join(spec.operators)}"
            )
    return tree
