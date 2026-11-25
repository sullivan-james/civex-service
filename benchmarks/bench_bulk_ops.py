"""The authority applying a pushed bulk delete and a bulk restore of records,
against the same bulk action done locally through civex's own service, on
PostgreSQL (the laptop and the authority are databases made for the run and
dropped afterwards).

Makes N records on a laptop and syncs them to the authority, then:

1. deletes them all on the laptop (`RecordService.delete_many`), and times it;
2. pushes those deletes to the authority (batches of `PUSH_BATCH`, as the
   client does) and times the authority's `push` alone (transport excluded);
3. the same for `restore_set`.

Reports ms per record for each, and pushed / local.

    PG_URL=postgresql+psycopg2://civexhub@localhost:5545/postgres \
        python benchmarks/bench_bulk_ops.py --records 70000
"""

from __future__ import annotations

import argparse
import cProfile
import os
import pstats
import tempfile
import time
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text

from civex.testing import Projects
from civex.testing.peers import build_study, connect, device


def _database(admin, base: str, label: str):
    name = f"civex_bench_{label}_{uuid.uuid4().hex[:8]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    return name, base.rsplit("/", 1)[0] + f"/{name}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", type=int, default=70_000)
    ap.add_argument("--profile", action="store_true")
    ap.add_argument("--children", action="store_true", help="a child under every 10th")
    args = ap.parse_args()
    base = os.environ["PG_URL"]
    n = args.records
    scratch = Path(tempfile.mkdtemp(prefix="civex-bench-"))
    os.environ["CIVEX_USER_STATE"] = str(scratch / "user-state.toml")
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    a_name, a_url = _database(admin, base, "auth")
    d_name, d_url = _database(admin, base, "dev")
    projects = Projects(scratch)
    try:
        authority = projects("authority", db_url=a_url)
        laptop = device(lambda name: projects(name, db_url=d_url), authority, "laptop")
        build_study(laptop)
        laptop.schema_svc.add_field("encounter", "notes", "longtext")
        laptop.schema_svc.add_field("encounter", "count", "integer")
        laptop.commit()
        connect(laptop)
        ids = []
        for i in range(n):
            made = laptop.record_svc.add(
                "study",
                "encounter",
                {"site": f"site-{i % 97}", "notes": f"Observation {i}", "count": i},
                with_labels=False,
            )
            ids.append(str(made.id))
        laptop.commit()
        t = time.perf_counter()
        laptop.sync_svc.sync()
        print(f"made {n} and synced them in {time.perf_counter() - t:.0f}s")

        transport = laptop._holder["inner"]
        real = transport.push
        spent = {"server": 0.0}
        prof = cProfile.Profile() if args.profile else None
        answers: list = []

        def timed(entries):
            t0 = time.perf_counter()
            if prof:
                prof.enable()
            out = real(entries)
            authority.commit()
            if prof:
                prof.disable()
            spent["server"] += time.perf_counter() - t0
            answers.extend(r.status for r in out.results)
            return out

        transport.push = timed

        def phase(name: str, act) -> None:
            t0 = time.perf_counter()
            act()
            laptop.commit()
            local = time.perf_counter() - t0
            spent["server"] = 0.0
            answers.clear()
            laptop.sync_svc.sync()
            pushed = spent["server"]
            print(
                f"{name}: local {local / n * 1000:6.3f} ms/record, "
                f"pushed {pushed / n * 1000:6.3f} ms/record, "
                f"ratio {pushed / local:5.2f}x  "
                f"({len(answers)} answers: "
                f"{ {s: answers.count(s) for s in set(answers)} })"
            )

        phase("delete ", lambda: laptop.record_svc.delete_many(ids))
        phase("restore", lambda: laptop.record_svc.restore_set(ids))
        if prof:
            pstats.Stats(prof).sort_stats("tottime").print_stats(30)
    finally:
        projects.close()
        for name in (a_name, d_name):
            with admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


if __name__ == "__main__":
    main()
