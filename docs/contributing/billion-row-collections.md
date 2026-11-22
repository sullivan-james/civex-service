# Planning for billion-row collections

Status: design note plus measurements. **No production schema change ships with
it.** The benchmark that produced every number is
[`benchmarks/bench_scale.py`](https://github.com/CivexData/civex-service/blob/main/benchmarks/bench_scale.py)
(raw output: `benchmarks/results-20m.json`).

civex-hub hosts many civex repositories, one PostgreSQL schema each, and wants
repositories with billions of records and terabytes of data. This note answers:
where does today's `records` / `audit_log` design stop being fast, what would
partitioning, BRIN or a JSONB side table change, and what should land first.

## Short version

1. At 20M records the *reads* are fine; the *writes* are not. Insert rate falls
   from ~13k rows/s (300k rows) to ~1.3-1.5k rows/s, at ~20-27 KB of WAL per row.
   The cause is the random `uuid4` ids: every insert dirties random leaf pages
   of the primary key and the `(id, dataset_id)` unique index and logs a whole
   page after each checkpoint. Time-ordered ids (uuidv7) measured **10x the
   insert rate and 8x less WAL** on the same table, with no schema change.
2. Exact `count(*)` is the one read that grows linearly (9 s for an 11.5M-row
   collection); the planner estimate was within 0.5%. That is the sibling
   keyset/estimated-count work, not partitioning.
3. Partitioning `records` is not needed to reach hundreds of millions of rows
   in one repository, is blocked by four foreign keys as written, and does not
   help the usual skew (one collection holding over half the rows). Do it last, per
   repository, and by hash of `id`, not `dataset_id`.
4. Time-partitioning `audit_log` is cheap and legal (no foreign key points at
   it), but its benefit at these sizes is maintenance, not query speed, and it
   costs `hub_seq` its unique index. Do it when an audit table passes ~100M rows.
5. BRIN on `created_at` cannot replace the `(dataset_id, created_at)` B-trees
   (keyset on a big collection went from <1 ms to 250 ms). A JSONB side table
   is a real win only for records carrying kilobyte-sized values.

## What was measured, and how far it can be trusted

Machine: PostgreSQL 18.6, `shared_buffers=256MB`, `max_wal_size=1GB`,
`work_mem=32MB`, 7.5 GB RAM shared with other jobs, NVMe-class disk under WSL2.
Timings are the median of 2-5 timed runs after one warm-up (2 for the slowest
queries; the raw JSON has min/median/max), so reads are warm-ish but the 20M-row table (17 GB heap, 28 GB with indexes) is far larger than
memory: this is a small-RAM, large-data box on purpose, which is the regime
where index and WAL behaviour shows.

**Scale reached: 20M records + 20M audit rows, not 100M.** Seeding ran at
~19k records/s (17 min for records, 1.7 min for audit, 8 min of index builds).
100M would have needed ~1.5 h to seed plus ~140 GB of disk, beyond the ~30 min
budget. Where this note says "at 100M" or "at 1B" it is an extrapolation and
says so; sizes and rebuild times scale linearly, and the insert and
keyset behaviour is argued from the mechanism, not measured.

Synthetic data: 200 collections, one holding ~57% of rows (a hot collection; 11.5M of 20M),
the rest skewed; 891 bytes per record; 8 fields keyed by field UUID; 2% soft
deleted; `created_at` rises with insert order; audit rows are delta-format.
Seeding bypasses the `search_vector` trigger (the vector is computed inline)
and builds indexes after loading; insert throughput is measured separately on
the finished table with all indexes and the trigger live. `audit_log` omits a
few narrow columns (`device`, `op_id`, ...).

Single runs on a shared host: treat differences under ~2x between variants as
noise (the spike's per-variant query timings can be moved by whichever table
happened to be in cache).

## Behaviour of `records` and `audit_log` at 20M rows

### Size

| | rows | heap | indexes | total |
|---|---|---|---|---|
| `records` | 20.0M | 17.4 GB | 10.3 GB | 27.7 GB (1.4 KB/row) |
| `audit_log` | 20.0M | 5.4 GB | 2.4 GB | 7.8 GB (0.4 KB/row) |

Largest `records` indexes: GIN `data` 3.2 GB, GIN `search_vector` 2.0 GB, the
two partial live indexes 1.1 GB each, `(id, dataset_id)` unique 0.95 GB,
`(dataset_id, created_at)` 0.77 GB, primary key 0.6 GB. Extrapolated linearly,
100M records is ~140 GB and a billion is ~1.4 TB in a single repository schema
(heap alone 870 GB), plus ~40 GB of audit per 100M writes.

### Reads

| Query | 20M rows | Note |
|---|---|---|
| Keyset page (50 rows), big collection, first / 75% deep | 0.5 / 0.7 ms | Partial live index `(dataset_id, created_at, id)` |
| Keyset page, small collection; by `schema_id` | 0.8 / 0.7 ms | |
| `OFFSET 1000000` in the big collection | 0.76 s | What keyset replaces; linear in the offset |
| JSONB `@>` two keys, in collection, `LIMIT 50` | 190 ms (11 ms in an earlier, warmer run) | GIN; very cache-sensitive |
| same, `count(*)` | 0.8 s (1.7 s earlier run) | Bitmap heap scan over ~100k matches |
| JSONB `@>` on a rare value, whole table | 0.2 ms | GIN |
| `data->>'f' = x` with no index (small collection) | 10-14 ms | Scans the collection's range only |
| Full-text, rare word, in collection, `LIMIT 20` | 7 ms | |
| Full-text, ranked, whole table, rare / common word | 46 / 360 ms | `ts_rank` must fetch every match |
| Exact count, big collection (11.5M live) | **9.3 s** (8.7-10.0) | Index-only scan, linear |
| Exact count, whole table | 5.4 s | |
| Estimate: `reltuples` / planner row estimate | 0.1 ms / 11.53M vs 11.48M true | |
| Audit: history of one entity; head `hub_seq`; sync feed 1000 rows deep | 0.1-0.6 ms | B-tree on `hub_seq` |
| Audit: one day's count | 2.9 ms | |

Reads are bounded by index depth, not table size, as long as the query is one
of the indexed shapes. The exceptions are anything that must touch every match:
exact counts, ranked full-text over common words, wide JSONB containment, and
`OFFSET`. Keyset paging and estimated counts (sibling unit) remove the two
that matter for the UI.

### Writes: the real limit

| Insert path, all indexes + trigger live, into the 20M-row table | rows/s | WAL / row |
|---|---|---|
| `INSERT .. SELECT`, trigger on | 1,280 | 27.6 KB |
| same, trigger off (so `search_vector` stays NULL and its GIN is not maintained either) | 2,390 | 21.3 KB |
| client `COPY`, trigger on | 560 | |
| `audit_log` insert | 2,570 | 12.2 KB |
| for reference, same insert at 300k rows (a smoke run of this script; not in the committed JSON) | 13,100 | 4.6 KB |

The `ids` phase of the benchmark isolates the cause: 100k inserts, 20M-row
table, checkpoint before each batch.

| Primary key | rows/s | WAL / row | full-page images / row |
|---|---|---|---|
| `uuid4` (what civex does today) | 1,561 | 19.8 KB | 2.47 |
| `uuidv7` (time-ordered) | 15,357 | 2.6 KB | 0.09 |

Random ids touch a random leaf of the two id-keyed indexes per row; with the
indexes much larger than `shared_buffers`, each is a cache miss plus, after a
checkpoint, a full-page WAL image. Time-ordered ids append at the right edge.
The GIN indexes, the `created_at` B-trees and the search-vector trigger plus its
GIN still cost something (switching both off roughly doubled the rate), so this is the biggest single fix,
not the last. The `audit_log` primary key is `uuid4` too and shows the same
pattern. Caveat: a larger `shared_buffers` / `max_wal_size` would raise the
absolute numbers; the ratio holds whenever the id indexes exceed memory, which
at 100M rows (~11 GB of id indexes) is almost any deployment.

Bulk edits are the other write cliff. Setting one field on 1% of the table
(200k rows) took **434 s and 8.8 GB of WAL (44 KB/row)**: the new row version
is not a HOT update (the GIN, search-vector and every B-tree entry are
rewritten), and the trigger recomputes the vector. A 100M-row repository
editing 1% would be ~1M rows, ~35 min. Bulk operations should be chunked and
should expect this.

### Maintenance

| Operation (20M-row table) | Time |
|---|---|
| `VACUUM (ANALYZE)` after the 1% update / on a clean table | 20 s / 11 s |
| `ANALYZE` | 3 s |
| `REINDEX` the partial live index / the `data` GIN | 33 s / 157 s |
| `VACUUM (ANALYZE)` of `audit_log` (20M rows) | 39 s |
| Seed-time build: GIN `data` / GIN `search_vector` / all 11 `records` indexes | 139 s / 88 s / ~7 min |

Linear extrapolation to 1B rows: a GIN rebuild is ~2.2 h, a vacuum pass
~10-20 min, and a full index rebuild ~6 h per repository. These, not query
latency, are what a billion-row single table is expensive in; they argue for
partitions as a *maintenance* tool (rebuild/vacuum one slice at a time), which
is why partitioning is recommended last and per repository rather than never.

## The spike: partitioning, BRIN, side table

Run on a 3M-row copy of `records` (and `audit_log`), four variants of the same
data, all with the full index set except where noted. Row counts are smaller
than the main run because each variant is a full copy; the 5M-row run is in the
JSON. Feasibility checks are exact, not statistical.

### Constraints: what partitioning forbids

| DDL on a table partitioned by `HASH (dataset_id)` | Result |
|---|---|
| `PRIMARY KEY (id)` / `UNIQUE (id)` | **Error:** unique constraint must include all partitioning columns |
| `PRIMARY KEY (id, dataset_id)`; `UNIQUE (id, dataset_id)` | ok |
| deferred composite self-FK `(parent_record_id, dataset_id) -> (id, dataset_id)` | ok |
| FK from another table to `records(id)` | **Error:** no unique constraint matching the referenced columns |

`models.py` has four foreign keys onto `records.id` alone (`RecordNote`,
`WorkflowJob`, `RecordReference`, `FileReference`; lines ~454, 658, 871, 903). Partitioning by
`dataset_id` therefore means rewriting each to reference `(id, dataset_id)` or
dropping it, and it makes `id` unique only per collection (a record move
between collections, which changes `dataset_id`, becomes a cross-partition row
move). Partitioning by **`HASH (id)`** keeps every one of those constraints
legal: the primary key stays `(id)`, the `(id, dataset_id)` unique and the
composite self-FK contain `id`, and the other tables' FKs still work (all
verified above). It costs the dataset-level pruning.

