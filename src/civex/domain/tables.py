"""Tables in an export: which formats, and how a value is written in each.

A table is the rows of the records an export selects, beside (or instead of) their
files. This module is the one rule for *what a cell holds* and *what a table is
called*; it is pure, so the folder export, the zip, the view export, the CLI and
the collection CSV can't disagree. The writers that put a table on disk are
`civex.services.table_files`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from civex.domain import geo
from civex.domain.exceptions import ValidationError

# format -> (extension, media type). The first is the default.
FORMATS: dict[str, tuple[str, str]] = {
    "csv": (".csv", "text/csv"),
    "tsv": (".tsv", "text/tab-separated-values"),
    "xlsx": (
        ".xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    "json": (".json", "application/json"),
    "jsonl": (".jsonl", "application/x-ndjson"),
}
DEFAULT_FORMAT = "csv"

# Formats whose cells are text (a list or a point has to be written as text).
TEXT_FORMATS = ("csv", "tsv")

# Columns that come from the record itself rather than from one of its fields.
META_COLUMNS = ("id", "schema", "created_at", "updated_at")
# What a table starts with when no columns are chosen: the id, so a row can be
# matched back to its record, then every field.
DEFAULT_META = ("id",)

# Excel refuses a sheet name longer than this or holding any of `: \ / ? * [ ]`.
SHEET_NAME_MAX = 31


def check_format(fmt: str) -> str:
    if fmt not in FORMATS:
        raise ValidationError(f"A table format is one of: {', '.join(FORMATS)}.")
    return fmt


# What a table's rows are: one row per record, or the fields of one record as
# field/value pairs (a metadata sheet).
SHAPE_ROWS = "rows"
SHAPE_FIELDS = "fields"
SHAPES = (SHAPE_ROWS, SHAPE_FIELDS)
# The columns of a field/value table.
FIELD_COLUMNS = ["field", "value"]


@dataclass
class TableSpec:
    """A table to export beside (or instead of) the files. Three independent
    choices say what it is:

    - **rows**: records of `kind` (a schema name). They come from the records the
      export takes, the ones above them, and (with "everything beneath") the ones
      below. None is the first, simplest form: one table for each kind the export
      holds.
    - **where** it is written: None = once, at the top of the export; a schema
      name = in the folder of each record of that kind, holding the records of
      `kind` that are that record or beneath it. `where == kind` is a record's own
      metadata. Folders are the tree layout's, so it needs that layout.
    - **columns**: field names (own, inherited from a record above, or a
      `ref_field.target_field` join) or `META_COLUMNS`; None = the id and every
      field.

    Beside those: its `format`, its `shape`, the file `name` (a template over the
    folder's record, without the extension; None names it for what it holds) and
    whether a folder with no rows gets a table at all (`skip_empty`)."""

    format: str = DEFAULT_FORMAT
    columns: list[str] | None = None
    # What to call the file, without its extension. With `kind` set it is a name
    # template over the folder's record (`{schema}`, `{id}` and its fields); in
    # the first form it is the name when there is just one table.
    name: str | None = None
    kind: str | None = None
    where: str | None = None
    shape: str = SHAPE_ROWS
    skip_empty: bool = True

    def __post_init__(self) -> None:
        check_format(self.format)
        if self.shape not in SHAPES:
            raise ValidationError(f"A table's shape is one of: {', '.join(SHAPES)}.")
        if self.where and not self.kind:
            raise ValidationError("A table written in each folder needs its kind.")
        if self.shape == SHAPE_FIELDS and not (self.kind and self.kind == self.where):
            raise ValidationError(
                "Field/value tables describe one record, so they are written in "
                "each folder of the kind they describe."
            )

    @property
    def general(self) -> bool:
        """The first, simplest form: no kind chosen, so one table per kind the
        export holds, written at the top."""
        return self.kind is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "columns": self.columns,
            "name": self.name,
            "kind": self.kind,
            "where": self.where,
            "shape": self.shape,
            "skip_empty": self.skip_empty,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TableSpec | None":
        if not data:
            return None
        columns = data.get("columns")
        return cls(
            format=data.get("format") or DEFAULT_FORMAT,
            columns=list(columns) if columns else None,
            name=data.get("name") or None,
            kind=data.get("kind") or None,
            where=data.get("where") or None,
            shape=data.get("shape") or SHAPE_ROWS,
            skip_empty=data.get("skip_empty") is not False,
        )

    @classmethod
    def from_list(cls, items: list[dict[str, Any]] | None) -> "list[TableSpec]":
        return [t for t in (cls.from_dict(i) for i in items or []) if t is not None]


def extension(fmt: str) -> str:
    return FORMATS[fmt][0]


def media_type(fmt: str) -> str:
    return FORMATS[fmt][1]


def cell(value: Any, fmt: str) -> Any:
    """One value as it is written in `fmt`.

    Text formats (csv, tsv) write a point as `lat, lon` and any other list or
    object as JSON, so a cell is never Python's repr. xlsx keeps numbers, true/
    false as themselves and writes a list or object as JSON text. json and jsonl
    keep everything as it is."""
    if fmt in ("json", "jsonl"):
        return value
    if geo.is_geometry(value):
        return geo.to_text(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    if fmt in TEXT_FORMATS:
        return "" if value is None else value
    return value


def nest(row: dict[str, Any]) -> dict[str, Any]:
    """{"amount": 100, "customer.email": "a@x"} -> {"amount": 100, "customer":
    {"email": "a@x"}}: json keeps a joined column inside the record it came from
    instead of repeating a flat dotted header."""
    nested: dict[str, Any] = {}
    for key, value in row.items():
        if "." in key:
            head, _, tail = key.partition(".")
            holder = nested.setdefault(head, {})
            if isinstance(holder, dict):
                holder[tail] = value
        else:
            nested[key] = value
    return nested


def sheet_name(name: str) -> str:
    """`name` as a worksheet name Excel accepts."""
    cleaned = re.sub(r"[:\\/?*\[\]]", " ", name).strip().strip("'") or "Sheet"
    return cleaned[:SHEET_NAME_MAX]
