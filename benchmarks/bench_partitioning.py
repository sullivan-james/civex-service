"""Partitioned vs plain `records` on PostgreSQL: a trimmed version of bench_scale.py.

Seeds one repository schema with `--rows` records laid out as a plain table,
measures it, converts it in place with `civex.db.partitioning.partition_records`
(timing the conversion and its WAL: this is the migration's cost on a populated
repository), and measures the same data again partitioned. Prints one JSON
document.

    createdb civex_bench
    PG_URL=postgresql+psycopg2://user@localhost:5432/civex_bench \\
      .venv/bin/python benchmarks/bench_partitioning.py --rows 5000000 --out part.json

The schema is dropped at the end. Not part of the product or the test suite.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
import uuid

from sqlalchemy import create_engine, text

from civex.db import partitioning
from civex.db.migrate import ensure_schema_current
from civex.domain.ids import row_id, uuid7

FIELDS = [uuid.uuid4().hex for _ in range(8)]
HOT_SHARE = 57  # percent of rows in one collection
COLLECTIONS = 200


def _wal(conn) -> int:
    return float(
        conn.execute(
            text("SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0')")
        ).scalar_one()
    )


def seed(conn, rows: int, datasets: list, schema_id) -> float:
    start = time.time()
    conn.execute(text("ALTER TABLE records DISABLE TRIGGER USER"))
    pairs = ", ".join(
        f"'{k}', md5(g::text || '{k[:4]}') || md5(g::text || '{k[4:8]}') || md5(g::text)"
        for k in FIELDS[1:]
    )
    chunk = 500_000
    for lo in range(0, rows, chunk):
        hi = min(rows, lo + chunk)
        conn.execute(
            text(
                f"""
                INSERT INTO records (id, dataset_id, schema_id, data, created_at, updated_at,
                                     deleted_at, search_vector)
                SELECT gen_random_uuid(),
                       CASE WHEN g % 100 < {HOT_SHARE} THEN (CAST(:d AS uuid[]))[1]
                            ELSE (CAST(:d AS uuid[]))[2 + g % {COLLECTIONS - 1}] END,
                       :s, d.data, ts, ts,
                       CASE WHEN g % 50 = 7 THEN ts END,
                       to_tsvector('simple', d.words)
                FROM generate_series({lo}, {hi - 1}) g,
                LATERAL (SELECT timestamptz '2025-01-01' + g * interval '3 seconds' AS ts) t,
                LATERAL (SELECT jsonb_build_object('{FIELDS[0]}', 'u' || g, 'tag', 't' || (g % 1000), {pairs}) AS data,
                                'u' || g || ' t' || (g % 1000) AS words) d
                """
            ),
            {"d": datasets, "s": schema_id},
        )
        conn.commit()
    conn.execute(text("ALTER TABLE records ENABLE TRIGGER USER"))
    conn.commit()
    return time.time() - start


def timed(conn, sql: str, params: dict | None = None, runs: int = 7) -> dict:
    conn.execute(text(sql), params or {}).all()  # warm
    out = []
    for _ in range(runs):
        t = time.perf_counter()
        conn.execute(text(sql), params or {}).all()
        out.append((time.perf_counter() - t) * 1000)
    return {"median_ms": round(statistics.median(out), 2), "max_ms": round(max(out), 2)}


def read_suite(engine, hot, small, sample_ids) -> dict:
    res: dict = {}
    with engine.connect() as c:
        c.execute(text("ANALYZE records"))
        cursors = c.execute(
            text(
                "SELECT created_at, id FROM records WHERE dataset_id = :d AND deleted_at IS NULL "
                "ORDER BY created_at, id OFFSET :o LIMIT 1"
            ),
            {
                "d": hot,
                "o": max(
                    1,
                    int(
                        c.execute(
                            text("SELECT count(*) FROM records WHERE dataset_id = :d"),
                            {"d": hot},
                        ).scalar_one()
                        * 0.4
                    ),
                ),
            },
        ).one()
        keyset = (
            "SELECT id, data FROM records WHERE dataset_id = :d AND deleted_at IS NULL "
            "AND (created_at, id) > (:c, :i) ORDER BY created_at, id LIMIT 50"
        )
        res["keyset_page_hot"] = timed(
            c, keyset, {"d": hot, "c": cursors[0], "i": cursors[1]}
        )
        res["keyset_page_first_hot"] = timed(
            c,
            "SELECT id, data FROM records WHERE dataset_id = :d AND deleted_at IS NULL "
            "ORDER BY created_at, id LIMIT 50",
            {"d": hot},
        )
        res["keyset_page_small"] = timed(
            c,
            "SELECT id, data FROM records WHERE dataset_id = :d AND deleted_at IS NULL "
            "ORDER BY created_at, id LIMIT 50",
            {"d": small},
        )
        t = time.perf_counter()
        for rid in sample_ids:
            c.execute(text("SELECT * FROM records WHERE id = :i"), {"i": rid}).all()
        res["lookup_by_id_median_ms"] = round(
            (time.perf_counter() - t) * 1000 / len(sample_ids), 3
        )
        res["gin_contains_page"] = timed(
            c,
            "SELECT id FROM records WHERE dataset_id = :d AND data @> CAST(:q AS jsonb) LIMIT 50",
            {"d": hot, "q": json.dumps({"tag": "t42"})},
        )
        res["gin_contains_count"] = timed(
            c,
            "SELECT count(*) FROM records WHERE dataset_id = :d AND data @> CAST(:q AS jsonb)",
            {"d": hot, "q": json.dumps({"tag": "t42"})},
            runs=3,
        )
        res["gin_rare_value_whole_table"] = timed(
            c,
            "SELECT id FROM records WHERE data @> CAST(:q AS jsonb)",
            {"q": json.dumps({FIELDS[0]: "u123457"})},
        )
        res["fulltext_rare_word"] = timed(
            c,
            "SELECT id FROM records WHERE dataset_id = :d AND search_vector @@ to_tsquery('simple', 'u123457') LIMIT 20",
            {"d": hot},
        )
        res["exact_count_hot"] = timed(
            c,
            "SELECT count(*) FROM records WHERE dataset_id = :d AND deleted_at IS NULL",
            {"d": hot},
            runs=2,
        )
        c.rollback()
    return res


def insert_suite(engine, hot, schema_id, n: int) -> dict:
    """n inserts through the live indexes and trigger: v4, pure v7 and row_id ids."""
    out: dict = {}
    for label, make in (("uuid4", uuid.uuid4), ("uuid7", uuid7), ("row_id", row_id)):
        raw = engine.raw_connection()
        try:
            cur = raw.cursor()
            cur.execute("CHECKPOINT")
            cur.execute("SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0')")
            w0 = float(cur.fetchone()[0])
            t = time.perf_counter()
            for lo in range(0, n, 5000):
                rows = [
                    (
                        str(make()),
                        str(hot),
                        str(schema_id),
                        json.dumps(
                            {
                                "tag": f"t{(lo + i) % 1000}",
                                FIELDS[0]: f"x{label}{lo + i}",
                                "p": "y" * 200,
                            }
                        ),
                    )
                    for i in range(min(5000, n - lo))
                ]
                args = b",".join(
                    cur.mogrify("(%s::uuid,%s::uuid,%s::uuid,%s::jsonb,now(),now())", r)
                    for r in rows
                )
                cur.execute(
                    b"INSERT INTO records (id, dataset_id, schema_id, data, created_at, updated_at) VALUES "
                    + args
                )
                raw.commit()
            secs = time.perf_counter() - t
            cur.execute("SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0')")
            w1 = float(cur.fetchone()[0])
        finally:
            raw.close()
        out[label] = {
            "rows_per_s": round(n / secs),
            "wal_bytes_per_row": round((w1 - w0) / n),
        }
    return out


def audit_suite(engine, rows: int) -> dict:
    """Seed a plain audit_log (indexes live), convert it, time both sides."""
    out: dict = {}
    t = time.time()
    with engine.begin() as c:
        c.execute(
            text(
                f"""
                INSERT INTO audit_log (id, action, entity_type, entity_id, new_data, timestamp,
                                       hub_seq, sync_state, format)
                SELECT gen_random_uuid(), 'update', 'record', gen_random_uuid(),
                       jsonb_build_object('a', g), now() - (g * interval '80 seconds'),
                       g, 'synced', 2
                FROM generate_series(1, {rows}) g
                """
            )
        )
    out["seed_s"] = round(time.time() - t, 1)
    with engine.execution_options(isolation_level="AUTOCOMMIT").connect() as c:
        c.execute(text("VACUUM (ANALYZE) audit_log"))
    out["plain_reads"] = _audit_reads(engine)
    raw = engine.connect()
    w0 = _wal(raw)
    raw.rollback()
    t = time.time()
    with raw.begin():
        partitioning.partition_audit_log(raw)
    out["conversion"] = {
        "seconds": round(time.time() - t, 1),
        "wal_gb": round((_wal(raw) - w0) / 1e9, 2),
    }
    raw.close()
    with engine.execution_options(isolation_level="AUTOCOMMIT").connect() as c:
        c.execute(text("VACUUM (ANALYZE) audit_log"))
    with engine.connect() as c:
        out["partitions"] = len(partitioning.partitions_of(c, "audit_log"))
    out["partitioned_reads"] = _audit_reads(engine)
    return out


def _audit_reads(engine) -> dict:
    res: dict = {}
    with engine.connect() as c:
        head = c.execute(text("SELECT max(hub_seq) FROM audit_log")).scalar_one()
        res["head_hub_seq"] = timed(c, "SELECT max(hub_seq) FROM audit_log")
        res["feed_1000_after_mid"] = timed(
            c,
            "SELECT id FROM audit_log WHERE hub_seq > :s ORDER BY hub_seq LIMIT 1000",
            {"s": head // 2},
        )
        res["history_of_one_entity"] = timed(
            c,
            "SELECT id FROM audit_log WHERE entity_id = (SELECT entity_id FROM audit_log "
            "WHERE hub_seq = :s) ORDER BY timestamp",
            {"s": head // 3},
        )
        res["one_day_count"] = timed(
            c,
            "SELECT count(*) FROM audit_log WHERE timestamp >= now() - interval '3 days' "
            "AND timestamp < now() - interval '2 days'",
        )
        c.rollback()
    return res


def catalog(engine) -> dict:
    with engine.connect() as c:
        rels = c.execute(
            text(
                "SELECT count(*) FROM pg_class WHERE relnamespace = current_schema()::regnamespace"
            )
        ).scalar_one()
        attrs = c.execute(
            text(
                "SELECT count(*) FROM pg_attribute a JOIN pg_class r ON r.oid = a.attrelid "
                "WHERE r.relnamespace = current_schema()::regnamespace"
            )
        ).scalar_one()
        return {"pg_class_rows": rels, "pg_attribute_rows": attrs}


def locks_for_keyset(engine, hot) -> int:
    with engine.connect() as c:
        c.execute(
            text(
                "SELECT id FROM records WHERE dataset_id = :d ORDER BY created_at LIMIT 50"
            ),
            {"d": hot},
        ).all()
        n = c.execute(
            text(
                "SELECT count(*) FROM pg_locks WHERE pid = pg_backend_pid() AND locktype = 'relation'"
            )
        ).scalar_one()
        c.rollback()
        return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=5_000_000)
    ap.add_argument("--inserts", type=int, default=100_000)
    ap.add_argument("--modulus", type=int, default=8)
    ap.add_argument(
        "--audit-rows", type=int, default=0, help="also convert an audit_log this big"
    )
    ap.add_argument("--out")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    url = os.environ["PG_URL"]
    name = f"bench_{uuid.uuid4().hex[:8]}"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"CREATE SCHEMA {name}"))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={name}"})
    report: dict = {"rows": args.rows, "modulus": args.modulus}
    try:
        # Empty-repository catalog cost, plain vs default layout.
        ensure_schema_current(
            engine,
            partitioning.PartitionLayout(records_partitions=1, audit_monthly=False),
        )
        report["catalog_plain_empty"] = catalog(engine)
        schema_id = uuid.uuid4()
        datasets = [uuid.uuid4() for _ in range(COLLECTIONS)]
        with engine.begin() as c:
            c.execute(
                text(
                    "INSERT INTO schemas (id, name, created_at) VALUES (:i, 's', now())"
                ),
                {"i": schema_id},
            )
            for n, d in enumerate(datasets):
                c.execute(
                    text(
                        "INSERT INTO datasets (id, name, created_at) VALUES (:i, :n, now())"
                    ),
                    {"i": d, "n": f"d{n}"},
                )
        # Indexes are built after loading, as bench_scale.py does.
        with engine.begin() as c:
            defs = c.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema() "
                    "AND tablename = 'records' AND indexname NOT IN "
                    "('records_pkey','uq_records_id_dataset')"
                )
            ).all()
            for n, _ in defs:
                c.execute(text(f"DROP INDEX {n}"))
        with engine.connect() as c:
            report["seed_s"] = round(
                seed(c, args.rows, [str(d) for d in datasets], schema_id), 1
            )
        t = time.time()
        with engine.begin() as c:
            for _, d in defs:
                c.execute(text(d))
        report["index_build_s"] = round(time.time() - t, 1)
        with engine.execution_options(isolation_level="AUTOCOMMIT").connect() as c:
            c.execute(text("VACUUM (ANALYZE) records"))
        hot, small = datasets[0], datasets[5]
        with engine.connect() as c:
            sample = [
                r[0]
                for r in c.execute(
                    text("SELECT id FROM records TABLESAMPLE SYSTEM (0.01) LIMIT 300")
                )
            ]
            report["size_plain"] = c.execute(
                text("SELECT pg_total_relation_size('records')")
            ).scalar_one()
        report["plain"] = {
            "reads": read_suite(engine, hot, small, sample),
            "locks_keyset": locks_for_keyset(engine, hot),
            "inserts": insert_suite(engine, hot, schema_id, args.inserts),
        }
        # Convert in place: the migration's cost on a populated repository.
        raw = engine.connect()
        w0 = _wal(raw)
        raw.rollback()
        t = time.time()
        with raw.begin():
            partitioning.partition_records(raw, args.modulus)
        report["conversion"] = {
            "seconds": round(time.time() - t, 1),
            "wal_gb": round((_wal(raw) - w0) / 1e9, 2),
        }
        raw.close()
        with engine.connect() as c:
            rows = c.execute(text("SELECT count(*) FROM records")).scalar_one()
            report["rows_after_conversion"] = rows
            report["size_partitioned"] = c.execute(
                text(
                    "SELECT sum(pg_total_relation_size(inhrelid)) FROM pg_inherits "
                    "WHERE inhparent = 'records'::regclass"
                )
            ).scalar_one()
        with engine.execution_options(isolation_level="AUTOCOMMIT").connect() as c:
            c.execute(text("VACUUM (ANALYZE) records"))
        report["partitioned"] = {
            "reads": read_suite(engine, hot, small, sample),
            "locks_keyset": locks_for_keyset(engine, hot),
            "inserts": insert_suite(engine, hot, schema_id, args.inserts),
        }
        report["catalog_partitioned_loaded"] = catalog(engine)
        if args.audit_rows:
            report["audit_log"] = audit_suite(engine, args.audit_rows)
    finally:
        if not args.keep:
            with admin.connect() as c:
                c.execute(text(f"DROP SCHEMA {name} CASCADE"))
        # Empty-repository catalog cost of the default layout.
        probe = f"probe_{uuid.uuid4().hex[:8]}"
        with admin.connect() as c:
            c.execute(text(f"CREATE SCHEMA {probe}"))
        pe = create_engine(url, connect_args={"options": f"-csearch_path={probe}"})
        t = time.time()
        ensure_schema_current(pe)
        report["catalog_default_empty"] = {
            **catalog(pe),
            "create_s": round(time.time() - t, 2),
        }
        pe.dispose()
        with admin.connect() as c:
            c.execute(text(f"DROP SCHEMA {probe} CASCADE"))
    text_out = json.dumps(report, indent=2, default=float)
    print(text_out)
    if args.out:
        open(args.out, "w").write(text_out + "\n")


if __name__ == "__main__":
    main()