`audit_log` partitioned by `RANGE (timestamp)`: the primary key must become
`(id, timestamp)`, and a **unique index on `hub_seq` is rejected** (the same
rule). Nothing references `audit_log.id`, so the primary key change is
contained; uniqueness of `hub_seq` would have to rest on the authority that
assigns it, with a plain index for the feed.

**Replays and the `audit_log` key.** With the key `(id, timestamp)` the
database no longer rejects a second row with the same `id` unless the time is
identical too, and nothing may use `ON CONFLICT (id)` on this table. No path
does: an entry made elsewhere is kept only after an existence check by id
(`SyncRepository.has_entry`, in the feed pull and history backfill) or after
the authority's per-event record (`sync_ops`, primary key `op_id`, an
unpartitioned table) says the event is new (push). The push check and its row
are in one transaction, so of two concurrent replays of one event the second
waits on the first's `sync_ops` key and rolls back whole; the pull and backfill
run under the project's sync lock. `tests/sync/test_postgres_audit_replay.py`
replays each path, with the time re-spelled, and expects one row per id.

### Effect on the existing indexes

Both partitioned layouts create the same indexes *per partition*, including the
partial live indexes and both GINs; nothing had to change in their definitions
(`CREATE INDEX` on the parent propagates). Sizes are the same to within 3%
(`records` total 4.18 GB monolithic, 4.28 GB hashed on dataset, 4.29 GB hashed
on id), and build time was in the same range (55-77 s for the whole index set, though the
hash variants' primary keys were built during the load and the others' inside
the timed block, so the times are not strictly comparable).

