# Benchmarks and stress tests

| Script | What it is for |
|---|---|
| `generate.py` | Fill a project with a large, realistic dataset (records, and with `--files` stored files on several volumes) through civex's own services |
| `stress.py` | Time, load, break and check a project made by `generate.py`: metadata and files |
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

`all` runs every part in order; each also runs alone.

| Part | What it does |
|---|---|
| `bench` | Starts `civex serve` and times, over HTTP: list pages (first, deep, filtered, sorted, on an ancestor's field), search, a record, the reference picker, Activity, a collection's file plan and listing, a zip, export as links and as copies (removed again), the storage report, clean-up and retention dry runs. `--reps` |
| `load` | `--readers` threads reading (pages, records, downloads, file plans) while one writer uploads, creates and edits, for `--seconds` (`--upload-kb`). Latency, throughput and every error, with "database is locked" counted |
| `chaos` | Renames a volume's folder and checks a record still opens, says its file can't be reached, a download answers 503 naming the drive, and a plan lists what is out of reach; then kills a file move once it is copying (`--kill-after`), resumes it as a person would and checks the volume emptied. **Changes the project** |
| `check` | Every file records use is in the inventory and on disk, nothing on disk is unaccounted for, `civex doctor` is clean; `--hash` re-hashes every file |

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
