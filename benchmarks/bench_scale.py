"""
Benchmark: how `records` and `audit_log` behave at tens of millions of rows,
and what partitioning / BRIN / a JSONB side table would change.

Companion to docs/contributing/billion-row-collections.md, which holds the numbers
this script produced. Not part of the product: it builds its own throwaway
tables (prefix `bm_`) in a scratch database, mirroring the DDL in
src/civex/db/models.py, and never imports civex.

One command, clean database in, JSON + a printed summary out:

    PG_URL=postgresql://user@localhost:5545/civex_scratch \\
        python benchmarks/bench_scale.py --rows 20000000 --out scale-results.json

Phases (each can be run alone with --phase):
    seed       build `bm_records` and `bm_audit` at --rows rows, then their indexes
    ids        insert cost of random uuid4 vs time-ordered uuidv7 primary keys
    measure    insert throughput, keyset list, JSONB lookup, FTS, count, vacuum, sizes
    spike      hash-partitioned records, time-partitioned audit, BRIN, JSONB side table
    catalog    partitions x schemas catalog growth (schema-per-repo model)

Seeding is server-side (INSERT .. SELECT generate_series) in 1M-row batches with
the search-vector trigger bypassed (the tsvector is computed inline) and the
indexes built after the load, because that is the only way to reach 10^7-10^8
rows in minutes. Insert throughput is measured separately, on the finished
table with every index and the trigger live, which is what a real write sees.

Needs a database you can fill: ~1 KB per record plus indexes, so roughly
1.8 KB per record in total (36 GB at 20M rows, plus WAL). Drops its tables when done
unless --keep is given.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import statistics
import sys
import time
import uuid

import psycopg2

PG_URL = os.environ.get("PG_URL", "postgresql://civexhub@localhost:5545/civex_scratch")

N_DATASETS = 200
N_SCHEMAS = 20
BATCH = 1_000_000
REPS = 5

# Field UUIDs the generated records are keyed by (as in production, data is
# keyed by field id, not name).
F_NAME, F_SITE, F_STATUS, F_COUNT, F_NOTE, F_DAY, F_TAG, F_NEEDLE = (
    str(uuid.UUID(int=i + 1)) for i in range(8)
)

WORDS_SQL = "ARRAY(SELECT 'w' || g FROM generate_series(1, 2000) g)"

# --------------------------------------------------------------------------
# DDL: the records / audit_log shapes from src/civex/db/models.py
# --------------------------------------------------------------------------

RECORDS_COLS = """
    id UUID NOT NULL,
    dataset_id UUID NOT NULL,
    schema_id UUID NOT NULL,
    parent_record_id UUID,
    data JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    search_vector TSVECTOR,
    deleted_at TIMESTAMPTZ
"""

# audit_log keeps the columns the sync feed and history reads touch; the
# omitted ones (device, op_id, ...) are narrow and change sizes by a few %.
AUDIT_COLS = """
    id UUID NOT NULL,
    action VARCHAR(20) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id UUID NOT NULL,
    old_data JSONB,
    new_data JSONB,
    "timestamp" TIMESTAMPTZ NOT NULL DEFAULT now(),
    batch_id UUID,
    actor VARCHAR(100),
    hlc VARCHAR(40),
    hub_seq BIGINT,
    sync_state VARCHAR(10) NOT NULL DEFAULT 'synced',
    apply_state VARCHAR(10) NOT NULL DEFAULT 'applied',
    delta JSONB,
    format SMALLINT NOT NULL DEFAULT 2,
    local_seq BIGSERIAL