| 3M rows, median ms | monolithic | hash(dataset_id) x16 | hash(id) x16 | BRIN instead of the `created_at` B-trees |
|---|---|---|---|---|
| keyset page, small collection | 0.4 | 0.6 | 1.2 | 2.4 |
| keyset page, big collection | 0.3 | 0.4 | 1.0 | **249** |
| keyset by `schema_id`, no collection filter | 0.6 | 1.1 | 1.6 | **383** |
| JSONB `@>` in a collection (count) | 87 | 21 | 52 | 61 |
| JSONB `@>` rare value, whole table | 0.2 | 1.7 | 1.6 | 0.2 |
| full-text, rare word | 1.0 | 1.2 | 0.9 | 0.9 |
| exact count, big collection | 411 | 159 | 280 | 251 |
| one-day `created_at` window | 1.3 | 1.7 | 8.8 | 1.3 |
| lookup by `id` alone | 0.17 | 0.58 | 0.19 | 0.15 |

Reading it:

- **Pruned queries get slightly slower, not faster.** Every partitioned plan
  adds planning time (0.5-1 ms vs 0.1 ms) and, for unpruned shapes, an Append
  or Merge Append across 16 index scans. The keyset page stays sub-ms to 1.5
  ms; nothing got faster that was already index-bounded.
