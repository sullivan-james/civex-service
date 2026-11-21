"""Managed field indexes in the database: list, create, drop.

Made at runtime, not by a migration, because which fields have one is a choice
about this computer's database (see `IndexService`, the one place that
decides). Each is a partial expression index named `ix_rf_<field id>`:

    CREATE INDEX ix_rf_<id>
        ON records (dataset_id, <field_value(data, id, kind)>, created_at, id)
        WHERE deleted_at IS NULL AND schema_id = '<schema id>'

over exactly the expression the filter and sort compiler writes
(`db/field_values.py`), and only the live records of the schema that owns the
field, which every list of that kind already narrows to. The columns are the
whole of a collection's sorted listing (`record_repo._order_by` plus its
tie-breakers), so the index hands a page over in order: an index on the value
alone is passed over by SQLite's planner for `ix_records_dataset_schema` and a
sort of every record of the kind, because it can't give the tie-breakers'
order. The same index serves a range or equality filter on the field within a
collection, its count, and the uniqueness check on save. Across every
collection (no `dataset_id`) it is not used for sorting. The models never name
these indexes, so `missing_structure` (tables and columns) and the migration
drift check ignore them.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import column, text
from sqlalchemy.engine import Connection

from civex.db.field_values import FieldValue
from civex.db.models import Record
from civex.domain.field_index import PREFIX, FieldIndexSpec, field_of

_LIKE = PREFIX.replace("_", "\\_") + "%"


def existing(conn: Connection) -> set[str]:
    """Names of the managed indexes the database has now (on PostgreSQL only
    valid ones: a CONCURRENTLY build that was interrupted leaves an invalid
    index behind, which `create` replaces)."""
    if conn.dialect.name == "postgresql":
        sql = (
            "SELECT c.relname FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indexrelid "
            "JOIN pg_class t ON t.oid = i.indrelid "
            "WHERE t.relname = 'records' AND t.relnamespace = current_schema()::regnamespace "
            "AND i.indisvalid AND c.relname LIKE :p ESCAPE '\\'"
        )
    else:
        sql = (
            "SELECT name FROM sqlite_master WHERE type = 'index' "
            "AND tbl_name = 'records' AND name LIKE :p ESCAPE '\\'"
        )
    return {row[0] for row in conn.execute(text(sql), {"p": _LIKE})}


def _value_sql(spec: FieldIndexSpec, dialect: Any) -> str:
    expr = FieldValue(
        column("data", Record.__table__.c.data.type), str(spec.field_id), spec.kind
    )
    return str(expr.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))


def stats_name(name: str) -> str:
    """PostgreSQL: the statistics object kept beside a field index."""
    return f"{name}_stats"


def stats_sql(spec: FieldIndexSpec, dialect: Any) -> str:
    """PostgreSQL ignores a *partial* index's statistics when it estimates how
    many records a condition on its expression matches (a range then counts as
    a third of the table, and the planner scans everything rather than use the
    index), so each index has statistics on the value of its own, which
    `ANALYZE` fills (PostgreSQL 14+)."""
    return (
        f"CREATE STATISTICS IF NOT EXISTS {stats_name(spec.name)} "
        f"ON ({_value_sql(spec, dialect)}) FROM records"
    )


def create_sql(spec: FieldIndexSpec, dialect: Any) -> str:
    """The CREATE INDEX statement for `spec` in `dialect` (an `Engine.dialect`)."""
    where = column("deleted_at").is_(None) & (
        column("schema_id", Record.__table__.c.schema_id.type) == spec.schema_id
    )
    on = _value_sql(spec, dialect)
    cond = where.compile(dialect=dialect, compile_kwargs={"literal_binds": True})
    concurrently = " CONCURRENTLY" if dialect.name == "postgresql" else ""
    return (
        f"CREATE INDEX{concurrently} IF NOT EXISTS {spec.name} "
        f"ON records (dataset_id, {on}, created_at, id) WHERE {cond}"
    )


def create(conn: Connection, spec: FieldIndexSpec) -> None:
    """Build one index. On PostgreSQL `conn` must be in autocommit (it is built
    CONCURRENTLY, so saving records goes on meanwhile); on SQLite it holds the
    database for as long as it takes, like any write."""
    if conn.dialect.name == "postgresql":
        # Not listed by `existing` but maybe there, invalid: start again.
        conn.exec_driver_sql(f"DROP INDEX CONCURRENTLY IF EXISTS {spec.name}")
    conn.exec_driver_sql(create_sql(spec, conn.dialect))
    if conn.dialect.name == "postgresql":
        conn.exec_driver_sql(stats_sql(spec, conn.dialect))


def drop(conn: Connection, name: str) -> None:
    if field_of(name) is None:  # never anything but ours
        raise ValueError(f"'{name}' is not a managed field index")
    concurrently = " CONCURRENTLY" if conn.dialect.name == "postgresql" else ""
    conn.exec_driver_sql(f"DROP INDEX{concurrently} IF EXISTS {name}")
    if conn.dialect.name == "postgresql":
        conn.exec_driver_sql(f"DROP STATISTICS IF EXISTS {stats_name(name)}")