"""

TRIGGER_FN = """
CREATE OR REPLACE FUNCTION bm_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('simple', (
        SELECT coalesce(string_agg(entry.value #>> '{}', ' '), '')
        FROM jsonb_each(NEW.data) AS entry
        WHERE jsonb_typeof(entry.value) IN ('string', 'number')
    ));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def records_indexes(t: str) -> list[str]:
    """The seven non-unique indexes models.py declares, named after `t`."""
    return [
        f"CREATE INDEX {t}_ds_schema ON {t} (dataset_id, schema_id)",
        f"CREATE INDEX {t}_ds_created ON {t} (dataset_id, created_at)",
        f"CREATE INDEX {t}_ds_parent ON {t} (dataset_id, parent_record_id)",
        f"CREATE INDEX {t}_deleted ON {t} (deleted_at)",
        f"CREATE INDEX {t}_parent ON {t} (parent_record_id)",
        f"CREATE INDEX {t}_live_ds_created ON {t} (dataset_id, created_at, id) "
        f"WHERE deleted_at IS NULL",
        f"CREATE INDEX {t}_live_schema_created ON {t} (schema_id, created_at, id) "
        f"WHERE deleted_at IS NULL",
        f"CREATE INDEX {t}_data_gin ON {t} USING gin (data)",
        f"CREATE INDEX {t}_sv ON {t} USING gin (search_vector)",
    ]


def audit_indexes(t: str) -> list[str]:
    return [
        f'CREATE INDEX {t}_entity ON {t} (entity_id, "timestamp")',
        f'CREATE INDEX {t}_ts ON {t} ("timestamp")',
        f"CREATE INDEX {t}_batch ON {t} (batch_id)",
        f"CREATE INDEX {t}_hub_seq ON {t} (hub_seq)",
        f"CREATE INDEX {t}_unsynced ON {t} (\"timestamp\") WHERE sync_state = 'pending'",
    ]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def connect(url: str = PG_URL):
    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SET maintenance_work_mem = '512MB'")
    cur.execute("SET work_mem = '32MB'")
    cur.execute("SET max_parallel_maintenance_workers = 2")
    return conn


def q(cur, sql: str, params=None):
    cur.execute(sql, params)
    return cur.fetchall() if cur.description else None


def one(cur, sql: str, params=None):
    return q(cur, sql, params)[0][0]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def timed(cur, sql: str, params=None, reps: int = REPS) -> dict:
    """Run `sql` reps+1 times (first is warm-up); median/min/max ms of the rest."""
    ms: list[float] = []
    for i in range(reps + 1):
        t0 = time.perf_counter()
        cur.execute(sql, params)
        if cur.description:
            cur.fetchall()
        if i:
            ms.append((time.perf_counter() - t0) * 1000)
    return {
        "median_ms": round(statistics.median(ms), 2),
        "min_ms": round(min(ms), 2),
        "max_ms": round(max(ms), 2),
    }


def explain_json(cur, sql: str, params=None) -> dict:
    cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params)
    return cur.fetchone()[0][0]


def plan_nodes(plan: dict) -> list[str]:
    out = [
        f"{plan['Node Type']}"
        + (f" on {plan['Index Name']}" if "Index Name" in plan else "")
    ]
    for p in plan.get("Plans", []):
        out += plan_nodes(p)
    return out


def size(cur, rel: str) -> int:
    return one(cur, "SELECT pg_relation_size(%s::regclass)", (rel,))


def total_size(cur, rel: str) -> int:
    return one(cur, "SELECT pg_total_relation_size(%s::regclass)", (rel,))


def index_sizes(cur, table: str) -> dict[str, int]:
    rows = q(
        cur,
        """SELECT c.relname, pg_relation_size(c.oid)
           FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
           WHERE i.indrelid = %s::regclass ORDER BY 2 DESC""",
        (table,),
    )
    return {n: s for n, s in rows}


def mb(n: float) -> float:
    return round(float(n) / 1024 / 1024, 1)


def wal_lsn(cur) -> int:
    return int(one(cur, "SELECT pg_current_wal_lsn() - '0/0'::pg_lsn"))


# --------------------------------------------------------------------------
# seed
# --------------------------------------------------------------------------


def seed(cur, rows: int, results: dict) -> None:
    log(f"seed: {rows:,} records and {rows:,} audit rows")
    for t in ("bm_audit", "bm_records", "bm_datasets", "bm_schemas"):
        cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    cur.execute("CREATE TABLE bm_datasets (n INT PRIMARY KEY, id UUID NOT NULL)")
    cur.execute("CREATE TABLE bm_schemas (n INT PRIMARY KEY, id UUID NOT NULL)")
    cur.execute(
        "INSERT INTO bm_datasets SELECT g, gen_random_uuid() FROM generate_series(1,%s) g",
        (N_DATASETS,),
    )
    cur.execute(
        "INSERT INTO bm_schemas SELECT g, gen_random_uuid() FROM generate_series(1,%s) g",
        (N_SCHEMAS,),
    )
    cur.execute(TRIGGER_FN)
    cur.execute(f"CREATE TABLE bm_records ({RECORDS_COLS})")
    cur.execute(f"CREATE TABLE bm_audit ({AUDIT_COLS})")

    # Dataset 1 holds ~half the rows (a hot collection); the rest skew down.
    # created_at advances with the row number: real data arrives in time order.
    span_s = 2 * 365 * 86400
    t0 = time.time()
    for lo in range(0, rows, BATCH):
        hi = min(lo + BATCH, rows)
        cur.execute(
            f"""
            WITH ds AS (SELECT array_agg(id ORDER BY n) a FROM bm_datasets),
                 sc AS (SELECT array_agg(id ORDER BY n) a FROM bm_schemas),
                 w  AS (SELECT {WORDS_SQL} a),
                 src AS (
                   SELECT g,
                     CASE WHEN random() < 0.5 THEN 1
                          ELSE 1 + floor({N_DATASETS} * power(random(), 3))::int END AS d,
                     (random() * 2000)::int AS w1, (random() * 2000)::int AS w2,
                     (random() * 2000)::int AS w3,
                     (random() * 49)::int AS site, (random() * 3)::int AS st
                   FROM generate_series(%s, %s) g
                 ),
                 built AS (
                   SELECT g, d, site, st, w1, w2, w3,
                     jsonb_build_object(
                       '{F_NAME}', 'name-' || g,
                       '{F_SITE}', 'site-' || site,
                       '{F_STATUS}', (ARRAY['active','inactive','pending','enrolled'])[st + 1],
                       '{F_COUNT}', (random() * 1000)::int,
                       '{F_NOTE}', (SELECT a[w1+1] || ' ' || a[w2+1] || ' ' || a[w3+1] FROM w)
                                   || ' ' || repeat('lorem ipsum ', 12),
                       '{F_DAY}', to_char(timestamptz '2024-01-01' + (g %% 700) * interval '1 day', 'YYYY-MM-DD'),
                       '{F_TAG}', 'tag-' || (g %% 5000)
                     ) || CASE WHEN g %% 1000003 = 0
                               THEN jsonb_build_object('{F_NEEDLE}', 'needle-' || g)
                               ELSE '{{}}'::jsonb END AS data
                   FROM src
                 )
            INSERT INTO bm_records
            SELECT gen_random_uuid(), (SELECT a[d] FROM ds), (SELECT a[1 + g %% {N_SCHEMAS}] FROM sc),
                   NULL, data,
                   timestamptz '2024-01-01' + (g::float8 / {rows}) * {span_s} * interval '1 second',
                   timestamptz '2024-01-01' + (g::float8 / {rows}) * {span_s} * interval '1 second',
                   to_tsvector('simple', (SELECT string_agg(e.value #>> '{{}}', ' ')
                                          FROM jsonb_each(data) e
                                          WHERE jsonb_typeof(e.value) IN ('string','number'))),
                   CASE WHEN g %% 50 = 0 THEN timestamptz '2025-06-01' END
            FROM built
            """,
            (lo + 1, hi),
        )
        el = time.time() - t0
        log(f"  records {hi:,}/{rows:,}  {hi / el:,.0f} rows/s")
    results["seed_records_s"] = round(time.time() - t0, 1)

    # audit: one `create` per record plus 25% `update`s; delta-format payloads.
    t0 = time.time()
    for lo in range(0, rows, BATCH):
        hi = min(lo + BATCH, rows)
        cur.execute(
            f"""
            INSERT INTO bm_audit (id, action, entity_type, entity_id, old_data, new_data, "timestamp",
                                  batch_id, actor, hlc, hub_seq, sync_state, delta)
            SELECT gen_random_uuid(),
                   CASE WHEN g %% 4 = 0 THEN 'update' ELSE 'create' END,
                   'record', gen_random_uuid(), NULL,
                   jsonb_build_object('id', g, 'dataset', 'x'),
                   timestamptz '2024-01-01' + (g::float8 / {rows}) * {span_s} * interval '1 second',
                   CASE WHEN g %% 10 = 0 THEN gen_random_uuid() END,
                   'user' || (g %% 40),
                   lpad(to_hex(g), 16, '0') || '-0000',
                   g,
                   CASE WHEN g > {rows} - 1000 THEN 'pending' ELSE 'synced' END,
                   jsonb_build_object('data.' || (g %% 8), jsonb_build_object('before', g %% 97, 'after', g %% 89))
            FROM generate_series(%s, %s) g
            """,
            (lo + 1, hi),
        )
        el = time.time() - t0
        log(f"  audit   {hi:,}/{rows:,}  {hi / el:,.0f} rows/s")
    results["seed_audit_s"] = round(time.time() - t0, 1)

    # Index builds, timed: this is also the cost of a reindex / pg_upgrade.
    builds: dict[str, float] = {}
    t0 = time.time()
    cur.execute("ALTER TABLE bm_records ADD PRIMARY KEY (id)")
    cur.execute(
        "ALTER TABLE bm_records ADD CONSTRAINT bm_records_uq UNIQUE (id, dataset_id)"
    )
    builds["pk+unique"] = round(time.time() - t0, 1)
    for ddl in records_indexes("bm_records"):
        t1 = time.time()
        cur.execute(ddl)
        builds[ddl.split()[2]] = round(time.time() - t1, 1)
        log(f"  built {ddl.split()[2]}: {builds[ddl.split()[2]]}s")
    cur.execute(
        "CREATE TRIGGER bm_records_sv BEFORE INSERT OR UPDATE OF data ON bm_records "
        "FOR EACH ROW EXECUTE FUNCTION bm_search_vector_update()"
    )
    cur.execute("ALTER TABLE bm_audit ADD PRIMARY KEY (id)")
    for ddl in audit_indexes("bm_audit"):
        t1 = time.time()
        cur.execute(ddl)
        builds[ddl.split()[2]] = round(time.time() - t1, 1)
        log(f"  built {ddl.split()[2]}: {builds[ddl.split()[2]]}s")
    results["index_build_s"] = builds
    cur.execute("ANALYZE bm_records")
    cur.execute("ANALYZE bm_audit")


# --------------------------------------------------------------------------
# measure
# --------------------------------------------------------------------------


def measure(cur, results: dict) -> None:
    log("measure: sizes")
    m: dict = {}
    for t in ("bm_records", "bm_audit"):
        m[t] = {
            "rows": one(
                cur, "SELECT reltuples::bigint FROM pg_class WHERE relname = %s", (t,)
            ),
            "heap_mb": mb(size(cur, t)),
            "toast_mb": mb(
                one(
                    cur,
                    "SELECT coalesce(pg_total_relation_size(reltoastrelid),0) "
                    "FROM pg_class WHERE relname = %s",
                    (t,),
                )
            ),
            "indexes_mb": {k: mb(v) for k, v in index_sizes(cur, t).items()},
            "total_mb": mb(total_size(cur, t)),
        }
    m["avg_record_bytes"] = one(
        cur,
        "SELECT avg(pg_column_size(r.*))::int FROM "
        "(SELECT * FROM bm_records TABLESAMPLE SYSTEM (0.01)) r",
    )
    results["sizes"] = m

    big = one(cur, "SELECT id FROM bm_datasets WHERE n = 1")
    small = one(cur, "SELECT id FROM bm_datasets WHERE n = %s", (N_DATASETS,))
    sc = one(cur, "SELECT id FROM bm_schemas WHERE n = 1")
    r: dict = {}

    log("measure: keyset list")
    # Keyset page: first page, and a page ~3/4 of the way through the big dataset.
    mid_ts, mid_id = q(
        cur,
        """SELECT created_at, id FROM bm_records WHERE dataset_id = %s AND deleted_at IS NULL
           ORDER BY created_at, id OFFSET (SELECT count(*) * 3 / 4 FROM bm_records
           WHERE dataset_id = %s AND deleted_at IS NULL) LIMIT 1""",
        (big, big),
    )[0]
    page = """SELECT id, data, created_at FROM bm_records
              WHERE dataset_id = %s AND deleted_at IS NULL
                AND (created_at, id) > (%s, %s) ORDER BY created_at, id LIMIT 50"""
    r["keyset_first_page_big_dataset"] = timed(
        cur, page, (big, "-infinity", "00000000-0000-0000-0000-000000000000")
    )
    r["keyset_deep_page_big_dataset"] = timed(cur, page, (big, mid_ts, mid_id))
    r["keyset_first_page_small_dataset"] = timed(
        cur, page, (small, "-infinity", "00000000-0000-0000-0000-000000000000")
    )
    r["keyset_by_schema_first_page"] = timed(
        cur,
        """SELECT id, data FROM bm_records WHERE schema_id = %s AND deleted_at IS NULL
           AND (created_at, id) > (%s, %s) ORDER BY created_at, id LIMIT 50""",
        (sc, "-infinity", "00000000-0000-0000-0000-000000000000"),
    )
    # The thing keyset paging replaces, for scale: OFFSET into the same dataset.
    r["offset_1M_big_dataset"] = timed(
        cur,
        """SELECT id, data FROM bm_records WHERE dataset_id = %s AND deleted_at IS NULL
           ORDER BY created_at, id LIMIT 50 OFFSET 1000000""",
        (big,),
        reps=2,
    )
    r["keyset_deep_plan"] = plan_nodes(
        explain_json(cur, page, (big, mid_ts, mid_id))["Plan"]
    )

    log("measure: JSONB lookup")
    hit = f'{{"{F_SITE}":"site-17","{F_STATUS}":"active"}}'
    r["jsonb_contains_2keys_in_dataset"] = timed(
        cur,
        "SELECT id FROM bm_records WHERE dataset_id = %s AND data @> %s::jsonb LIMIT 50",
        (big, hit),
    )
    r["jsonb_contains_2keys_in_dataset_count"] = timed(
        cur,
        "SELECT count(*) FROM bm_records WHERE dataset_id = %s AND data @> %s::jsonb",
        (big, hit),
        reps=2,
    )
    r["jsonb_contains_2keys_plan"] = plan_nodes(
        explain_json(
            cur,
            "SELECT count(*) FROM bm_records WHERE dataset_id = %s AND data @> %s::jsonb",
            (big, hit),
        )["Plan"]
    )
    needle = f'{{"{F_NEEDLE}":"needle-{1000003}"}}'
    r["jsonb_contains_rare_value_whole_table"] = timed(
        cur, "SELECT id FROM bm_records WHERE data @> %s::jsonb", (needle,)
    )
    r["jsonb_contains_rare_plan"] = plan_nodes(
        explain_json(
            cur, "SELECT id FROM bm_records WHERE data @> %s::jsonb", (needle,)
        )["Plan"]
    )
    r["jsonb_text_equals_no_index_expr"] = timed(
        cur,
        "SELECT count(*) FROM bm_records WHERE dataset_id = %s AND data->>%s = 'tag-42'",
        (small, F_TAG),
    )

    log("measure: full-text")
    r["fts_rare_word_in_dataset_limit20"] = timed(
        cur,
        "SELECT id FROM bm_records WHERE dataset_id = %s AND search_vector @@ to_tsquery('simple','w1999') "
        "AND deleted_at IS NULL LIMIT 20",
        (big,),
    )
    r["fts_rare_word_ranked_whole_table"] = timed(
        cur,
        """SELECT id, ts_rank(search_vector, to_tsquery('simple','w1999')) r FROM bm_records
                WHERE search_vector @@ to_tsquery('simple','w1999') AND deleted_at IS NULL
                ORDER BY r DESC LIMIT 20""",
        reps=3,
    )
    r["fts_common_word_ranked_whole_table"] = timed(
        cur,
        """SELECT id, ts_rank(search_vector, to_tsquery('simple','lorem & w7')) r FROM bm_records
                WHERE search_vector @@ to_tsquery('simple','lorem & w7') AND deleted_at IS NULL
                ORDER BY r DESC LIMIT 20""",
        reps=2,
    )

    log("measure: count")
    r["count_exact_big_dataset_live"] = timed(
        cur,
        "SELECT count(*) FROM bm_records WHERE dataset_id = %s AND deleted_at IS NULL",
        (big,),
        reps=2,
    )
    r["count_exact_small_dataset_live"] = timed(
        cur,
        "SELECT count(*) FROM bm_records WHERE dataset_id = %s AND deleted_at IS NULL",
        (small,),
    )
    r["count_exact_whole_table"] = timed(cur, "SELECT count(*) FROM bm_records", reps=2)
    r["count_estimate_reltuples"] = timed(
        cur, "SELECT reltuples::bigint FROM pg_class WHERE relname = 'bm_records'"
    )
    est = q(
        cur,
        "EXPLAIN (FORMAT JSON) SELECT 1 FROM bm_records WHERE dataset_id = %s AND deleted_at IS NULL",
        (big,),
    )
    r["count_estimate_planner_rows_big_dataset"] = est[0][0][0]["Plan"]["Plan Rows"]
    r["count_exact_big_dataset_value"] = one(
        cur,
        "SELECT count(*) FROM bm_records WHERE dataset_id = %s AND deleted_at IS NULL",
        (big,),
    )
    r["count_exact_whole_table_value"] = one(cur, "SELECT count(*) FROM bm_records")

    log("measure: audit_log reads")
    ent = one(
        cur, "SELECT entity_id FROM bm_audit OFFSET %s LIMIT 1", (results["rows"] // 3,)
    )
    r["audit_history_of_one_entity"] = timed(
        cur,
        'SELECT id, action, delta FROM bm_audit WHERE entity_id = %s ORDER BY "timestamp"',
        (ent,),
    )
    r["audit_hub_seq_feed_1000_deep"] = timed(
        cur,
        "SELECT id, hub_seq FROM bm_audit WHERE hub_seq > %s ORDER BY hub_seq LIMIT 1000",
        (results["rows"] // 2,),
    )
    r["audit_head_seq"] = timed(cur, "SELECT max(hub_seq) FROM bm_audit")
    r["audit_unsynced_pending"] = timed(
        cur,
        """SELECT id FROM bm_audit WHERE sync_state = 'pending' ORDER BY "timestamp" LIMIT 1000""",
    )
    r["audit_time_range_count_1day"] = timed(
        cur,
        """SELECT count(*) FROM bm_audit WHERE "timestamp" >= timestamptz '2025-03-01'
                AND "timestamp" < timestamptz '2025-03-02'""",
    )
    results["reads"] = r

    log("measure: insert throughput (all indexes + trigger live)")
    ins: dict = {}
    n = 200_000
    base = results["rows"]
    # Same generator, appended in time order (the usual case)
    sql = f"""
        INSERT INTO bm_records (id, dataset_id, schema_id, data, created_at, updated_at)
        SELECT gen_random_uuid(), (SELECT id FROM bm_datasets WHERE n = 1 + g %% 40),
               (SELECT id FROM bm_schemas WHERE n = 1),
               jsonb_build_object('{F_NAME}', 'ins-' || g, '{F_SITE}', 'site-' || (g %% 50),
                                  '{F_STATUS}', 'active', '{F_COUNT}', g %% 1000,
                                  '{F_NOTE}', 'w' || (g %% 2000) || ' w' || (g %% 1999) || ' ' || repeat('lorem ipsum ', 12),
                                  '{F_DAY}', '2026-01-01', '{F_TAG}', 'tag-' || g %% 5000),
               now(), now()
        FROM generate_series(%s, %s) g"""
    w0 = wal_lsn(cur)
    t0 = time.perf_counter()
    cur.execute(sql, (base + 1, base + n))
    dt = time.perf_counter() - t0
    ins["records_insert_select_trigger_on"] = {
        "rows_per_s": round(n / dt),
        "wal_bytes_per_row": round((wal_lsn(cur) - w0) / n),
    }
    # NB: with the trigger off the rows get a NULL search_vector, so this also skips the
    # search_vector GIN maintenance: it measures trigger + FTS index, not the trigger alone.
    cur.execute("ALTER TABLE bm_records DISABLE TRIGGER bm_records_sv")
    w0 = wal_lsn(cur)
    t0 = time.perf_counter()
    cur.execute(sql, (base + n + 1, base + 2 * n))
    dt = time.perf_counter() - t0
    ins["records_insert_select_trigger_off"] = {
        "rows_per_s": round(n / dt),
        "wal_bytes_per_row": round((wal_lsn(cur) - w0) / n),
    }
    cur.execute("ALTER TABLE bm_records ENABLE TRIGGER bm_records_sv")

    # COPY from the client: what sync apply / bulk import does.
    buf = io.StringIO()
    ds_id = one(cur, "SELECT id FROM bm_datasets WHERE n = 2")
    sc_id = one(cur, "SELECT id FROM bm_schemas WHERE n = 1")
    for i in range(n):
        d = json.dumps(
            {
                F_NAME: f"copy-{i}",
                F_SITE: f"site-{i % 50}",
                F_STATUS: "active",
                F_COUNT: i % 1000,
                F_NOTE: f"w{i % 2000} w{i % 1999} " + "lorem ipsum " * 12,
                F_TAG: f"tag-{i % 5000}",
            }
        )
        d = d.replace("\\", "\\\\")
        buf.write(f"{uuid.uuid4()}\t{ds_id}\t{sc_id}\t{d}\n")
    buf.seek(0)
    t0 = time.perf_counter()
    cur.copy_expert("COPY bm_records (id, dataset_id, schema_id, data) FROM STDIN", buf)
    dt = time.perf_counter() - t0
    ins["records_copy_trigger_on"] = {"rows_per_s": round(n / dt)}

    w0 = wal_lsn(cur)
    t0 = time.perf_counter()
    cur.execute(
        """INSERT INTO bm_audit (id, action, entity_type, entity_id, new_data, "timestamp", actor, hlc, hub_seq, delta)
            SELECT gen_random_uuid(), 'create', 'record', gen_random_uuid(), '{"id":1}', now(), 'u', 'h', g,
                   '{"data.1":{"before":1,"after":2}}'
            FROM generate_series(%s, %s) g""",
        (base + 1, base + n),
    )
    dt = time.perf_counter() - t0
    ins["audit_insert_select"] = {
        "rows_per_s": round(n / dt),
        "wal_bytes_per_row": round((wal_lsn(cur) - w0) / n),
    }
    results["inserts"] = ins

    log("measure: update + vacuum")
    v: dict = {}
    w0 = wal_lsn(cur)
    t0 = time.perf_counter()
    # 1% of the big dataset: a bulk edit (status flip). Updating `data` re-fires the trigger.
    cur.execute(
        f"""UPDATE bm_records SET data = jsonb_set(data, '{{{F_STATUS}}}', '"inactive"'), updated_at = now()
            WHERE id IN (SELECT id FROM bm_records WHERE dataset_id = %s AND deleted_at IS NULL
                         ORDER BY created_at LIMIT %s)""",
        (big, base // 100),
    )
    v["update_1pct_s"] = round(time.perf_counter() - t0, 1)
    v["update_1pct_rows"] = cur.rowcount
    v["update_1pct_wal_mb"] = mb(wal_lsn(cur) - w0)
    cur.execute("SELECT pg_stat_force_next_flush()")
    v["dead_tuples_before_vacuum"] = one(
        cur, "SELECT n_dead_tup FROM pg_stat_user_tables WHERE relname = 'bm_records'"
    )
    t0 = time.perf_counter()
    cur.execute("VACUUM (ANALYZE) bm_records")
    v["vacuum_analyze_after_1pct_update_s"] = round(time.perf_counter() - t0, 1)
    t0 = time.perf_counter()
    cur.execute("VACUUM (ANALYZE) bm_records")
    v["vacuum_analyze_clean_table_s"] = round(time.perf_counter() - t0, 1)
    t0 = time.perf_counter()
    cur.execute("ANALYZE bm_records")
    v["analyze_s"] = round(time.perf_counter() - t0, 1)
    t0 = time.perf_counter()
    cur.execute("REINDEX INDEX bm_records_live_ds_created")
    v["reindex_live_ds_created_s"] = round(time.perf_counter() - t0, 1)
    t0 = time.perf_counter()
    cur.execute("REINDEX INDEX bm_records_data_gin")
    v["reindex_data_gin_s"] = round(time.perf_counter() - t0, 1)
    t0 = time.perf_counter()
    cur.execute("VACUUM (ANALYZE) bm_audit")
    v["vacuum_analyze_audit_s"] = round(time.perf_counter() - t0, 1)
    results["maintenance"] = v


def id_order(cur, results: dict) -> None:
    """Insert cost of random (uuid4) vs time-ordered (uuidv7, PostgreSQL 18+) primary keys.

    civex ids are random uuid4, so every insert dirties a random leaf page in the
    primary key and the (id, dataset_id) unique index; after each checkpoint the
    first touch of each page is logged whole (a full-page image). Time-ordered
    ids keep those two indexes' insert point at the right-hand edge.
    """
    log("id_order: random vs time-ordered ids on the full-size table")
    n = 100_000
    out: dict = {"rows_each": n}
    base = one(cur, "SELECT count(*) FROM bm_records") + 10_000_000
    for label, id_expr in (
        ("uuid4_random", "gen_random_uuid()"),
        ("uuidv7_time_ordered", "uuidv7()"),
    ):
        cur.execute("CHECKPOINT")  # same starting point: no page has been logged since
        cur.execute("SELECT wal_fpi, wal_bytes FROM pg_stat_wal")
        fpi0, wb0 = cur.fetchone()
        t0 = time.perf_counter()
        cur.execute(
            f"""INSERT INTO bm_records (id, dataset_id, schema_id, data, created_at, updated_at)
                SELECT {id_expr}, (SELECT id FROM bm_datasets WHERE n = 1 + g %% 40),
                       (SELECT id FROM bm_schemas WHERE n = 1),
                       jsonb_build_object('{F_NAME}', 'idord-' || g, '{F_SITE}', 'site-' || (g %% 50),
                                          '{F_NOTE}', 'w' || (g %% 2000) || ' w' || (g %% 1999)),
                       now(), now()
                FROM generate_series(%s, %s) g""",
            (base, base + n - 1),
        )
        dt = time.perf_counter() - t0
        cur.execute("SELECT pg_stat_force_next_flush()")
        cur.execute("SELECT wal_fpi, wal_bytes FROM pg_stat_wal")
        fpi1, wb1 = cur.fetchone()
        out[label] = {
            "rows_per_s": round(n / dt),
            "wal_bytes_per_row": round((wb1 - wb0) / n),
            "full_page_images_per_row": round((fpi1 - fpi0) / n, 2),
        }
        base += n + 1
    results["id_order"] = out


# --------------------------------------------------------------------------
# spike: partitioning, BRIN, side table
# --------------------------------------------------------------------------

SPIKE_ROWS_DEFAULT = 3_000_000


def spike(cur, spike_rows: int, results: dict) -> None:
    log(f"spike: {spike_rows:,}-row comparison tables")
    sp: dict = {}
    sp["rows"] = spike_rows
    for t in (
        "sp_mono",
        "sp_hash",
        "sp_hashid",
        "sp_brin",
        "sp_aud_mono",
        "sp_aud_part",
    ):
        cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    for t in ("sp_blob_inline", "sp_blob_small", "sp_blob_side"):
        cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")

    # Constraint feasibility on a partitioned records table ---------------
    feas: dict = {}
    cur.execute(f"CREATE TABLE sp_hash ({RECORDS_COLS}) PARTITION BY HASH (dataset_id)")
    for name, ddl in {
        "primary_key_on_id_alone": "ALTER TABLE sp_hash ADD PRIMARY KEY (id)",
        "unique_id_alone": "ALTER TABLE sp_hash ADD CONSTRAINT u UNIQUE (id)",
        "primary_key_id_dataset_id": "ALTER TABLE sp_hash ADD PRIMARY KEY (id, dataset_id)",
        "unique_id_dataset_id_(uq_records_id_dataset)": "ALTER TABLE sp_hash ADD CONSTRAINT uq_id_ds UNIQUE (id, dataset_id)",
    }.items():
        try:
            cur.execute(ddl)
            feas[name] = "ok"
        except psycopg2.Error as e:
            feas[name] = f"ERROR: {e.pgerror.splitlines()[0]}"
    for i in range(16):
        cur.execute(
            f"CREATE TABLE sp_hash_p{i} PARTITION OF sp_hash FOR VALUES WITH (MODULUS 16, REMAINDER {i})"
        )
    try:
        cur.execute(
            """ALTER TABLE sp_hash ADD CONSTRAINT fk_parent FOREIGN KEY (parent_record_id, dataset_id)
               REFERENCES sp_hash (id, dataset_id) DEFERRABLE INITIALLY DEFERRED"""
        )
        feas["deferred_composite_self_fk_on_partitioned"] = "ok"
    except psycopg2.Error as e:
        feas["deferred_composite_self_fk_on_partitioned"] = (
            f"ERROR: {e.pgerror.splitlines()[0]}"
        )
    cur.execute("CREATE TABLE sp_child (id UUID PRIMARY KEY, record_id UUID)")
    try:
        cur.execute(
            "ALTER TABLE sp_child ADD FOREIGN KEY (record_id) REFERENCES sp_hash (id)"
        )
        feas["foreign_key_to_records_id_alone_from_other_tables"] = "ok"
    except psycopg2.Error as e:
        feas["foreign_key_to_records_id_alone_from_other_tables"] = (
            f"ERROR: {e.pgerror.splitlines()[0]}"
        )
    cur.execute("DROP TABLE sp_child")
    cur.execute("DROP TABLE sp_hash")

    # Build the same N-row table four ways -----------------------------------
    cur.execute(f"CREATE TABLE sp_mono ({RECORDS_COLS})")
    cur.execute(
        f"CREATE TABLE sp_hash ({RECORDS_COLS}, PRIMARY KEY (id, dataset_id)) PARTITION BY HASH (dataset_id)"
    )
    for i in range(16):
        cur.execute(
            f"CREATE TABLE sp_hash_p{i} PARTITION OF sp_hash FOR VALUES WITH (MODULUS 16, REMAINDER {i})"
        )
    # Hash on `id` instead: the PK stays (id), and every constraint that already
    # contains id (the (id, dataset_id) unique, the composite FK, the FKs from
    # other tables to records.id) stays legal.
    cur.execute(
        f"CREATE TABLE sp_hashid ({RECORDS_COLS}, PRIMARY KEY (id)) PARTITION BY HASH (id)"
    )
    for i in range(16):
        cur.execute(
            f"CREATE TABLE sp_hashid_p{i} PARTITION OF sp_hashid FOR VALUES WITH (MODULUS 16, REMAINDER {i})"
        )
    cur.execute(
        "ALTER TABLE sp_hashid ADD CONSTRAINT sp_hashid_uq UNIQUE (id, dataset_id)"
    )
    cur.execute("CREATE TABLE sp_child2 (id UUID PRIMARY KEY, record_id UUID)")
    for name, ddl in {
        "hash_by_id_deferred_composite_self_fk": """ALTER TABLE sp_hashid ADD CONSTRAINT fk_parent
            FOREIGN KEY (parent_record_id, dataset_id) REFERENCES sp_hashid (id, dataset_id)
            DEFERRABLE INITIALLY DEFERRED""",
        "hash_by_id_fk_from_other_table_to_id": "ALTER TABLE sp_child2 ADD FOREIGN KEY (record_id) REFERENCES sp_hashid (id)",
    }.items():
        try:
            cur.execute(ddl)
            feas[name] = "ok"
        except psycopg2.Error as e:
            feas[name] = f"ERROR: {e.pgerror.splitlines()[0]}"
    cur.execute("DROP TABLE sp_child2")
    cur.execute(f"CREATE TABLE sp_brin ({RECORDS_COLS})")
    for t in ("sp_mono", "sp_hash", "sp_hashid", "sp_brin"):
        # ordered by created_at = the physical order a time-ordered insert produces
        t0 = time.time()
        cur.execute(
            f"INSERT INTO {t} SELECT * FROM bm_records ORDER BY created_at LIMIT %s",
            (spike_rows,),
        )
        log(f"  loaded {t} in {time.time() - t0:.0f}s")

    sp["feasibility"] = feas
    sp["load_s"] = {}
    builds: dict = {}
    for t in ("sp_mono", "sp_hash", "sp_hashid", "sp_brin"):
        t0 = time.time()
        if t == "sp_mono":
            cur.execute("ALTER TABLE sp_mono ADD PRIMARY KEY (id)")
            cur.execute(
                "ALTER TABLE sp_mono ADD CONSTRAINT sp_mono_uq UNIQUE (id, dataset_id)"
            )
            for ddl in records_indexes("sp_mono"):
                cur.execute(ddl)
        elif t in ("sp_hash", "sp_hashid"):
            if t == "sp_hash":
                cur.execute(
                    "ALTER TABLE sp_hash ADD CONSTRAINT sp_hash_uq UNIQUE (id, dataset_id)"
                )
            # on the parent: Postgres creates one index per partition
            for ddl in records_indexes(t):
                cur.execute(ddl)
        else:
            cur.execute("ALTER TABLE sp_brin ADD PRIMARY KEY (id)")
            # BRIN on created_at replaces the two (dataset, created) B-trees; keep the rest.
            keep = [
                d
                for d in records_indexes("sp_brin")
                if "ds_created" not in d and "schema_created" not in d
            ]
            for ddl in keep:
                cur.execute(ddl)
            cur.execute(
                "CREATE INDEX sp_brin_created ON sp_brin USING brin (created_at) WITH (pages_per_range = 32)"
            )
        builds[t] = round(time.time() - t0, 1)
        cur.execute(f"ANALYZE {t}")
    sp["index_build_s"] = builds

    sizes = {}
    for t in ("sp_mono", "sp_hash", "sp_hashid", "sp_brin"):
        sizes[t] = {
            "heap_mb": mb(
                size(cur, t)
                if t not in ("sp_hash", "sp_hashid")
                else one(
                    cur,
                    "SELECT sum(pg_relation_size(c.oid)) FROM pg_inherits i JOIN pg_class c ON c.oid=i.inhrelid "
                    "WHERE i.inhparent = %s::regclass",
                    (t,),
                )
            ),
            "total_mb": mb(
                one(cur, "SELECT pg_total_relation_size(%s::regclass)", (t,))
                if t not in ("sp_hash", "sp_hashid")
                else one(
                    cur,
                    "SELECT sum(pg_total_relation_size(c.oid)) FROM pg_inherits i JOIN pg_class c "
                    "ON c.oid=i.inhrelid WHERE i.inhparent = %s::regclass",
                    (t,),
                )
            ),
        }
    sizes["sp_brin"]["brin_index_mb"] = mb(size(cur, "sp_brin_created"))
    sizes["sp_mono"]["ds_created_btree_mb"] = mb(size(cur, "sp_mono_ds_created"))
    sizes["sp_mono"]["live_ds_created_partial_mb"] = mb(
        size(cur, "sp_mono_live_ds_created")
    )
    sizes["sp_mono"]["data_gin_mb"] = mb(size(cur, "sp_mono_data_gin"))
    sp["sizes"] = sizes

    # Queries ---------------------------------------------------------------
    big = one(cur, "SELECT id FROM bm_datasets WHERE n = 1")
    small = one(cur, "SELECT id FROM bm_datasets WHERE n = %s", (N_DATASETS,))
    zero = "00000000-0000-0000-0000-000000000000"
    hit = f'{{"{F_SITE}":"site-17","{F_STATUS}":"active"}}'
    pk_probe = one(cur, "SELECT id FROM sp_mono OFFSET %s LIMIT 1", (spike_rows // 3,))
    queries = {
        "keyset_first_page_small_dataset": (
            "SELECT id, data FROM {t} WHERE dataset_id = %s AND deleted_at IS NULL "
            "AND (created_at, id) > (%s, %s) ORDER BY created_at, id LIMIT 50",
            (small, "-infinity", zero),
        ),
        "keyset_first_page_big_dataset": (
            "SELECT id, data FROM {t} WHERE dataset_id = %s AND deleted_at IS NULL "
            "AND (created_at, id) > (%s, %s) ORDER BY created_at, id LIMIT 50",
            (big, "-infinity", zero),
        ),
        "keyset_by_schema_no_dataset_filter": (
            "SELECT id FROM {t} WHERE schema_id = (SELECT id FROM bm_schemas WHERE n = 1) AND deleted_at IS NULL "
            "AND (created_at, id) > (%s, %s) ORDER BY created_at, id LIMIT 50",
            ("-infinity", zero),
        ),
        "jsonb_contains_in_dataset": (
            "SELECT count(*) FROM {t} WHERE dataset_id = %s AND data @> %s::jsonb",
            (big, hit),
        ),
        "jsonb_contains_rare_whole_table": (
            "SELECT id FROM {t} WHERE data @> %s::jsonb",
            (f'{{"{F_SITE}":"site-17","{F_NAME}":"name-5"}}',),
        ),
        "fts_rare_word_whole_table": (
            "SELECT id FROM {t} WHERE search_vector @@ to_tsquery('simple','w1999') LIMIT 20",
            (),
        ),
        "count_live_big_dataset": (
            "SELECT count(*) FROM {t} WHERE dataset_id = %s AND deleted_at IS NULL",
            (big,),
        ),
        "time_window_whole_table_1day": (
            "SELECT count(*) FROM {t} WHERE created_at >= timestamptz '2024-03-01' AND created_at < timestamptz '2024-03-02'",
            (),
        ),
        "pk_lookup_by_id_only": (
            "SELECT id FROM {t} WHERE id = %s",
            (pk_probe,),
        ),
    }
    qres: dict = {}
    for name, (sql, params) in queries.items():
        qres[name] = {}
        for t in ("sp_mono", "sp_hash", "sp_hashid", "sp_brin"):
            s = sql.format(t=t)
            res = timed(cur, s, params, reps=3)
            res["plan"] = plan_nodes(explain_json(cur, s, params)["Plan"])[:6]
            plan = explain_json(cur, s, params)
            res["planning_ms"] = round(plan.get("Planning Time", 0), 2)
            qres[name][t] = res
    sp["queries"] = qres

    # Row movement: "move a collection" changes dataset_id => changes partition.
    t0 = time.perf_counter()
    cur.execute(
        "UPDATE sp_hash SET dataset_id = (SELECT id FROM bm_datasets WHERE n = 199) WHERE dataset_id = %s",
        (small,),
    )
    sp["move_small_collection_hash_s"] = {
        "rows": cur.rowcount,
        "seconds": round(time.perf_counter() - t0, 2),
    }
    t0 = time.perf_counter()
    cur.execute(
        "UPDATE sp_mono SET dataset_id = (SELECT id FROM bm_datasets WHERE n = 199) WHERE dataset_id = %s",
        (small,),
    )
    sp["move_small_collection_mono_s"] = {
        "rows": cur.rowcount,
        "seconds": round(time.perf_counter() - t0, 2),
    }
    t0 = time.perf_counter()
    cur.execute(
        "UPDATE sp_hashid SET dataset_id = (SELECT id FROM bm_datasets WHERE n = 199) WHERE dataset_id = %s",
        (small,),
    )
    sp["move_small_collection_hash_by_id_s"] = {
        "rows": cur.rowcount,
        "seconds": round(time.perf_counter() - t0, 2),
    }

    # Insert throughput into partitioned vs monolithic (indexes live) ---------
    ins = {}
    n = 200_000
    for t in ("sp_mono", "sp_hash", "sp_hashid"):
        t0 = time.perf_counter()
        cur.execute(
            f"""INSERT INTO {t} (id, dataset_id, schema_id, data, created_at, updated_at)
                SELECT gen_random_uuid(), (SELECT id FROM bm_datasets WHERE n = 1 + g % 40),
                       (SELECT id FROM bm_schemas WHERE n = 1),
                       jsonb_build_object('{F_NAME}', 'ins-' || g, '{F_SITE}', 'site-' || (g % 50)),
                       now(), now() FROM generate_series(1, {n}) g"""
        )
        ins[t] = round(n / (time.perf_counter() - t0))
    sp["insert_rows_per_s_indexes_live"] = ins

    # audit_log: monolithic vs monthly range partitions -------------------------
    log("spike: audit_log time partitioning")
    cur.execute(f"CREATE TABLE sp_aud_mono ({AUDIT_COLS})")
    cur.execute(
        f'CREATE TABLE sp_aud_part ({AUDIT_COLS}, PRIMARY KEY (id, "timestamp")) '
        f'PARTITION BY RANGE ("timestamp")'
    )
    for k in range(26):  # 2024-01 .. 2026-02
        y, mth = 2024 + k // 12, k % 12 + 1
        ny, nm = (y + 1, 1) if mth == 12 else (y, mth + 1)
        cur.execute(
            f"CREATE TABLE sp_aud_part_{y}{mth:02d} PARTITION OF sp_aud_part "
            f"FOR VALUES FROM ('{y}-{mth:02d}-01') TO ('{ny}-{nm:02d}-01')"
        )
    cur.execute(
        'INSERT INTO sp_aud_mono SELECT * FROM bm_audit ORDER BY "timestamp" LIMIT %s',
        (spike_rows,),
    )
    cur.execute(
        'INSERT INTO sp_aud_part SELECT * FROM bm_audit ORDER BY "timestamp" LIMIT %s',
        (spike_rows,),
    )
    cur.execute("ALTER TABLE sp_aud_mono ADD PRIMARY KEY (id)")
    for t in ("sp_aud_mono", "sp_aud_part"):
        for ddl in audit_indexes(t):
            cur.execute(ddl)
        cur.execute(f"ANALYZE {t}")
    # hub_seq uniqueness: a global unique needs the partition key
    try:
        cur.execute(
            "CREATE UNIQUE INDEX sp_aud_part_hub_seq_uq ON sp_aud_part (hub_seq)"
        )
        sp["audit_unique_hub_seq_on_time_partitioned"] = "ok"
    except psycopg2.Error as e:
        sp["audit_unique_hub_seq_on_time_partitioned"] = (
            f"ERROR: {e.pgerror.splitlines()[0]}"
        )
    cur.execute('SELECT max("timestamp") FROM sp_aud_mono')
    ent_probe = one(
        cur, "SELECT entity_id FROM sp_aud_mono OFFSET %s LIMIT 1", (spike_rows // 3,)
    )
    aq = {
        "history_of_one_entity": (
            'SELECT id FROM {t} WHERE entity_id = %s ORDER BY "timestamp"',
            (ent_probe,),
        ),
        "hub_seq_feed_1000": (
            "SELECT id FROM {t} WHERE hub_seq > %s ORDER BY hub_seq LIMIT 1000",
            (spike_rows // 2,),
        ),
        "time_range_1day_count": (
            "SELECT count(*) FROM {t} WHERE \"timestamp\" >= timestamptz '2024-03-01' "
            "AND \"timestamp\" < timestamptz '2024-03-02'",
            (),
        ),
        "max_hub_seq": ("SELECT max(hub_seq) FROM {t}", ()),
    }
    ares: dict = {}
    for name, (sql, params) in aq.items():
        ares[name] = {}
        for t in ("sp_aud_mono", "sp_aud_part"):
            s = sql.format(t=t)
            res = timed(cur, s, params, reps=3)
            res["plan"] = plan_nodes(explain_json(cur, s, params)["Plan"])[:5]
            ares[name][t] = res
    sp["audit_queries"] = ares
    t0 = time.perf_counter()
    cur.execute("ALTER TABLE sp_aud_part DETACH PARTITION sp_aud_part_202401")
    cur.execute("DROP TABLE sp_aud_part_202401")
    sp["audit_drop_oldest_month_partition_s"] = round(time.perf_counter() - t0, 3)
    n_old = one(
        cur,
        """SELECT count(*) FROM sp_aud_mono WHERE "timestamp" < timestamptz '2024-02-01'""",
    )
    t0 = time.perf_counter()
    cur.execute(
        """DELETE FROM sp_aud_mono WHERE "timestamp" < timestamptz '2024-02-01'"""
    )
    sp["audit_delete_oldest_month_monolithic"] = {
        "rows": n_old,
        "seconds": round(time.perf_counter() - t0, 2),
    }
    sp["audit_sizes_mb"] = {
        "mono_total": mb(total_size(cur, "sp_aud_mono")),
        "part_total": mb(
            one(
                cur,
                "SELECT sum(pg_total_relation_size(c.oid)) FROM pg_inherits i JOIN pg_class c "
                "ON c.oid=i.inhrelid WHERE i.inhparent = 'sp_aud_part'::regclass",
            )
        ),
    }

    # Large JSONB: inline vs side table ---------------------------------------
    log("spike: large JSONB inline vs side table")
    side_rows = min(spike_rows, 500_000)
    # ~6.4 KB of hex text (correlated on g so it is per-row), too big to stay inline
    blob = "(SELECT string_agg(md5(g::text || k), '') FROM generate_series(1, 200) k)"
    cur.execute(
        "CREATE TABLE sp_blob_inline (id UUID PRIMARY KEY, dataset_id UUID NOT NULL, data JSONB NOT NULL)"
    )
    cur.execute(
        "CREATE TABLE sp_blob_small (id UUID PRIMARY KEY, dataset_id UUID NOT NULL, data JSONB NOT NULL)"
    )
    cur.execute(
        "CREATE TABLE sp_blob_side (record_id UUID PRIMARY KEY REFERENCES sp_blob_small(id), payload JSONB NOT NULL)"
    )
    cur.execute(
        f"""CREATE TEMP TABLE sp_ids AS SELECT gen_random_uuid() id, g FROM generate_series(1,{side_rows}) g"""
    )
    cur.execute(
        f"""INSERT INTO sp_blob_inline SELECT id, (SELECT id FROM bm_datasets WHERE n = 1 + g % 50),
              jsonb_build_object('{F_NAME}', 'name-' || g, '{F_STATUS}', 'active', '{F_COUNT}', g % 1000,
                                 'trace', {blob}) FROM sp_ids"""
    )
    cur.execute(
        f"""INSERT INTO sp_blob_small SELECT id, (SELECT id FROM bm_datasets WHERE n = 1 + g % 50),
              jsonb_build_object('{F_NAME}', 'name-' || g, '{F_STATUS}', 'active', '{F_COUNT}', g % 1000) FROM sp_ids"""
    )
    cur.execute(
        f"INSERT INTO sp_blob_side SELECT id, jsonb_build_object('trace', {blob}) FROM sp_ids"
    )
    for t in ("sp_blob_inline", "sp_blob_small"):
        cur.execute(f"CREATE INDEX {t}_gin ON {t} USING gin (data)")
    cur.execute("ANALYZE sp_blob_inline")
    cur.execute("ANALYZE sp_blob_small")
    cur.execute("ANALYZE sp_blob_side")
    blobres: dict = {"rows": side_rows}
    blobres["inline"] = {
        "heap_mb": mb(size(cur, "sp_blob_inline")),
        "toast_mb": mb(
            one(
                cur,
                "SELECT pg_total_relation_size(reltoastrelid) FROM pg_class "
                "WHERE relname = 'sp_blob_inline'",
            )
        ),
        "gin_mb": mb(size(cur, "sp_blob_inline_gin")),
    }
    blobres["split_hot"] = {
        "heap_mb": mb(size(cur, "sp_blob_small")),
        "gin_mb": mb(size(cur, "sp_blob_small_gin")),
        "side_total_mb": mb(total_size(cur, "sp_blob_side")),
    }
    blobres["list_page_inline"] = timed(
        cur,
        "SELECT id, data FROM sp_blob_inline WHERE dataset_id = (SELECT id FROM bm_datasets WHERE n = 1) LIMIT 1000",
        reps=3,
    )
    blobres["list_page_split"] = timed(
        cur,
        "SELECT id, data FROM sp_blob_small WHERE dataset_id = (SELECT id FROM bm_datasets WHERE n = 1) LIMIT 1000",
        reps=3,
    )
    blobres["agg_count_by_status_inline"] = timed(
        cur,
        f"SELECT data->>'{F_STATUS}', count(*) FROM sp_blob_inline GROUP BY 1",
        reps=2,
    )
    blobres["agg_count_by_status_split"] = timed(
        cur,
        f"SELECT data->>'{F_STATUS}', count(*) FROM sp_blob_small GROUP BY 1",
        reps=2,
    )
    w0 = wal_lsn(cur)
    t0 = time.perf_counter()
    cur.execute(
        f"UPDATE sp_blob_inline SET data = jsonb_set(data, '{{{F_STATUS}}}', '\"done\"') "
        f"WHERE id IN (SELECT id FROM sp_blob_inline LIMIT 100000)"
    )
    blobres["update_small_field_100k_inline"] = {
        "seconds": round(time.perf_counter() - t0, 1),
        "wal_mb": mb(wal_lsn(cur) - w0),
    }
    w0 = wal_lsn(cur)
    t0 = time.perf_counter()
    cur.execute(
        f"UPDATE sp_blob_small SET data = jsonb_set(data, '{{{F_STATUS}}}', '\"done\"') "
        f"WHERE id IN (SELECT id FROM sp_blob_small LIMIT 100000)"
    )
    blobres["update_small_field_100k_split"] = {
        "seconds": round(time.perf_counter() - t0, 1),
        "wal_mb": mb(wal_lsn(cur) - w0),
    }
    sp["jsonb_side_table"] = blobres

    results["spike"] = sp
    for t in (
        "sp_mono",
        "sp_hash",
        "sp_hashid",
        "sp_brin",
        "sp_aud_mono",
        "sp_aud_part",
        "sp_blob_inline",
        "sp_blob_small",
        "sp_blob_side",
    ):
        cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")


# --------------------------------------------------------------------------
# catalog: partitions x schemas
# --------------------------------------------------------------------------


def catalog(cur, results: dict, n_schemas: int = 40) -> None:
    """Build n_schemas repo schemas with records/audit, unpartitioned vs partitioned,
    and read the system-catalog growth. The hub gives every repo its own schema."""
    log(f"catalog: {n_schemas} schemas x variants")
    out: dict = {}

    def counts(prefix: str) -> dict:
        row = q(
            cur,
            """SELECT (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname LIKE %(p)s),
                      (SELECT count(*) FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
                          JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname LIKE %(p)s),
                      (SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid
                          JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname LIKE %(p)s)""",
            {"p": prefix + "%"},
        )[0]
        return {
            "pg_class_rows": row[0],
            "pg_attribute_rows": row[1],
            "pg_index_rows": row[2],
        }

    variants = {
        "unpartitioned": (0, 0),
        "records_hash_8": (8, 0),
        "records_hash_16": (16, 0),
        "records_hash_16_audit_monthly_24": (16, 24),
    }
    for name, (hp, ap) in variants.items():
        pre = f"bmcat_{name}_"
        for i in range(n_schemas):
            cur.execute(f"DROP SCHEMA IF EXISTS {pre}{i} CASCADE")
        before = one(
            cur,
            "SELECT sum(pg_total_relation_size(c.oid)) FROM pg_class c JOIN pg_namespace n ON "
            "n.oid=c.relnamespace WHERE n.nspname = 'pg_catalog'",
        )
        t0 = time.time()
        for i in range(n_schemas):
            s = f"{pre}{i}"
            cur.execute(f"CREATE SCHEMA {s}")
            cur.execute(f"SET search_path = {s}")
            if hp:
                cur.execute(
                    f"CREATE TABLE records ({RECORDS_COLS}, PRIMARY KEY (id, dataset_id)) PARTITION BY HASH (dataset_id)"
                )
                for p in range(hp):
                    cur.execute(
                        f"CREATE TABLE records_p{p} PARTITION OF records FOR VALUES WITH (MODULUS {hp}, REMAINDER {p})"
                    )
            else:
                cur.execute(f"CREATE TABLE records ({RECORDS_COLS}, PRIMARY KEY (id))")
            cur.execute("ALTER TABLE records ADD CONSTRAINT uq UNIQUE (id, dataset_id)")
            for ddl in records_indexes("records"):
                cur.execute(ddl)
            if ap:
                cur.execute(
                    f'CREATE TABLE audit_log ({AUDIT_COLS}, PRIMARY KEY (id, "timestamp")) PARTITION BY RANGE ("timestamp")'
                )
                for k in range(ap):
                    y, mth = 2025 + k // 12, k % 12 + 1
                    ny, nm = (y + 1, 1) if mth == 12 else (y, mth + 1)
                    cur.execute(
                        f"CREATE TABLE audit_log_{y}{mth:02d} PARTITION OF audit_log "
                        f"FOR VALUES FROM ('{y}-{mth:02d}-01') TO ('{ny}-{nm:02d}-01')"
                    )
            else:
                cur.execute(f"CREATE TABLE audit_log ({AUDIT_COLS}, PRIMARY KEY (id))")
            for ddl in audit_indexes("audit_log"):
                cur.execute(ddl)
            cur.execute("RESET search_path")
        build_s = time.time() - t0
        c = counts(pre)
        c["create_seconds_per_schema"] = round(build_s / n_schemas, 3)
        c["pg_class_rows_per_schema"] = round(c["pg_class_rows"] / n_schemas, 1)
        c["pg_attribute_rows_per_schema"] = round(c["pg_attribute_rows"] / n_schemas, 1)
        c["catalog_mb_total"] = mb(
            one(
                cur,
                "SELECT sum(pg_total_relation_size(c.oid)) FROM pg_class c JOIN pg_namespace n ON "
                "n.oid=c.relnamespace WHERE n.nspname = 'pg_catalog'",
            )
            - before
        )
        # DROP SCHEMA timing: what deleting a repo costs the catalog
        t0 = time.time()
        cur.execute(f"DROP SCHEMA {pre}0 CASCADE")
        c["drop_one_schema_s"] = round(time.time() - t0, 3)
        # A query that cannot prune opens every partition + every index; lock count is what
        # max_locks_per_transaction budgets for.
        cur.execute("BEGIN")
        cur.execute(f"SET LOCAL search_path = {pre}1")
        cur.execute("SELECT count(*) FROM records WHERE data @> '{\"a\":1}'")
        c["locks_for_unpruned_records_query"] = one(
            cur,
            "SELECT count(*) FROM pg_locks WHERE pid = pg_backend_pid() AND locktype = 'relation'",
        )
        cur.execute("ROLLBACK")
        out[name] = c
        for i in range(n_schemas):
            cur.execute(f"DROP SCHEMA IF EXISTS {pre}{i} CASCADE")
    out["schemas"] = n_schemas
    out["max_locks_per_transaction"] = one(cur, "SHOW max_locks_per_transaction")
    results["catalog"] = out


# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--rows", type=int, default=20_000_000, help="records (and audit rows) to seed"
    )
    ap.add_argument(
        "--spike-rows",
        type=int,
        default=SPIKE_ROWS_DEFAULT,
        help="rows in the spike comparison tables",
    )
    ap.add_argument(
        "--phase",
        action="append",
        choices=["seed", "measure", "ids", "spike", "catalog"],
        help="run only these phases (default: all, in order)",
    )
    ap.add_argument("--out", default="scale-results.json")
    ap.add_argument("--keep", action="store_true", help="keep bm_* tables afterwards")
    args = ap.parse_args()

    phases = args.phase or ["seed", "measure", "ids", "spike", "catalog"]
    conn = connect()
    cur = conn.cursor()
    results: dict = {}
    if os.path.exists(args.out):
        results = json.load(open(args.out))
    if "seed" in phases or "rows" not in results:
        results["rows"] = args.rows
    results["postgres"] = one(cur, "SHOW server_version")
    results["settings"] = {
        k: one(cur, f"SHOW {k}")
        for k in (
            "shared_buffers",
            "work_mem",
            "maintenance_work_mem",
            "max_wal_size",
            "effective_cache_size",
        )
    }
    for ph in phases:
        {
            "seed": lambda: seed(cur, args.rows, results),
            "measure": lambda: measure(cur, results),
            "ids": lambda: id_order(cur, results),
            "spike": lambda: spike(cur, args.spike_rows, results),
            "catalog": lambda: catalog(cur, results),
        }[ph]()
        json.dump(results, open(args.out, "w"), indent=2, default=str)
        log(f"phase {ph} done -> {args.out}")
    # Only after a clean finish: a failed run keeps its tables so a phase can be rerun.
    if not args.keep and phases[-1] in ("spike", "catalog"):
        for t in ("bm_audit", "bm_records", "bm_datasets", "bm_schemas"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
