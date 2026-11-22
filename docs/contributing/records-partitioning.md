# Partitioned `records` and `audit_log` (PostgreSQL), and time-ordered ids

Status: shipped in migration `b5d8f1a3c6e2`. Follows the measurements and
options in the billion-row design note (civex-service PR #418,
`docs/contributing/billion-row-collections.md`); this note records what was
built, why those choices, and what it cost, with numbers from
`benchmarks/bench_partitioning.py`.

civex-hub hosts one civex repository per PostgreSQL schema (`repo_<hex>`) and
wants repositories with billions of records. Reads were never the problem (the
indexes bound them); inserts and maintenance were. Three changes:

1. New rows of the busy tables get **time-ordered ids**.
2. PostgreSQL `records` is **`PARTITION BY HASH (id)`**.
3. PostgreSQL `audit_log` is **`PARTITION BY RANGE (timestamp)`, monthly**.

SQLite is unchanged: plain tables, same ids behaviour minus nothing (it has no
partitioning and is single-user).

## 1. Time-ordered ids

`civex.domain.ids.row_id()` (pure Python, works on SQLite too) is the default for `records.id`, `audit_log.id`
and `file_references.id` (everything else stays `uuid4`). Rows already stored
keep their ids; old and new mix freely; the column type and wire format are
unchanged.

