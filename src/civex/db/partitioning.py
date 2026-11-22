"""Table partitioning for `records` and `audit_log` on PostgreSQL.

Why, and what was measured: docs/contributing/billion-row-collections.md. In
short, a single table of hundreds of millions of rows is not slow to read (the
indexes bound that) but is slow and risky to *maintain* (rebuilding a GIN
index, vacuuming, bulk-loading), and a partition is the unit those operate on.

Layouts (SQLite is never partitioned: it is single-user and has no support):

- `records`: `PARTITION BY HASH (id)` with a configurable modulus
  (`PartitionLayout.records_partitions`, default 8; 0 or 1 = a plain table).
  The primary key is still `(id)` (it contains the partition key), so the
  unique `(id, dataset_id)`, the deferred composite self-FK and the four foreign
  keys from other tables onto `records.id` all stay valid, and every index
  (partial B-trees, both GINs) is kept as a partitioned index. Hash by `id`,
  not `dataset_id`: see the design note for why.
- `audit_log`: `PARTITION BY RANGE ("timestamp")`, one partition per month,
  plus a DEFAULT partition for anything outside the created months (a device's
  clock, an old import) so no write is ever refused. The primary key becomes
  `(id, timestamp)`. `hub_seq` never had a database-level unique index (it is
  a plain index; uniqueness comes from the counter `sync_meta.head_seq`, bumped
  atomically in the database), so nothing is lost by partitioning. See
  `ensure_audit_partitions` for creating future months.

Converting an existing table (`partition_records`, `partition_audit_log`) runs
in the caller's transaction: it is atomic, so a failure leaves the old table
exactly as it was. Writers are blocked from the start (SHARE ROW EXCLUSIVE),
readers only for the final swap. The data is copied once with the secondary
indexes and foreign keys built on the new table *before* the swap, so the
exclusive window is a DROP plus a few renames.

Everything here looks tables up through the connection's `search_path`, so it
works unchanged for civex-hub's schema-per-repository layout.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import OperationalError

DEFAULT_RECORDS_PARTITIONS = 8
DEFAULT_AUDIT_MONTHS_AHEAD = 2
# History older than this many months before the first month created goes in
# one "early" partition instead of a partition per month.
AUDIT_BACKFILL_MONTHS = 24
EARLY_PARTITION = "audit_log_early"

# How long a conversion waits for a lock before giving up (and rolling back,
# leaving the old table in place) instead of queueing everyone behind it.
LOCK_TIMEOUT = "120s"

ENV_RECORDS = "CIVEX_RECORDS_PARTITIONS"
ENV_AUDIT = "CIVEX_AUDIT_PARTITIONS"
ENV_AUDIT_AHEAD = "CIVEX_AUDIT_MONTHS_AHEAD"

_OFF = {"", "0", "1", "off", "none", "false", "no"}


@dataclass(frozen=True)
class PartitionLayout:
    """Which partitioned layout a PostgreSQL database gets when it is migrated.

    Only read when the migration runs (once per database): changing it later
    does not re-layout an existing database; call `partition_records` for that.
    """

    records_partitions: int = DEFAULT_RECORDS_PARTITIONS  # < 2: plain table
    audit_monthly: bool = True
    audit_months_ahead: int = DEFAULT_AUDIT_MONTHS_AHEAD

    @classmethod
    def for_config(cls, db, environ: dict[str, str] | None = None) -> PartitionLayout:
        """The layout a project's `[db]` section asks for (`db`: civex.config.DBConfig),
        else the environment's. Every place that migrates a project's database
        takes its layout from here."""
        layout = cls.from_env(environ)
        if getattr(db, "records_partitions", None) is not None:
            layout = replace(layout, records_partitions=int(db.records_partitions))
        return layout

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> PartitionLayout:
        env = os.environ if environ is None else environ
        records = env.get(ENV_RECORDS, "").strip().lower()
        audit = env.get(ENV_AUDIT, "").strip().lower()
        ahead = env.get(ENV_AUDIT_AHEAD, "").strip()
        return cls(
            records_partitions=(
                DEFAULT_RECORDS_PARTITIONS
                if not records
                else 0
                if records in _OFF
                else int(records)
            ),
            audit_monthly=audit not in {"off", "none", "false", "no", "0"},
            audit_months_ahead=int(ahead) if ahead else DEFAULT_AUDIT_MONTHS_AHEAD,
        )


# --- catalog helpers -------------------------------------------------------


def _q(conn: Connection, name: str) -> str:
    return conn.dialect.identifier_preparer.quote(name)


def _oid(conn: Connection, table: str) -> int | None:
    return conn.execute(
        text("SELECT to_regclass(:n)::oid"), {"n": _q(conn, table)}
    ).scalar()


def _relkind(conn: Connection, table: str) -> str | None:
    return conn.execute(
        text("SELECT relkind FROM pg_class WHERE oid = to_regclass(:n)"),
        {"n": _q(conn, table)},
    ).scalar()


def is_partitioned(conn: Connection, table: str) -> bool:
    return _relkind(conn, table) == "p"


def partitions_of(conn: Connection, table: str) -> list[str]:
    """Names of `table`'s partitions (empty for a plain table)."""
    rows = conn.execute(
        text(
            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
            "WHERE i.inhparent = to_regclass(:n) ORDER BY c.relname"
        ),
        {"n": _q(conn, table)},
    )
    return [r[0] for r in rows]