- **What partitioning does help is the linear scans** (the exact count and
  the wide `@>`: 2-4x), because each partition is a smaller index and a
  smaller scan, and workers parallelise across partitions. Those numbers are
  from a shared host and a single run each, so only the direction is firm.
- **Skew defeats `hash(dataset_id)`.** The hot collection (half the rows)
  lands whole in one partition, so the biggest collection gets no relief,
  and nothing guarantees an even spread of collections. `hash(id)` spreads
  evenly but every collection-scoped query touches all partitions.
- **Lookup by `id` alone** (used by record fetch, FKs, children) is 3x slower
  under `hash(dataset_id)` because it cannot prune, and unchanged under
  `hash(id)`.
- **Moving a collection:** a `dataset_id` update was 2.4-2.8 s for 2.5k rows in
  the monolithic and hash-by-id tables and 0.3 s in the dataset-hashed one in
  this run; do not read much into the ordering (the first measurement carries
  the cold cache). It works under PostgreSQL's row movement, with the deferred
  FK still checked at commit.
- **Insert rate** did not improve (8.1k monolithic, 7.6k, 5.9k): partitioning
  does not fix random ids; uuidv7 does.
- **BRIN** is tiny (0.4 MB vs ~170 MB for the partial B-tree) and fine for
  "last day across the whole table", but the keyset listing is
  `(dataset_id, created_at, id)` ordered; with no B-tree it falls back to a
  parallel sequential scan and sort. That result shows the
  cost of having no index for the `(dataset_id, created_at)` ordering, not a
  BRIN limitation: BRIN answers range predicates (the one-day window, 1.3 ms
  here) and cannot serve an `ORDER BY .. LIMIT` keyset. The test data is
  loaded in `created_at` order, which flatters BRIN; in a real repository
  with interleaved writers the correlation weakens. Use it as an *addition* for
  time-range scans, not a replacement.
