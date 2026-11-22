# Benchmarks and stress tests

| Script | What it is for |
|---|---|
| `generate.py` | Fill a project with a large, realistic dataset (records, and with `--files` stored files on several volumes) through civex's own services |
| `stress.py` | Time, load, break and check a project made by `generate.py`: metadata and files, and (`queries`) list reads with and without field indexes |
| `bench_indexes.py` | PostgreSQL index comparison on its own throwaway tables |
| `bench_scale.py` | `records` / `audit_log` at tens of millions of rows on PostgreSQL, plus a partitioning / BRIN / JSONB side-table spike; numbers in [the design note](../docs/contributing/billion-row-collections.md) |
| `bench_paging.py` | PostgreSQL: OFFSET vs keyset paging and exact vs estimated counts, seeded with N records (`PG_URL`, `--records`) |

They import civex, so run them with this checkout's virtualenv, from inside the
project they work on. Make a project for them; never point them at real data
(`stress.py chaos` moves files around).

## Make a project and stress it

```bash
CIVEX=~/civex/civex-service                  # this checkout
mkdir -p ~/stress/small && cd ~/stress/small
$CIVEX/.venv/bin/civex init --sqlite
$CIVEX/.venv/bin/python $CIVEX/benchmarks/generate.py --preset small --files
$CIVEX/.venv/bin/python $CIVEX/benchmarks/stress.py all
```

Put the project on a disk with room: the volumes go in `<project>-volumes/`
beside it, and random file content doesn't compress, so `--file-budget-gb` is
real disk. Generation runs at roughly 200 records/s on SQLite.

## Time lists at a million records

```bash
mkdir -p ~/stress/flat-1m && cd ~/stress/flat-1m
$CIVEX/.venv/bin/civex init --sqlite
$CIVEX/.venv/bin/python $CIVEX/benchmarks/generate.py --flat 1000000 --bulk
$CIVEX/.venv/bin/python $CIVEX/benchmarks/stress.py queries --reps 5
```

## generate.py

A bioacoustics study: shared `reference-data` (global: sites, species,
observers) and one `survey-<year>` collection per season holding
encounter → recording → selection. Encounters reference a site and an observer
and list species. Deterministic for a given `--seed`.

| Preset | Records | File budget |
|---|---|---|
| `tiny` | ~1k | 0.1 GB |
| `small` | ~17k | 1 GB |
| `medium` | ~170k | 8 GB |
| `large` | ~340k | 20 GB |

Explicit options win over a preset (`--preset medium --file-budget-gb 2`).

`--flat N` makes something else: one collection `flat` holding N records of
one kind `sample` with twenty scalar fields (text, numbers, dates, yes/no, with
gaps), for timing lists at a million records. Through `RecordService.add` it
runs at ~200 records/s, so a million takes over an hour; `--bulk` writes the
rows straight into the records table in their stored form (field-id keyed,
the timestamps `add` would give) at ~12,000/s, a million in about a minute and
a half. That bypasses validation, history (no audit rows), triggers and the
reference/file catalogs, none of which a list reads, so it is for timing reads
only. Running it again tops the collection up to N.
Without `--preset`: `--collections --encounters --recordings --selections
--sites --species --observers --first-year --batch --seed`.

`--files` adds:

- a `.wav` on each recording (`--audio-kb MIN MAX`), with `--dup-share` of them
  repeating earlier content, and a table on `--table-share` of selections;
- download names built from the records above and the site reference
  (`site_0002_2019-00000_20190505_0106.wav`);
- `--volumes` extra volumes in `--volumes-dir` (default `<project>-volumes/`),
  outside the project so removing one looks like an unplugged drive. The last
  is capped (`--small-volume-gb`, default a quarter of the budget) so writes
  spill, and each survey gets a home volume;
- a `--file-budget-gb` cap on new bytes; past it, records are made without files.

## stress.py

`all` runs every part in order (except `queries`); each also runs alone.

