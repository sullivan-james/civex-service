"""The one SQL expression for a record field's value, as a number, text or
boolean.

Every filter, sort and uniqueness check reads a field through `field_value`,
and every managed field index (`db/field_indexes.py`) is built on it too. The
planner uses an expression index only when the query's expression is exactly
the indexed one, so they must come from the same place: a filter written any
other way would silently stop using the index.

The JSON path is written into the SQL as a literal rather than bound as a
parameter, because an index is defined by its text: SQLite and PostgreSQL
compare a query's expression with the index's, and a placeholder never equals
a constant. Field ids are UUIDs; anything else is quoted safely all the same.

The SQL is the same as SQLAlchemy's own `data[key].as_float()` /
`.as_string()` / `.as_boolean()` (which this replaced), so values compare
exactly as they did.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, Float, String
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.visitors import InternalTraversal

from civex.domain.field_index import KINDS

_TYPES = {"number": Float, "text": String, "boolean": Boolean}
_CASTS = {"number": "FLOAT", "text": "VARCHAR", "boolean": "BOOLEAN"}


class FieldValue(ColumnElement[Any]):
    """`data -> field_id` typed as `kind` (see `civex.domain.field_index`)."""

    inherit_cache = True
    _traverse_internals = [
        ("data", InternalTraversal.dp_clauseelement),
        ("field_id", InternalTraversal.dp_string),
        ("kind", InternalTraversal.dp_string),
    ]

    def __init__(self, data: Any, field_id: str, kind: str) -> None:
        if kind not in KINDS:
            raise ValueError(f"Unknown field value kind '{kind}'")
        self.data = data
        self.field_id = str(field_id)
        self.kind = kind
        self.type = _TYPES[kind]()


def field_value(entity: Any, field_id: str, kind: str) -> FieldValue:
    """The value of `field_id` on `entity` (`Record`, or an alias of it)."""
    return FieldValue(entity.data, field_id, kind)


def _quoted(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


@compiles(FieldValue, "postgresql")
def _postgresql(element: FieldValue, compiler: Any, **kw: Any) -> str:
    data = compiler.process(element.data, **kw)
    return f"CAST(({data} ->> {_quoted(element.field_id)}) AS {_CASTS[element.kind]})"


@compiles(FieldValue)
def _default(element: FieldValue, compiler: Any, **kw: Any) -> str:
    # SQLite (and anything else with JSON_EXTRACT): the key quoted inside the
    # path so a key with a dot or a dash is one step.
    data = compiler.process(element.data, **kw)
    key = element.field_id.replace("\\", "\\\\").replace('"', '\\"')
    path = _quoted(f'$."{key}"')
    return f"CAST(JSON_EXTRACT({data}, {path}) AS {_CASTS[element.kind]})"