def _tmp_name(name: str) -> str:
    """A name for the new table's copy of `name` while the old one still exists."""
    return (
        name
        if len(name) <= 58
        else name[:50] + hashlib.md5(name.encode()).hexdigest()[:8]
    ) + "__n"


_ON = re.compile(r"\bON (?:ONLY )?(\S+) USING ")


@dataclass
class _Captured:
    indexes: list[tuple[str, str]]  # (name, CREATE INDEX statement)
    constraints: list[tuple[str, str, str]]  # (name, contype, definition)
    referencing: list[tuple[str, str, str]]  # (child table, name, definition)
    triggers: list[str]


def _capture(conn: Connection, table: str) -> _Captured:
    """The definitions to carry over, read from the catalog so nothing here can
    drift from what the table actually has."""
    oid = _oid(conn, table)
    indexes = [
        (r[0], r[1])
        for r in conn.execute(
            text(
                """
                SELECT ic.relname, pg_get_indexdef(i.indexrelid)
                FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid
                WHERE i.indrelid = :oid
                  AND NOT EXISTS (
                      SELECT 1 FROM pg_constraint c
                      WHERE c.conindid = i.indexrelid AND c.conrelid = i.indrelid
                        AND c.contype IN ('p', 'u', 'x'))
                ORDER BY ic.relname
                """
            ),
            {"oid": oid},
        )
    ]
    constraints = [
        (r[0], r[1], r[2])
        for r in conn.execute(
            text(
                """
                SELECT conname, contype::text, pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conrelid = :oid AND conparentid = 0
                  AND contype IN ('p', 'u', 'c', 'f')
                ORDER BY CASE contype WHEN 'p' THEN 0 WHEN 'u' THEN 1
                                      WHEN 'c' THEN 2 ELSE 3 END, conname
                """
            ),
            {"oid": oid},
        )
    ]
    referencing = [
        (r[0], r[1], r[2])
        for r in conn.execute(
            text(
                """
                SELECT c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid)
                FROM pg_constraint c
                WHERE c.confrelid = :oid AND c.conparentid = 0 AND c.contype = 'f'
                  AND c.conrelid <> :oid
                ORDER BY 1, 2
                """
            ),
            {"oid": oid},
        )
    ]
    triggers = [
        r[0]
        for r in conn.execute(
            text(
                "SELECT pg_get_triggerdef(oid) FROM pg_trigger "
                "WHERE tgrelid = :oid AND NOT tgisinternal ORDER BY tgname"
            ),
            {"oid": oid},
        )
    ]
    return _Captured(indexes, constraints, referencing, triggers)


def _retarget(definition: str, old: str, new: str) -> str:
    """Point a captured `REFERENCES old(...)` at `new`."""
    return re.sub(
        r"REFERENCES (?:\S+\.)?" + re.escape(old) + r"\(",
        f"REFERENCES {new}(",
        definition,
    )


