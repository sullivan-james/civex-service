"""
Benchmark: composite B-tree + GIN index speed comparison on PostgreSQL.

Measures the same queries before and after adding:
  - ix_records_dataset_schema  (dataset_id, schema_id)
  - ix_records_dataset_created (dataset_id, created_at)
  - ix_records_dataset_parent  (dataset_id, parent_record_id)
  - ix_records_data_gin        USING GIN (data)

Usage:
    PG_URL=postgresql://user:pass@localhost/mydb python tests/bench_indexes.py [--records N]

The script drops and recreates its own tables, so the target DB must exist but
can be empty. It cleans up after itself.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

PG_URL = os.environ.get("PG_URL", "postgresql://civex:civex@localhost/civex_bench")
DEFAULT_N = 100_000
QUERY_REPS = 7
BATCH_SIZE = 2_000

SITES = ["SiteAlpha", "SiteBeta", "SiteGamma", "SiteDelta"]
STATUSES = ["active", "inactive", "pending", "enrolled"]


# ---------------------------------------------------------------------------
# DDL helpers
# ---------------------------------------------------------------------------

_SETUP_DDL = """
CREATE TABLE IF NOT EXISTS bm_schemas (
    id UUID PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS bm_datasets (
    id UUID PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS bm_records (
    id UUID PRIMARY KEY,
    dataset_id UUID NOT NULL REFERENCES bm_datasets(id),
    schema_id  UUID NOT NULL REFERENCES bm_schemas(id),
    parent_record_id UUID REFERENCES bm_records(id),
    data JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""

_TEARDOWN_DDL = """
DROP TABLE IF EXISTS bm_records;
DROP TABLE IF EXISTS bm_datasets;
DROP TABLE IF EXISTS bm_schemas;
"""

_INDEX_DDL = [
    "CREATE INDEX ix_bm_dataset_schema  ON bm_records (dataset_id, schema_id)",
    "CREATE INDEX ix_bm_dataset_created ON bm_records (dataset_id, created_at)",
    "CREATE INDEX ix_bm_dataset_parent  ON bm_records (dataset_id, parent_record_id)",
    "CREATE INDEX ix_bm_data_gin        ON bm_records USING GIN (data)",
]

_DROP_INDEX_DDL = [
    "DROP INDEX IF EXISTS ix_bm_dataset_schema",
    "DROP INDEX IF EXISTS ix_bm_dataset_created",
    "DROP INDEX IF EXISTS ix_bm_dataset_parent",
    "DROP INDEX IF EXISTS ix_bm_data_gin",
]


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def seed(conn, schema_id: uuid.UUID, dataset_id: uuid.UUID, n: int) -> None:
    print(f"  Seeding {n:,} records in batches of {BATCH_SIZE:,}...")
    inserted = 0
    while inserted < n:
        batch_n = min(BATCH_SIZE, n - inserted)
        batch = [
            {
                "id": str(uuid.uuid4()),
                "dataset_id": str(dataset_id),
                "schema_id": str(schema_id),
                "data": json.dumps({
                    "subject_id": f"S{random.randint(1, 2000):04d}",
                    "site": random.choice(SITES),
                    "status": random.choice(STATUSES),
                    "age": random.randint(18, 90),
                    "score": round(random.uniform(0.0, 100.0), 2),
                }),
            }
            for _ in range(batch_n)
        ]
        conn.execute(
            text(
                "INSERT INTO bm_records (id, dataset_id, schema_id, data) "
                "VALUES (:id, :dataset_id, :schema_id, CAST(:data AS jsonb))"
            ),
            batch,
        )
        inserted += batch_n
        print(f"    {inserted:,}/{n:,}", end="\r")
    print()


# ---------------------------------------------------------------------------
# Query definitions (mirror the real record_repo patterns)
# ---------------------------------------------------------------------------

def q_gin_field_eq(conn, dataset_id: uuid.UUID, schema_id: uuid.UUID) -> int:
    """
    Exact match on a JSONB field using @> containment.
    On PostgreSQL this uses the GIN index; without it PostgreSQL falls back to Seq Scan.
    """
    row = conn.execute(
        text(
            "SELECT COUNT(*) FROM bm_records "
            "WHERE dataset_id = :did AND schema_id = :sid "
            "AND data @> '{\"site\": \"SiteAlpha\"}'::jsonb"
        ),
        {"did": str(dataset_id), "sid": str(schema_id)},
    ).scalar()
    return row


def q_btree_list(conn, dataset_id: uuid.UUID, schema_id: uuid.UUID) -> int:
    """
    Composite filter + ordered page — the typical list_filtered() hot path.
    Uses the (dataset_id, schema_id) B-tree index, then (dataset_id, created_at) for ORDER BY.
    """
    rows = conn.execute(
        text(
            "SELECT id FROM bm_records "
            "WHERE dataset_id = :did AND schema_id = :sid "
            "ORDER BY created_at LIMIT 50"
        ),
        {"did": str(dataset_id), "sid": str(schema_id)},
    ).fetchall()
    return len(rows)


def q_btree_count(conn, dataset_id: uuid.UUID, schema_id: uuid.UUID) -> int:
    """COUNT(*) used by the pagination header — same composite filter."""
    row = conn.execute(
        text(
            "SELECT COUNT(*) FROM bm_records "
            "WHERE dataset_id = :did AND schema_id = :sid"
        ),
        {"did": str(dataset_id), "sid": str(schema_id)},
    ).scalar()
    return row


# ---------------------------------------------------------------------------
# Timing + EXPLAIN
# ---------------------------------------------------------------------------

def measure(conn, fn, reps: int) -> float:
    """Return the median wall time in ms."""
    times = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn(conn)
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    return times[len(times) // 2]  # median


def explain(conn, sql: str, params: dict) -> list[str]:
    rows = conn.execute(text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {sql}"), params).fetchall()
    return [r[0] for r in rows]


def print_explain(conn, dataset_id: uuid.UUID, schema_id: uuid.UUID) -> None:
    lines = explain(
        conn,
        "SELECT COUNT(*) FROM bm_records "
        "WHERE dataset_id = :did AND schema_id = :sid "
        "AND data @> '{\"site\": \"SiteAlpha\"}'::jsonb",
        {"did": str(dataset_id), "sid": str(schema_id)},
    )
    for line in lines[:12]:  # cap output length
        print(f"    {line}")
    if len(lines) > 12:
        print(f"    ... ({len(lines) - 12} more lines)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--records", type=int, default=DEFAULT_N, metavar="N",
                        help=f"Number of records to seed (default: {DEFAULT_N:,})")
    parser.add_argument("--url", default=PG_URL,
                        help="PostgreSQL connection URL (default: $PG_URL or civex:civex@localhost/civex_bench)")
    args = parser.parse_args()

    try:
        engine = create_engine(args.url, echo=False)
        with engine.connect() as probe:
            probe.execute(text("SELECT 1"))
    except Exception as exc:
        print(f"Cannot connect to PostgreSQL: {exc}")
        print("Set PG_URL=postgresql://user:pass@host/db or pass --url")
        sys.exit(1)

    print(f"\nPostgreSQL benchmark — {args.records:,} records, {QUERY_REPS} reps per measurement\n")

    schema_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    with engine.begin() as conn:
        conn.execute(text(_TEARDOWN_DDL))
        conn.execute(text(_SETUP_DDL))
        conn.execute(text("INSERT INTO bm_schemas  VALUES (:id, 'Encounter')"), {"id": str(schema_id)})
        conn.execute(text("INSERT INTO bm_datasets VALUES (:id, 'Study2024')"), {"id": str(dataset_id)})

    with engine.begin() as conn:
        seed(conn, schema_id, dataset_id, args.records)

    with engine.begin() as conn:
        conn.execute(text("ANALYZE bm_records"))

    # ---- WITHOUT indexes ----
    print("=" * 60)
    print("BEFORE indexes")
    print("=" * 60)

    with engine.connect() as conn:
        print("\nEXPLAIN ANALYZE — GIN field-equality query:")
        print_explain(conn, dataset_id, schema_id)

        t_gin_before    = measure(conn, lambda c: q_gin_field_eq(c, dataset_id, schema_id), QUERY_REPS)
        t_list_before   = measure(conn, lambda c: q_btree_list(c, dataset_id, schema_id),   QUERY_REPS)
        t_count_before  = measure(conn, lambda c: q_btree_count(c, dataset_id, schema_id),  QUERY_REPS)

    print(f"\n  GIN field-equality (data @> ...)    {t_gin_before:>8.1f} ms  (median)")
    print(f"  B-tree list  (WHERE + ORDER LIMIT)  {t_list_before:>8.1f} ms  (median)")
    print(f"  B-tree count (WHERE COUNT(*))        {t_count_before:>8.1f} ms  (median)")

    # ---- ADD indexes ----
    print(f"\n{'─'*60}")
    print("Adding indexes...")
    with engine.begin() as conn:
        for ddl in _INDEX_DDL:
            conn.execute(text(ddl))
        conn.execute(text("ANALYZE bm_records"))
    print("Done.\n")

    # ---- WITH indexes ----
    print("=" * 60)
    print("AFTER indexes")
    print("=" * 60)

    with engine.connect() as conn:
        print("\nEXPLAIN ANALYZE — GIN field-equality query:")
        print_explain(conn, dataset_id, schema_id)

        t_gin_after    = measure(conn, lambda c: q_gin_field_eq(c, dataset_id, schema_id), QUERY_REPS)
        t_list_after   = measure(conn, lambda c: q_btree_list(c, dataset_id, schema_id),   QUERY_REPS)
        t_count_after  = measure(conn, lambda c: q_btree_count(c, dataset_id, schema_id),  QUERY_REPS)

    print(f"\n  GIN field-equality (data @> ...)    {t_gin_after:>8.1f} ms  (median)")
    print(f"  B-tree list  (WHERE + ORDER LIMIT)  {t_list_after:>8.1f} ms  (median)")
    print(f"  B-tree count (WHERE COUNT(*))        {t_count_after:>8.1f} ms  (median)")

    # ---- Summary ----
    def speedup(before: float, after: float) -> str:
        if after == 0:
            return "∞"
        ratio = before / after
        return f"{ratio:.1f}x faster" if ratio >= 1 else f"{1/ratio:.1f}x slower"

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    print(f"  {'Query':<40} {'Before':>8}   {'After':>8}   {'Speedup'}")
    print(f"  {'-'*40}   {'-'*8}   {'-'*8}   {'-'*15}")
    print(f"  {'GIN field-equality':<40} {t_gin_before:>7.1f}ms   {t_gin_after:>7.1f}ms   {speedup(t_gin_before, t_gin_after)}")
    print(f"  {'B-tree list (ORDER BY LIMIT 50)':<40} {t_list_before:>7.1f}ms   {t_list_after:>7.1f}ms   {speedup(t_list_before, t_list_after)}")
    print(f"  {'B-tree count':<40} {t_count_before:>7.1f}ms   {t_count_after:>7.1f}ms   {speedup(t_count_before, t_count_after)}")

    # ---- Cleanup ----
    print(f"\n{'─'*60}")
    print("Cleaning up benchmark tables...")
    with engine.begin() as conn:
        conn.execute(text(_TEARDOWN_DDL))
    print("Done.\n")


if __name__ == "__main__":
    main()