- **Catalog growth (schema-per-repo).** Each repo schema today holds 20
  `pg_class` rows and 72 `pg_attribute` rows for `records` + `audit_log` with
  indexes. Partitioning multiplies that:

| Per repo schema | `pg_class` rows | create time | locks for one unpruned `records` query |
|---|---|---|---|
| unpartitioned | 20 | 0.12 s | 13 |
| `records` hash x8 | 116 | 0.14 s | 109 |
| `records` hash x16 | 212 | 0.22 s | 205 |
| hash x16 + `audit_log` monthly x24 | 380 | 0.50 s | 205 |

For 10,000 repositories that is 200k catalog rows today, **2.1M with
hash x16**, and 3.8M with audit months too, with catalog size scaling
(26 MB per 40 schemas at x16, i.e. ~6.5 GB per 10,000 schemas of catalog
plus relcache memory per backend). An unpruned query takes 205 relation
locks against the default `max_locks_per_transaction` of 64 (a pooled
cluster handles it only because the limit is a pool-wide average; a
cross-partition migration or `pg_dump` takes all of them). So partitioning must
be opt-in per repository, never a default for all tenants.

### Large JSONB: side table

500k rows with a ~6.4 KB value inside `data`, vs the same rows with that value
in a one-to-one `payload` table and only the small fields in `records.data`:

| | inline | split |
|---|---|---|
| heap (hot) | 40 MB (+3.95 GB TOAST) | 112 MB |
| GIN on `data` | 74 MB | 39 MB |
| list page, 1000 rows including `data` | 32 ms | 5.6 ms |
| `GROUP BY` a small field, whole table | 2.8 s | 75 ms |
| update one small field in 100k rows | 26.5 s, 1.8 GB WAL | 3.6 s, 0.29 GB WAL |

PostgreSQL already moves the large value out of line (TOAST), so reads that
skip `data` are fine, but anything that reads `data` de-TOASTs the whole value,
and any update to a small field rewrites the whole large value. For records
whose big values are rarely read with the small ones, the split is 7x on
updates and 38x on aggregates. It is not a win for typical civex records
(~900 bytes), where it only adds a join. It changes the record model and the
sync bundle, so it should be a per-field storage option (a "large value" field
type), not a table split imposed on every repository.

## Recommendation: what lands first

Each step is independently shippable and ordered by (win) / (risk and cost).
All Alembic steps keep history replayable: they are new revisions on top of the
current head, PostgreSQL-specific ones are guarded by
`op.get_bind().dialect.name == "postgresql"` as the existing search-vector
trigger migration is, and SQLite keeps its single unpartitioned table (SQLite
has no partitioning and is single-tenant by design; every step below is a
no-op or application-level there).

1. **Time-ordered ids for new records and audit rows (no migration).** Replace
   `_uuid()` (`db/models.py:84`) with a uuidv7 generator (`uuid.uuid7()` once
   the minimum Python has it; a few lines until then). Existing uuid4 rows keep
   working; ids remain opaque UUIDs so the sync wire format is unaffected.
   Measured 10x insert rate and 8x less WAL at 20M rows. Clients that
   generate ids offline (sync devices) benefit as they upgrade; mixed
   populations are fine. One thing to decide: uuidv7 leaks creation time in
   the id, which uuid4 did not. *This is the single largest win and needs no
   schema change.*
2. **Keyset paging and estimated counts** (sibling unit). Removes `OFFSET` (0.8 s
   at 1M) and the exact counts (9-11 s) from user-facing paths.
