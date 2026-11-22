"""
Benchmark: OFFSET vs keyset paging, and exact vs estimated counts, on PostgreSQL.

Seeds N live records into a civex-migrated database (one INSERT ... SELECT over
generate_series, so 10M rows is a matter of minutes), then times, through
civex's own repository:

  - a page of 50 at depth 0 / 50% / 90% by OFFSET (`list_filtered`) and by
    keyset (`list_keyset`), unsorted and sorted by a JSON field (numeric,
    descending, with ties and nulls) and by created_at;
  - an exact count (`count`) against `estimate_count`, for the whole table and
    for one collection.

Usage:
    PG_URL=postgresql+psycopg2://user@localhost/scratch \
        python benchmarks/bench_paging.py [--records 10000000] [--reps 3] [--keep]

The target database must exist and be disposable: the script migrates it, adds
its own collection and schema, and (unless --keep) deletes its rows after.
Run it with this checkout's virtualenv.
"""

from __future__ import annotations

import argparse
import os
import statistics
import time
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from civex.db.migrate import ensure_schema_current
from civex.db.models import Dataset, Schema
from civex.domain.filters import SortKey
from civex.domain.query import ResolvedQuery
from civex.repositories.local import record_repo
from civex.repositories.local.record_repo import LocalRecordRepository

PG_URL = os.environ.get(
    "PG_URL", "postgresql+psycopg2://civex:civex@localhost/civex_bench"
)
PAGE = 50
BATCH = 500_000


def seed(session: Session, ds: uuid.UUID, sch: uuid.UUID, n: int) -> None:
    """n records, created_at one millisecond apart in groups of 3 (ties), a
    numeric `k` with many ties (absent on every 10th) and a text `s`."""
    done = 0
    while done < n:
        take = min(BATCH, n - done)
        session.execute(
            text(
                """
                INSERT INTO records (id, dataset_id, schema_id, data, created_at, updated_at)
                SELECT gen_random_uuid(), :ds, :sch,
                       CASE WHEN g % 10 = 0
                            THEN jsonb_build_object('s', 'v' || (g % 1000))
                            ELSE jsonb_build_object('k', g % 100000, 's', 'v' || (g % 1000))
                       END,
                       now() - make_interval(secs => (:total - g / 3) / 1000.0),
                       now()
                FROM generate_series(:start, :stop) AS g
                """
            ),
            {
                "ds": ds,
                "sch": sch,
                "total": n,
                "start": done,
                "stop": done + take - 1,
            },
        )
        session.commit()
        done += take
        print(f"  seeded {done:,}/{n:,}", flush=True)
    session.execute(text("ANALYZE records"))
    session.commit()


def timed(fn, reps: int) -> float:
    """Median wall-clock milliseconds of fn over `reps` runs."""
    runs = []
    for _ in range(reps):
        t = time.perf_counter()
        fn()
        runs.append((time.perf_counter() - t) * 1000)
    return statistics.median(runs)


def key_at(session: Session, query: ResolvedQuery, depth: int) -> list:
    """The keyset key of the record just before `depth` (found the slow way,
    outside the timings)."""
    terms = record_repo._sort_terms(query.sort) + [
        (record_repo.Record.created_at, False, False),
        (record_repo.Record.id, False, False),
    ]
    q = record_repo._base_query(session, query, True)
    q = q.add_columns(*[t[0].label(f"_k{i}") for i, t in enumerate(terms)])
    q = q.order_by(
        *record_repo._order_by(query.sort),
        record_repo.Record.created_at,
        record_repo.Record.id,
    )
    row = q.offset(depth - 1).limit(1).one()
    return list(row[1:])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", type=int, default=1_000_000)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--keep", action="store_true", help="leave the rows in place")
    ap.add_argument("--skip-seed", action="store_true", help="reuse rows from --keep")
    args = ap.parse_args()

    engine = create_engine(PG_URL)
    ensure_schema_current(engine)
    with Session(engine) as session:
        if args.skip_seed:
            ds = (
                session.query(Dataset)
                .filter(Dataset.name.like("bench-paging-%"))
                .order_by(Dataset.created_at.desc())
                .first()
            )
            sch = (
                session.query(Schema)
                .filter(Schema.name.like("bench_paging_%"))
                .order_by(Schema.created_at.desc())
                .first()
            )
            assert ds and sch, "nothing to reuse: run once with --keep"
        else:
            ds = Dataset(name=f"bench-paging-{uuid.uuid4().hex[:6]}")
            sch = Schema(name=f"bench_paging_{uuid.uuid4().hex[:6]}")
            session.add_all([ds, sch])
            session.commit()
            print(f"seeding {args.records:,} records")
            t = time.perf_counter()
            seed(session, ds.id, sch.id, args.records)
            print(f"  seeded in {time.perf_counter() - t:.0f}s")
        size = session.execute(
            text("SELECT pg_size_pretty(pg_total_relation_size('records'))")
        ).scalar()
        total = session.execute(
            text("SELECT count(*) FROM records WHERE dataset_id = :d"), {"d": ds.id}
        ).scalar()
        print(
            f"benchmark collection: {total:,} rows; records table {size} with indexes\n"
        )

        repo = LocalRecordRepository(session, is_postgres=True)
        orders = {
            "unsorted (created_at, id)": None,
            "k desc (JSON number, ties, nulls last)": [
                SortKey(field_id="k", numeric=True, descending=True)
            ],
            "created_at desc": [
                SortKey(field_id="", meta="@created_at", descending=True)
            ],
        }
        print(f"{'ordering':42} {'depth':>8} {'OFFSET ms':>11} {'keyset ms':>11}")
        for label, sort in orders.items():
            q = ResolvedQuery(dataset_id=ds.id, schema_id=sch.id, sort=sort)
            for frac in (0.0, 0.5, 0.9):
                depth = int(total * frac)
                if depth:
                    key = key_at(session, q, depth)
                    # Repeat the key lookup's own cost out: it is not timed.
                else:
                    key = None
                off = timed(lambda: repo.list_filtered(q, depth, PAGE), args.reps)
                ks = timed(lambda: repo.list_keyset(q, PAGE, key), args.reps)
                print(f"{label:42} {depth:>8,} {off:>11.1f} {ks:>11.1f}")
            print()

        print(
            f"{'count':42} {'exact ms':>11} {'estimate ms':>12} {'exact':>12} {'estimate':>12}"
        )
        for label, q in (
            ("whole table", ResolvedQuery()),
            ("one collection", ResolvedQuery(dataset_id=ds.id)),
            ("collection + schema", ResolvedQuery(dataset_id=ds.id, schema_id=sch.id)),
        ):
            exact_ms = timed(lambda: repo.count(q), args.reps)
            est_ms = timed(lambda: repo.estimate_count(q), args.reps)
            print(
                f"{label:42} {exact_ms:>11.1f} {est_ms:>12.1f} "
                f"{repo.count(q):>12,} {repo.estimate_count(q)[0]:>12,}"
            )

        if not args.keep:
            session.execute(
                text("DELETE FROM records WHERE dataset_id = :d"), {"d": ds.id}
            )
            session.delete(ds)
            session.delete(sch)
            session.commit()
    engine.dispose()


if __name__ == "__main__":
    main()