**It is not RFC 9562 UUIDv7, deliberately.** Pure v7 (`ids.uuid7()`, kept and
tested) starts with a 48-bit millisecond timestamp, so the first 8 hex
characters are identical for every row made in the same 65 seconds. civex
prints and accepts those 8 characters as the short id everywhere (CLI
`history show <id>`, `record set --id`, `get_by_prefix`, the UI's id labels,
about 35 call sites and 25 tests), and under v7 the short id of a new row would
be ambiguous with every other row of the minute. `row_id()` is a UUIDv8
(RFC 9562's custom layout) whose first 32 bits are the **microsecond clock
modulo 2^32**, then a 16-bit counter, the version nibble, and 74 random bits:

- inserts still land next to each other in an index (the insertion point sweeps
  through the key space once every 71.6 minutes instead of jumping to a random
  leaf per row), which is where the speed-up comes from;
- the first 8 hex characters are as distinct as a random id's, so short ids
  keep working;
- an id reveals only the time of day modulo 71.6 minutes, not when the row was
  made: the privacy cost of pure v7 (creation time readable from the id) is
  mostly avoided.

Trade-off against pure v7: v7 is append-only (the best case for a B-tree);
`row_id()` is a circular sweep, so at very large sizes each leaf receives a few
inserts per lap instead of thousands (index pages are touched once per lap, not
once per row). Measured below.

## 2. `records`: `PARTITION BY HASH (id)`

Why `id` and not `dataset_id`: four tables have foreign keys onto `records(id)`
and the primary key must contain the partition key; hashing `dataset_id` would
need all four rewritten and would put a hot collection in one partition. With
`HASH (id)` the primary key stays `(id)`, `(id, dataset_id)` stays unique, the
deferred self-foreign-key stays valid, every index (the two partial live B-trees
and both GINs) is kept as a partitioned index, and the search-vector trigger is
carried over. The ORM and every query are unchanged.

What it buys: a partition is the unit vacuum, `REINDEX`, GIN rebuilds and bulk
loads work on (1/8 of a repository at a time), and parallel workers spread
across partitions. What it does not buy: read latency. Every collection-scoped
query touches every partition, so pruned point reads get slightly slower
(table below). It is a maintenance feature, taken now for every repository on
the user's decision rather than only for outliers.

**Modulus.** `PartitionLayout.records_partitions`, default **8**; `0`/`1` (or
`CIVEX_RECORDS_PARTITIONS=off`, or `[db] records_partitions = 1` in
`config.toml`) keeps a plain table for tiny deployments. Set it before the
database first migrates (`civex.config.PartitionLayout`, which
`ensure_schema_current(engine, layout)` takes; the hub's `create_repo_schema` and
`migrate-repos` should pass one, or set the environment, to choose per
deployment); it is only read by migration `b5d8f1a3c6e2`
(`partitioning.partition_records(conn, n)` re-lays out an existing table later).
Use a power of two so a later split is a clean doubling.

Catalog cost per repository schema (measured on PostgreSQL 18.6 by creating an
empty schema; `pg_class` rows include heaps, TOAST tables and indexes; "locks"
is the relation locks one statement that touches every partition of `records`
takes, beyond a baseline of 20):

| Layout | `pg_class` rows | `pg_attribute` rows | locks, unpruned `records` query |
|---|---|---|---|
| nothing partitioned | 108 | 582 | 0 |
| `audit_log` monthly only | 148 | 752 | 0 |
| `records` x2 + audit | 172 | 820 | 24 |
| `records` x4 + audit | 196 | 888 | 48 |
| **`records` x8 + audit (default)** | **244** | **1,024** | **96** |
| `records` x16 + audit | 340 | 1,296 | 192 |

Each `records` partition adds 12 `pg_class` rows (heap, TOAST heap and index, 11
indexes) and 8 locks to any statement that cannot prune; each `audit_log`
partition about 8 rows. For 10,000 repositories the default is **2.4M**
`pg_class` rows (1.1M unpartitioned) and about 10M `pg_attribute` rows, and a
statement over all `records` partitions takes ~116 relation locks against the
default `max_locks_per_transaction = 64` (a pool-wide average: it works while
few statements are in that shape at once, and a cross-partition `pg_dump` or
migration takes them all). x8 is the default because it is the smallest
modulus that gives 1/8-size maintenance units and a useful degree of parallel
scan while keeping the per-schema overhead (+136 relations) and the lock count
under one `max_locks_per_transaction` budget; x16 doubles both. Hosts running
tens of thousands of schemas should raise `max_locks_per_transaction` and
`shared_buffers` for the relcache, or choose 4.

## 3. `audit_log`: `PARTITION BY RANGE ("timestamp")`, monthly

- Partitions: `audit_log_y2026m11` ... one per month, from this month to
  `months_ahead` (default 2) months ahead; `audit_log_early` for everything
  older than the first month (a device pushing years of history to a new
  repository lands here, never in the default partition); `audit_log_default`
  for anything beyond the horizon.
- Future months: `civex.db.migrate.ensure_audit_partitions(engine)` creates
  the missing ones (this month and `months_ahead`, default 2). civex calls a
  throttled form (`ensure_audit_partitions_daily`: at most one catalog check a
  day per engine, never raises) when a database is migrated and every time it
  builds a request context, so a server that stays up for months keeps creating
  them. **Hosts that do not build contexts for a repository (civex-hub's
  `migrate-repos`, a cron) should also call `ensure_audit_partitions(engine)`
  daily.** It is safe from several processes at once, gives up quietly after a
  3 s lock timeout or when a writer races it, and a host that forgets is safe,
  not broken: rows for a month with no partition go to `audit_log_default`, and
  the next call moves them into the new month's partition. That move holds
  `audit_log_default` (writers to it wait) for as long as the move takes, so
  keep the top-up running: with it, the default partition is empty.
- **`hub_seq` uniqueness.** The billion-row note says partitioning loses
  `audit_log`'s unique `hub_seq` index. On `main` that index never existed:
  `ix_audit_log_hub_seq` is a plain index (migration `c9e1f4a7b3d2`), and the
  uniqueness comes from the counter `sync_meta.head_seq`, which
  `next_hub_seq()` increments atomically in the database. Nothing is lost, and
  the plain index is kept (per partition) for the feed.
- **What is lost: `audit_log.id` uniqueness across partitions.** The primary key
  is now `(id, timestamp)` (a partitioned table's key must contain the partition
  key). An id still cannot repeat *with the same timestamp*, and ids are 122-bit
  random-ish, so a collision is not a practical concern. Nothing relies on the
  database to reject a repeated id with a different timestamp: the authority
  answers a re-sent entry from `sync_ops` (keyed by the entry's id, and
  pushes are serialised) before it writes, the pull path checks `has_entry`, and
  the deterministic `uuid5` seed ids go through the same `sync_ops` check.
  Nothing has a foreign key onto `audit_log.id`.
- Cost: a lookup by `id` alone (`session.get(AuditLog, id)`) probes every
  partition's primary key (one per month; ~1 ms at 29 partitions), and
  `max(hub_seq)` merges partitions (0.17 -> 0.85 ms).

## 4. Migration for existing databases

One revision, `b5d8f1a3c6e2`, run per schema by `ensure_schema_current` (so
`civexhub migrate-repos` applies it fleet-wide). PostgreSQL only; a no-op on
SQLite.

Algorithm (`civex.db.partitioning._rebuild`, same for both tables, reversible
by `downgrade`):

1. `LOCK ... IN SHARE ROW EXCLUSIVE MODE` on the table and on every table with a
   foreign key onto it (120 s `lock_timeout`; if a lock cannot be had the whole
   migration rolls back before anything is copied). Writers wait from here.
2. Read every index, constraint, foreign key and trigger from the catalog (so
   nothing can drift from what the table actually has).
3. `CREATE TABLE records__new (LIKE records ...) PARTITION BY HASH (id)` plus the
   partitions; `INSERT INTO records__new SELECT * FROM records`.
4. Create the constraints, indexes (partial and GIN included) and the other
   tables' foreign keys against the new table under temporary names, **before**
   the swap. Foreign keys are validated here, while the old table still serves
   readers.
5. `DROP TABLE records CASCADE` (refused up front if a view depends on it or
   row-level security is on), rename the new table, constraints and indexes to
   their old names, recreate the trigger, carry over the owner, grants and
   per-table storage settings (autovacuum tuning goes on each partition), then
   `ANALYZE`. Only this step takes ACCESS EXCLUSIVE: milliseconds. Column
   statistics targets are not carried over.

It is **atomic, not chunked**: everything runs in the migration's transaction,
so a failure (including killing the process) leaves the old table exactly as it
was and the next start retries; there is nothing half-copied to tell from a
finished copy and no resume state to get wrong. The price is that writers wait
for the copy plus the index builds and the transaction holds its WAL until
commit.

Measured (PostgreSQL 18.6, 256 MB `shared_buffers`, shared host, 5.0M records,
~1.5 KB/row including indexes, one hot collection):

| | records (5.0M) | per million rows | audit_log (5.0M) | per million rows |
|---|---|---|---|---|
| time, writers blocked | 248-261 s (two runs) | **~50 s** | 18.7 s | **3.7 s** |
| time, readers blocked | milliseconds | | milliseconds | |
| WAL written | 12.5-12.7 GB | 2.5 GB | 1.6 GB | 0.3 GB |

Budget about **1 minute of write downtime per million records** (the GIN indexes
are most of it) and 2.5 GB of WAL and as much free disk again as the table
(old and new coexist until the swap), on top of a normal day's WAL. A 100M-row
repository would be ~1.5 hours of write downtime: convert it offline, or opt it
out (`records_partitions = 1`) and call `partition_records` in a maintenance
window. An empty or new database converts in ~0.3 s (the migration chain
builds the table plain and this revision converts it; that is the "gate":
`records_partitions < 2` skips it, and an empty table makes it free).

**Deploy order for the hub.** The migration also runs on demand when any process
opens an unmigrated schema. For a repository with data that is a long write
stall inside a request, so run `civexhub migrate-repos` (serially, or with the
bounded pool noted in civex-hub's CLAUDE.md) before rolling out this civex
version; new repositories are unaffected.

## 5. Benchmarks

`benchmarks/bench_partitioning.py`: seeds one schema with N records (200
collections, one holding 57%; 8 fields; 2% soft-deleted; trigger-computed
search vector), measures it plain, converts it in place with the migration code,
measures the same data partitioned. PostgreSQL 18.6, `shared_buffers=256MB`,
`max_wal_size=1GB`, 7.5 GB RAM shared with other jobs, 5.0M records (16.8 GB
with indexes), medians of 7 runs after a warm-up. Single runs on a shared host:
treat differences under ~2x as noise.

Reads (ms, median):

| Query | plain | HASH(id) x8 |
|---|---|---|
| keyset page, hot collection, 40% deep | 1.26 | 1.44 |
| keyset page, hot collection, first | 0.51 | 0.87 |
| keyset page, small collection | 0.68 | 1.19 |
| lookup by `id` (average of 300, incl. round trip) | 0.76 | 0.80 |
| GIN `@>`, in collection, `LIMIT 50` | 13.0 | 34.5 |
| GIN `@>`, same, `count(*)` | 16.9 | 32.5 |
| GIN `@>` rare value, whole table | 0.43 | 1.18 |
| full-text, rare word, in collection | 0.29 | 0.46 |
| exact `count(*)`, hot collection (2.8M live) | 148 | 114 |
| relation locks, one keyset page | 13 | 109 |

As the design note predicted: nothing that was index-bounded gets faster,
pruned-index queries pay a small planning and Append cost, and the linear scans
(exact count) gain from parallelism. The GIN containment query is the one
visible regression (3x here; 8 smaller indexes each probed) and is a
reasonable thing to revisit with `jsonb_path_ops`.

Inserts, 100,000 rows through all indexes and the search-vector trigger, after
a checkpoint, into the 5M-row table:

| ids | plain: rows/s | WAL/row | HASH(id) x8: rows/s | WAL/row |
|---|---|---|---|---|
| random `uuid4` (before) | 5,831 | 8.0 KB | 2,861 | 29 KB |
| pure UUIDv7 (`ids.uuid7`) | 20,480 | 2.7 KB | 11,218 | 8.3 KB |
| `row_id()` (now) | 19,186 | 2.7 KB | 17,364 | 2.9 KB |

(A second full run measured 4,954 / 20,904 and 5,876 / 16,007 rows/s for random
/ v7, plain / partitioned: the ordering of the three 100k-row runs and
background checkpoints move individual cells by 2x, the pattern does not.)
Time-ordered ids are 3-4x the insert rate and 3x less WAL per row at 5M rows,
and `row_id()` keeps essentially all of pure v7's gain. The gap widens with
size: at 20M rows the billion-row note measured random ids at 1.3-1.6k rows/s
and 20-27 KB WAL per row against 15k rows/s and 2.6 KB for v7. The cache-sensitive
GIN rows above moved with the same noise (plain 13 -> 85 ms and partitioned
34 -> 3 ms for the in-collection `@>` page between the two runs), so read nothing
into the GIN difference beyond "same order of magnitude".

Audit log (5.0M entries, 24 months): plain vs monthly, ms median: `max(hub_seq)`
0.17 vs 0.85; sync feed 1000 rows from the middle 1.4 vs 1.7; history of one
entity 0.28 vs 1.03; one day's count 0.30 vs 1.01. 29 partitions.

Reproduce: `PG_URL=postgresql+psycopg2://u@host/db .venv/bin/python
benchmarks/bench_partitioning.py --rows 5000000 --audit-rows 5000000` (about 25
minutes, ~40 GB scratch, schema dropped at the end).

## 6. Things the hub should know

- Estimates: `pg_class.reltuples` of the **parent** of a partitioned table is
  not maintained (autovacuum does not analyze parents). Anything that estimates
  `records` counts from `reltuples` (the keyset/estimated-count work) must sum
  the partitions' `reltuples` or use the planner's `EXPLAIN` estimate;
  `partition_records` runs `ANALYZE` on the parent at the end.
- Per-partition vacuum, reindex and `pg_total_relation_size` work on the
  partitions (`records_p0`..), not the parent, which reports 0.
- `ensure_audit_partitions` should run daily from the hub (see section 3), and
  the hub should set `max_locks_per_transaction` for the number of partitions
  its busiest query takes.
- Mixed-version workers during the migration: writers wait on the lock and
  see the new layout transparently (same table names, same columns); a worker
  running civex from before this revision refuses a database at a revision it
  does not know (`DatabaseTooNewError`), which is the existing behaviour.