| Part | What it does |
|---|---|
| `bench` | Starts `civex serve` and times, over HTTP: list pages (first, deep, filtered, sorted, on an ancestor's field), search, a record, the reference picker, Activity, a collection's file plan and listing, a zip, export as links and as copies (removed again), the storage report, clean-up and retention dry runs. `--reps` |
| `load` | `--readers` threads reading (pages, records, downloads, file plans) while one writer uploads, creates and edits, for `--seconds` (`--upload-kb`). Latency, throughput and every error, with "database is locked" counted |
| `chaos` | Renames a volume's folder and checks a record still opens, says its file can't be reached, a download answers 503 naming the drive, and a plan lists what is out of reach; then kills a file move once it is copying (`--kill-after`), resumes it as a person would and checks the volume emptied. **Changes the project** |
| `check` | Every file records use is in the inventory and on disk, nothing on disk is unaccounted for, `civex doctor` is clean; `--hash` re-hashes every file |
| `queries` | On a `--flat` project (or the study: its selections in the first survey), in process through the services (the query, not HTTP): the explorer's reads (first page, a filtered page and its count, range counts, sorts by a number and a date both ways, a sorted page 100, filter + sort, text search page and count), median of `--reps`, first with no field indexes and then with four fields indexed (`IndexService`; `QUERY_TARGETS`), with the planner's statistics fresh both times; also how long building the indexes took. The project's own index choices are put back. `--results`, `--markdown`, `--baseline` (exit 1 when something is more than `--max-slowdown` times slower). Not part of `all` |

A report is printed and saved as `stress-<time>.json` in the project; the
server's output goes to `stress-server.log`. The exit status is 1 when a check
fails, so `stress.py check --hash` can gate a run.

## bench_scale.py

Needs an empty scratch PostgreSQL database with a lot of disk (about 1.8 KB
of table and index per record at 20M rows, ~36 GB plus WAL, so allow 70 GB;
RAM can be small). It builds its own `bm_*`/`sp_*` tables and never touches
civex data. One command, from a clean database:

```bash
createdb civex_scale
PG_URL=postgresql://user@localhost:5432/civex_scale \
  .venv/bin/python benchmarks/bench_scale.py --rows 20000000 --spike-rows 3000000 --out scale.json
```

The default run takes about an hour at 20M rows (seeding runs at ~17k rows/s,
so 100M rows is ~2 h of seeding alone, plus index builds). Use `--rows 1000000
--spike-rows 100000` for a ten-minute smoke test. `--phase` reruns one phase
(`seed`, `measure`, `ids`, `spike`, `catalog`); the JSON accumulates in `--out`.

## The weekly benchmark (CI)

`.github/workflows/benchmarks.yml` runs `stress.py queries` every Monday, on
`v*` tags and on demand (**Actions → Benchmarks → Run workflow**; from the
default branch only), on GitHub's own Linux runners:

1. Generates the `medium` study without files (~170k records, through the
   services) in a project under the runner's temp folder, never the checkout,
   and reports how long that took and records/s. The project is cached
   (`actions/cache`), keyed on a hash of `generate.py`, the migrations and the
   record write path (`record_service.py`, `record_repo.py`, `models.py`), so
   most weeks skip this.
2. Times the queries on the study's selections in its first survey
   (`QUERY_TARGETS["study"]`), without and with field indexes.
3. Puts the table in the job summary and uploads `queries.json`,
   `queries.md`, `summary.md` (and `generate.log` when it generated) as the
   `query-benchmark` artifact, kept 90 days.
4. Compares with the last successful run's `queries.json` (downloaded with
   `gh run download` and the job's own token) and fails when an operation is
   more than twice as slow (`--max-slowdown 2`) and more than `NOISE_MS`
   (10 ms) slower, so a 2 ms query taking 5 ms on a busy runner doesn't. No
   earlier run, or no artifact in it, is nothing to compare: it passes. A
   failed run's results are not the next baseline (only successful runs are).

The same comparison locally:

```bash
$CIVEX/.venv/bin/python $CIVEX/benchmarks/stress.py queries \
    --results now.json --markdown now.md --baseline before.json
```