def _refuse_dependent_views(conn: Connection, table: str) -> None:
    views = conn.execute(
        text(
            """
            SELECT DISTINCT v.relname
            FROM pg_depend d
            JOIN pg_rewrite r ON r.oid = d.objid
            JOIN pg_class v ON v.oid = r.ev_class
            WHERE d.refobjid = to_regclass(:n) AND v.oid <> d.refobjid
            """
        ),
        {"n": _q(conn, table)},
    ).all()
    if views:
        raise RuntimeError(
            f"cannot re-lay out {table}: views depend on it "
            f"({', '.join(v[0] for v in views)}); drop them first"
        )


def _rebuild(
    conn: Connection,
    table: str,
    *,
    partition_by: str | None,
    partitions: Iterable[tuple[str, str]],
    pk: str,
) -> None:
    """Replace `table` with a copy laid out as `partition_by` (None = plain).

    `partitions` is (name, "FOR VALUES ...") pairs for the new table. `pk` is
    the primary key's column list. One transaction, caller's: see module doc.
    """
    new = f"{table}__new"
    qt, qn = _q(conn, table), _q(conn, new)
    old_lock = conn.execute(text("SELECT current_setting('lock_timeout')")).scalar()
    conn.execute(
        text("SELECT set_config('lock_timeout', :v, true)"), {"v": LOCK_TIMEOUT}
    )
    conn.execute(text(f"LOCK TABLE {qt} IN SHARE ROW EXCLUSIVE MODE"))
    _refuse_dependent_views(conn, table)
    cap = _capture(conn, table)
    # The tables with foreign keys onto this one are locked now too (their
    # constraints are redone at the end): a lock that cannot be had should
    # fail before the copy, not after it.
    for child in sorted({c for c, _, _ in cap.referencing}):
        conn.execute(text(f"LOCK TABLE {child} IN SHARE ROW EXCLUSIVE MODE"))

    clause = f" PARTITION BY {partition_by}" if partition_by else ""
    conn.execute(
        text(
            f"CREATE TABLE {qn} (LIKE {qt} INCLUDING DEFAULTS INCLUDING GENERATED "
            f"INCLUDING IDENTITY INCLUDING STORAGE INCLUDING COMMENTS){clause}"
        )
    )
    for name, bound in partitions:
        conn.execute(text(f"CREATE TABLE {_q(conn, name)} PARTITION OF {qn} {bound}"))
    # `SELECT *` follows the column order LIKE copied.
    conn.execute(text(f"INSERT INTO {qn} SELECT * FROM {qt}"))

    # Everything the old table had, under temporary names, so the old table's
    # names stay free until the swap.
    renames: list[str] = []
    for name, ctype, definition in cap.constraints:
        if ctype == "p":
            definition = f"PRIMARY KEY ({pk})"
        tmp = _tmp_name(name)
        conn.execute(
            text(
                f"ALTER TABLE {qn} ADD CONSTRAINT {_q(conn, tmp)} "
                f"{_retarget(definition, table, qn)}"
            )
        )
        renames.append(
            f"ALTER TABLE {qt} RENAME CONSTRAINT {_q(conn, tmp)} TO {_q(conn, name)}"
        )
    for name, definition in cap.indexes:
        tmp = _tmp_name(name)
        stmt = re.sub(
            r"INDEX (\S+) ON ", f"INDEX {_q(conn, tmp)} ON ", definition, count=1
        )
        stmt = _ON.sub(f"ON {qn} USING ", stmt, count=1)
        conn.execute(text(stmt))
        renames.append(f"ALTER INDEX {_q(conn, tmp)} RENAME TO {_q(conn, name)}")
    # Foreign keys from other tables are created (and validated) against the
    # new table now, while the old constraints still guard the old one.
    for child, name, definition in cap.referencing:
        tmp = _tmp_name(name)
        conn.execute(
            text(
                f"ALTER TABLE {child} ADD CONSTRAINT {_q(conn, tmp)} "
                f"{_retarget(definition, table, qn)}"
            )
        )
        renames.append(
            f"ALTER TABLE {child} RENAME CONSTRAINT {_q(conn, tmp)} TO {_q(conn, name)}"
        )

    # The swap. CASCADE only removes the old foreign keys that pointed at it
    # (views were refused above).
    conn.execute(text(f"DROP TABLE {qt} CASCADE"))
    conn.execute(text(f"ALTER TABLE {qn} RENAME TO {qt}"))
    for stmt in renames:
        conn.execute(text(stmt))
    for trigger in cap.triggers:
        conn.execute(text(trigger))
    conn.execute(text("SELECT set_config('lock_timeout', :v, true)"), {"v": old_lock})
    conn.execute(text(f"ANALYZE {qt}"))


