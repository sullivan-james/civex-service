"""Field indexes: which fields can have one, what kind of value it holds, and
what it is called.

A field index is an expression index on one field's value over the live
records of the schema that owns the field. It belongs to this computer's
database, like any index: it is never in a record, the history or a sync
bundle, and the database it is in can be rebuilt from what is wanted. Which
fields are wanted is decided by `IndexService`; this module is the pure part.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from civex.domain.uniqueness import UNIQUE_DTYPES

# How a field's value is read in SQL: as a number (compared numerically, 1 ==
# 1.0), as text (ISO dates and datetimes sort as text), or as a boolean.
KINDS = ("number", "text", "boolean")

# Scalars only, the same types a uniqueness key may hold: lists, files and
# geometries have no single value to order by.
INDEXABLE_DTYPES = UNIQUE_DTYPES

# Every managed index's name starts with this; nothing else may.
PREFIX = "ix_rf_"

# Why the planner's statistics are being refreshed (`db/statistics.py`
# decides what each means on each database).
INDEX_BUILT = "index_built"
BULK_WRITE = "bulk_write"
PERIODIC = "periodic"

# Why a field is indexed.
UNIQUE_KEY = "unique_key"  # part of a uniqueness key: checked on every save
CHOSEN = "chosen"  # a person asked for it


def kind_of(dtype: str) -> str | None:
    """How a field of `dtype` is read in SQL, or None if it can't be indexed.
    Filters and sorts read it the same way (`RecordService._resolve_sort`
    sorts integers and floats as numbers, everything else as text)."""
    if dtype not in INDEXABLE_DTYPES:
        return None
    if dtype in ("integer", "float"):
        return "number"
    if dtype == "boolean":
        return "boolean"
    return "text"


def index_name(field_id: uuid.UUID | str) -> str:
    """`ix_rf_<field id as 32 hex digits>`: one per field, so a rename costs
    nothing, and short enough for PostgreSQL's 63-character limit."""
    return PREFIX + uuid.UUID(str(field_id)).hex


def field_of(name: str) -> uuid.UUID | None:
    """The field id a managed index's name stands for, or None."""
    if not name.startswith(PREFIX):
        return None
    try:
        return uuid.UUID(hex=name[len(PREFIX) :])
    except ValueError:
        return None


@dataclass(frozen=True)
class FieldIndexSpec:
    """One index: on `field_id`'s value as `kind`, over the live records of
    `schema_id` (the schema that defines the field: a record stores only its
    own schema's fields)."""

    field_id: uuid.UUID
    schema_id: uuid.UUID
    kind: str

    @property
    def name(self) -> str:
        return index_name(self.field_id)


@dataclass
class FieldIndexState:
    """A field index as `IndexService.status` reports it."""

    field_id: uuid.UUID
    field_name: str
    schema_name: str
    reasons: list[str] = field(default_factory=list)  # UNIQUE_KEY, CHOSEN
    built: bool = False  # in the database now
    indexable: bool = True  # a single-valued type (`INDEXABLE_DTYPES`)

    @property
    def name(self) -> str:
        return index_name(self.field_id)


@dataclass
class FieldIndexReport:
    """What is wanted and what the database has: `fields` are the wanted ones
    (built or not), `stale` the managed indexes nothing wants any more."""

    fields: list[FieldIndexState] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)

    @property
    def missing(self) -> list[FieldIndexState]:
        return [f for f in self.fields if not f.built]

    @property
    def in_step(self) -> bool:
        return not self.missing and not self.stale


@dataclass
class ReconcileResult:
    created: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    seconds: float = 0.0
    # Builds that stopped to let a save through, and were started again.
    yielded: int = 0
    # Stopped before the end (the host is shutting down): not in step yet.
    stopped: bool = False


@dataclass
class IndexProgress:
    """How far a reconcile has got, for the status bar and the CLI's bar:
    building the `done + 1`th of `total` indexes, the one on `field_label` of
    `schema_label`, or `waiting` for a quiet moment to start it (on SQLite a
    build holds saves back, so it waits until nobody has saved for a few
    seconds, and stops to let a save through: `yielded` counts those)."""

    done: int
    total: int
    schema_label: str = ""
    field_label: str = ""
    waiting: bool = False
    yielded: int = 0


class IndexBuildYielded(Exception):
    """A build stopped part way to let a save through (SQLite); nothing of it
    was kept, and it is started again once saving has gone quiet."""
