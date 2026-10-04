"""Filtering workflow runs with the same filter tree as records.

The wire format and parsing are `domain/filters.py`'s: AND/OR groups of
`{"field", "op", "value"}`. Only the fields differ. A record's are its schema's;
a run's are the ones declared here, once, for the repository that applies them
and the UI that builds the filter (`GET /jobs/filter-fields`). A leaf naming a
`schema` is refused: runs have no hierarchy to reach through.
"""

from __future__ import annotations

from dataclasses import dataclass, field as _field
from typing import Any

from civex.domain.exceptions import ValidationError
from civex.domain.filters import FilterNode, leaves, parse_filter_tree

STATUSES = ["pending", "running", "completed", "failed", "cancelled"]
TRIGGERS = ["record_created", "record_updated", "manual"]

# Operators each kind of field accepts.
_TEXT_OPS = ["eq", "ne", "contains", "in", "is_null"]
_CHOICE_OPS = ["eq", "ne", "in", "is_null"]
_NUMBER_OPS = ["eq", "ne", "gt", "gte", "lt", "lte"]
_DATE_OPS = ["gt", "gte", "lt", "lte", "is_null"]


@dataclass(frozen=True)
class RunField:
    name: str
    label: str
    # string | enum | integer | datetime, as record field types, so the filter
    # builder offers the same controls.
    type: str
    description: str = ""
    # Fixed choices; None = free (the UI offers the values it knows of).
    choices: list[str] | None = None
    operators: list[str] = _field(default_factory=list)


RUN_FIELDS: list[RunField] = [
    RunField(
        "workflow", "Workflow", "string", "The workflow's name.", None, _CHOICE_OPS
    ),
    RunField("status", "Result", "enum", "How the run ended.", STATUSES, _CHOICE_OPS),
    RunField(
        "trigger", "Started by", "enum", "What started it.", TRIGGERS, _CHOICE_OPS
    ),
    RunField(
        "schema",
        "Record schema",
        "string",
        "The schema of the record it ran on.",
        None,
        _CHOICE_OPS,
    ),
    RunField(
        "created_at", "Queued", "datetime", "When the run was queued.", None, _DATE_OPS
    ),
    RunField(
        "finished_at", "Finished", "datetime", "When the run ended.", None, _DATE_OPS
    ),
    RunField(
        "error_kind",
        "Failure type",
        "string",
        "The kind of failure, such as validation_error or timeout.",
        None,
        _CHOICE_OPS,
    ),
    RunField(
        "error",
        "Error message",
        "string",
        "The failure's own message.",
        None,
        _TEXT_OPS,
    ),
    RunField(
        "failed_step",
        "Failed step",
        "string",
        "The id of the step that failed.",
        None,
        _CHOICE_OPS,
    ),
    RunField(
        "depth",
        "Chain depth",
        "integer",
        "How many runs started this one.",
        None,
        _NUMBER_OPS,
    ),
    RunField(
        "record",
        "Record id",
        "string",
        "The record it ran on.",
        None,
        ["eq", "ne", "in"],
    ),
]
_BY_NAME = {f.name: f for f in RUN_FIELDS}


def parse_run_filter(raw: Any) -> FilterNode:
    """Parse and check a run filter: known fields, an operator each accepts,
    no schema-qualified conditions. Raises ValidationError otherwise."""
    tree = parse_filter_tree(raw)
    for leaf in leaves(tree):
        if leaf.schema is not None:
            raise ValidationError("Run filters can't name a schema.")
        spec = _BY_NAME.get(leaf.field)
        if spec is None:
            raise ValidationError(
                f"Unknown run field '{leaf.field}'. Must be one of: "
                f"{', '.join(_BY_NAME)}"
            )
        if leaf.op not in spec.operators:
            raise ValidationError(
                f"'{leaf.op}' doesn't apply to {spec.label}; use one of "
                f"{', '.join(spec.operators)}"
            )
    return tree