# --- records ---------------------------------------------------------------


def partition_records(conn: Connection, modulus: int) -> bool:
    """Lay `records` out as HASH (id) x `modulus`; True if it changed anything.

    No-op for `modulus` < 2 or when already partitioned. An empty table (a new
    repository) converts in milliseconds; a populated one is copied once, see
    the module doc for the cost.
    """
    if conn.dialect.name != "postgresql" or modulus < 2:
        return False
    if _relkind(conn, "records") != "r":
        return False
    _rebuild(
        conn,
        "records",
        partition_by="HASH (id)",
        partitions=[
            (
                f"records_p{n}",
                f"FOR VALUES WITH (MODULUS {modulus}, REMAINDER {n})",
            )
            for n in range(modulus)
        ],
        pk="id",
    )
    return True


def unpartition_records(conn: Connection) -> bool:
    if conn.dialect.name != "postgresql" or not is_partitioned(conn, "records"):
        return False
    _rebuild(conn, "records", partition_by=None, partitions=[], pk="id")
    return True


# --- audit_log -------------------------------------------------------------


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _add_months(d: date, n: int) -> date:
    index = d.year * 12 + (d.month - 1) + n
    return date(index // 12, index % 12 + 1, 1)


def _month_bound(d: date) -> str:
    return f"'{d.isoformat()} 00:00:00+00'"


def _month_name(d: date) -> str:
    return f"audit_log_y{d.year}m{d.month:02d}"


def _month_range(d: date) -> str:
    return f"FOR VALUES FROM ({_month_bound(d)}) TO ({_month_bound(_add_months(d, 1))})"


def partition_audit_log(
    conn: Connection,
    months_ahead: int = DEFAULT_AUDIT_MONTHS_AHEAD,
    now: datetime | None = None,
) -> bool:
    """Lay `audit_log` out by month on `timestamp`; True if it changed anything.

    Creates a partition for each month from the oldest entry (at most
    AUDIT_BACKFILL_MONTHS back) to
    `months_ahead` past now, and a DEFAULT partition for whatever falls outside
    them (entries dated in the future stay there until `ensure_audit_partitions`
    reaches their month and moves them). Entries older than the first month
    share `audit_log_early`.
    """
    if conn.dialect.name != "postgresql":
        return False
    if _relkind(conn, "audit_log") != "r":
        return False
    today = _month_start((now or datetime.now(timezone.utc)).date())
    lo = conn.execute(text('SELECT min("timestamp") FROM audit_log')).scalar_one()
    first = today
    if lo is not None:
        first = min(today, _month_start(lo.astimezone(timezone.utc).date()))
    first = max(first, _add_months(today, -AUDIT_BACKFILL_MONTHS))
    # Everything dated before the first month lands in `early`, so history that
    # arrives with old timestamps (a device pushing years of entries, an
    # import) never goes to the default partition, which stays for the future.
    parts: list[tuple[str, str]] = [
        (
            EARLY_PARTITION,
            f"FOR VALUES FROM (MINVALUE) TO ({_month_bound(first)})",
        )
    ]
    month = first
    while month <= _add_months(today, months_ahead):
        parts.append((_month_name(month), _month_range(month)))
        month = _add_months(month, 1)
    parts.append(("audit_log_default", "DEFAULT"))
    _rebuild(
        conn,
        "audit_log",
        partition_by='RANGE ("timestamp")',
        partitions=parts,
        pk='id, "timestamp"',
    )
    return True


def unpartition_audit_log(conn: Connection) -> bool:
    if conn.dialect.name != "postgresql" or not is_partitioned(conn, "audit_log"):
        return False
    _rebuild(conn, "audit_log", partition_by=None, partitions=[], pk="id")
    return True


def ensure_audit_partitions(
    target: Engine | Connection,
    months_ahead: int | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Create the monthly `audit_log` partitions from this month through
    `months_ahead` months from now (default 2) that don't exist yet; return
    the names created.

    Call it periodically from the host (daily is plenty; it is a handful of
    catalog lookups when nothing is missing) and civex calls it each time a
    database is migrated. A host that forgets is safe, not broken: rows for a
    month with no partition go to `audit_log_default`, and the next call moves
    them into the month's new partition. Does nothing on SQLite or when
    `audit_log` is not partitioned. Safe to call from several processes at once.

    `target` is an Engine (opens its own transaction) or a Connection (runs in
    the caller's).
    """
    if isinstance(target, Engine):
        if target.dialect.name != "postgresql":
            return []
        with target.begin() as conn:
            return ensure_audit_partitions(conn, months_ahead, now)
    conn = target
    if conn.dialect.name != "postgresql" or not is_partitioned(conn, "audit_log"):
        return []
    ahead = DEFAULT_AUDIT_MONTHS_AHEAD if months_ahead is None else months_ahead
    today = _month_start((now or datetime.now(timezone.utc)).date())
    wanted = [_add_months(today, i) for i in range(ahead + 1)]
    existing = set(partitions_of(conn, "audit_log"))
    missing = [m for m in wanted if _month_name(m) not in existing]
    if not missing:
        return []
    # One creator at a time per schema; the second finds them made. A short
    # lock timeout: creating a partition needs a lock on `audit_log` that a
    # busy writer can hold off, and this may run on a request's path. Giving
    # up is harmless (rows go to the default partition and the next call
    # moves them in), so it is reported as "nothing created".
    try:
        with conn.begin_nested():
            return _create_months(conn, missing)
    except OperationalError as exc:
        if "lock timeout" in str(exc) or "could not obtain lock" in str(exc):
            return []
        raise


def _create_months(conn: Connection, missing: list[date]) -> list[str]:
    previous = conn.execute(text("SELECT current_setting('lock_timeout')")).scalar()
    conn.execute(text("SELECT set_config('lock_timeout', '3s', true)"))
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(current_schema() || '.audit_log'))")
    )
    existing = set(partitions_of(conn, "audit_log"))
    created: list[str] = []
    has_default = "audit_log_default" in existing
    for month in missing:
        name = _month_name(month)
        if name in existing:
            continue
        nxt = _add_months(month, 1)
        stray = 0
        if has_default:
            stray = conn.execute(
                text(
                    'SELECT count(*) FROM (SELECT 1 FROM audit_log_default WHERE "timestamp" >= '
                    f'{_month_bound(month)} AND "timestamp" < {_month_bound(nxt)} LIMIT 1) s'
                )
            ).scalar_one()
        if not stray:
            conn.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS {_q(conn, name)} "
                    f"PARTITION OF audit_log {_month_range(month)}"
                )
            )
        else:
            # Rows for this month were written before it existed. Move them
            # into the new partition, then attach it (attaching checks that
            # the default partition holds none of its range, hence the move).
            conn.execute(
                text(
                    f"CREATE TABLE {_q(conn, name)} (LIKE audit_log INCLUDING DEFAULTS)"
                )
            )
            conn.execute(
                text(
                    f'WITH moved AS (DELETE FROM audit_log_default WHERE "timestamp" >= '
                    f'{_month_bound(month)} AND "timestamp" < {_month_bound(nxt)} RETURNING *) '
                    f"INSERT INTO {_q(conn, name)} SELECT * FROM moved"
                )
            )
            conn.execute(
                text(
                    f"ALTER TABLE audit_log ATTACH PARTITION {_q(conn, name)} "
                    f"{_month_range(month)}"
                )
            )
        created.append(name)
    conn.execute(text("SELECT set_config('lock_timeout', :v, true)"), {"v": previous})
    return created