3. **Index and write-path diet, measured first.** At 20M rows the GIN `data`
   and `search_vector` are 5.3 of the 10.3 GB of indexes and dominate WAL per
   write. Candidates, none measured here beyond their size: drop
   `ix_records_dataset_created` (0.77 GB, largely redundant with the partial
   live index except for trash views), `ix_records_deleted_at` (0.13 GB, low
   selectivity), `ix_records_dataset_schema` (0.14 GB); make the GIN
   `jsonb_path_ops` (smaller, `@>` only); give bulk loads a path that computes
   the search vector set-wise or defers its GIN (the trigger plus its GIN
   accounted for about half the insert cost; the split is not measured). Each is a normal Alembic drop
   or create, SQLite-safe.
4. **Chunking and write-through-WAL guidance for bulk edits** (application): a
   1% edit costs 44 KB of WAL per row; bound batch sizes and expose progress.
5. **Time-partition `audit_log`, per repository, when it passes ~100M rows.**
   New revision: create `audit_log_p` partitioned by month on `timestamp`
   with `PRIMARY KEY (id, timestamp)`, a plain (non-unique) `hub_seq` index,
   copy in batches, swap names in one transaction, keep the old table until
   verified. Gains: vacuum/reindex per month, cold partitions, a one-statement
   detach. It does not speed up the sync feed (1.1 ms vs 0.5 ms) and costs
   `hub_seq` its unique index and ~7 catalog rows per month per repository, so
   use yearly (or monthly only past a size threshold) partitions. The hub
   schema-per-repo model means this runs per schema, driven by the hub's
   `migrate-repos`, not by civex's startup migration.
6. **Partition `records`, only for a repository that needs it, by `HASH (id)`.**
   Same promotion mechanism as step 5 (an operator-triggered per-schema
   rebuild, recorded in a small `civex_layout` marker so civex and the hub know
   which layout a schema has). `hash(id)` keeps all existing constraints, and
   16 partitions keep rebuilds and vacuums to ~1/16 of the table. Do not use
   `hash(dataset_id)`: it needs four foreign-key rewrites, makes `id` non-unique
   across collections, and leaves the hot collection in one partition. The
   `models.py` drift check (`make migrations-check`) compares on SQLite, so
   the partitioned layout is described in the migration, not declared on
   `Record.__table_args__`.
7. **Side-store for large JSONB values**, as an opt-in field storage mode, when
   a customer actually has kilobyte values (the measurements above are for
   6 KB values).
8. **Add BRIN on `created_at`** only where a repository runs whole-table time
   scans; it is cheap, additive, and never replaces a B-tree.

What the hub should do regardless of civex: keep one schema per repo (the
tenant already is the natural partition unit; the hub reaches billions of rows
*across* repositories without any of the above), and watch
`pg_class` / `pg_attribute` growth and `max_locks_per_transaction` before
enabling per-repo partitioning on a cluster with thousands of schemas.

## Open questions

- Is uuidv7's embedded timestamp acceptable for record ids (privacy)? The
  alternative that keeps most of the win is a time-ordered prefix with a
  random suffix, or ordering by a server-assigned monotonic key.
- Retention: does anyone want to drop audit history? Sync depends on
  `hub_seq` continuity, so detach-and-drop is only safe behind a sync
  checkpoint; otherwise partitioning audit is maintenance-only.
- Mixed-version workers during the partition swap in steps 5 and 6 need the
  hub's "refuse to serve a stale schema" status API (CIVEXHUB notes) to be
  safe.

## Reproducing

```bash
createdb civex_scale
PG_URL=postgresql://user@localhost:5432/civex_scale \
  .venv/bin/python benchmarks/bench_scale.py --rows 20000000 --spike-rows 3000000 --out scale.json
```

About an hour and ~36 GB of tables and indexes plus WAL (allow 70 GB) at 20M
rows. `benchmarks/results-20m.json` combines one such run (seed, measure,
ids, catalog) with the `spike` block of a separate 3M-row run, plus the
5M-row spike block from the 20M run under `spike_5m_without_hash_by_id`.
See `benchmarks/README.md`.
