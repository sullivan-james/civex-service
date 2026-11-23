"""The authority applying a pushed batch of records, and the client making one,
on PostgreSQL with a large repository behind it.

Pushes `--batches` seed batches of 250 realistic records (`_seed`, the first
upload's path; `--mode pending` pushes ordinary pending creates instead) into
an authority prefilled to `--prefill` records (and as many audit_log and
sync_ops rows), and reports per record: the authority's time (`push`) and the
client's (everything else: reading the snapshots, `note_seed_acked`, the
commit). Both sides are PostgreSQL databases made for the run and dropped
afterwards.

    PG_URL=postgresql+psycopg2://civexhub@localhost:5545/postgres \
        python benchmarks/bench_bulk_push.py --prefill 200000 --batches 8

`--profile` prints where the authority's time goes (cProfile, by cumulative).
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

from bench_push import Counter
from civex.services import sync_service
from civex.testing import Projects
from civex.testing.peers import build_study, connect, device


def _database(admin, base: str, label: str):
    name = f"civex_bench_{label}_{uuid.uuid4().hex[:8]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    return name, base.rsplit("/", 1)[0] + f"/{name}"


def _prefill(engine, rows: int) -> None:
    """`rows` more records, with an audit_log row and a sync_ops row each,
    cloned from the one record the authority holds, in the repository's own
    numbering."""
    with engine.begin() as conn:
        base = conn.execute(text("SELECT head_seq FROM sync_meta")).scalar_one()
        conn.execute(
            text(
                """
            CREATE TEMP TABLE fill ON COMMIT DROP AS
            SELECT gen_random_uuid() AS rid, gen_random_uuid() AS aid,
                   gen_random_uuid() AS oid, :base + g AS seq
            FROM generate_series(1, :n) g"""
            ),
            {"base": base, "n": rows},
        )
        conn.execute(
            text(
                """
            INSERT INTO records (id, dataset_id, schema_id, parent_record_id, data,
                                 created_at, updated_at, deleted_at)
            SELECT f.rid, r.dataset_id, r.schema_id, NULL, r.data,
                   r.created_at, r.updated_at, NULL
            FROM fill f, (SELECT * FROM records LIMIT 1) r"""
            )
        )
        conn.execute(
            text(
                """
            INSERT INTO audit_log (id, action, entity_type, entity_id, old_data,
                new_data, timestamp, actor, device, device_id, hlc, hub_seq,
                sync_state, apply_state, delta, format)
            SELECT f.aid, a.action, 'record', f.rid, NULL, a.new_data, a.timestamp,
                   a.actor, a.device, a.device_id, a.hlc, f.seq, 'synced',
                   a.apply_state, a.delta, a.format
            FROM fill f, (SELECT * FROM audit_log WHERE entity_type = 'record'
                          AND hub_seq IS NOT NULL LIMIT 1) a"""
            )
        )
        conn.execute(
            text(
                """
            INSERT INTO sync_ops (op_id, device_id, device_name, entity_type,
                entity_id, status, message, conflicts, hub_seq, received_at)
            SELECT f.oid, o.device_id, o.device_name, 'record', f.rid, 'applied',
                   NULL, '[]', f.seq, o.received_at
            FROM fill f, (SELECT * FROM sync_ops WHERE entity_type = 'record'
                          LIMIT 1) o"""
            )
        )
        conn.execute(text("UPDATE sync_meta SET head_seq = :s"), {"s": base + rows})
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("VACUUM ANALYZE"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefill", type=int, default=200_000)
    ap.add_argument("--batches", type=int, default=8)
    ap.add_argument("--mode", choices=("seed", "pending"), default="seed")
    ap.add_argument("--profile", action="store_true")
    args = ap.parse_args()
    base = os.environ["PG_URL"]
    n = args.batches * sync_service.PUSH_BATCH
    scratch = Path(tempfile.mkdtemp(prefix="civex-bench-", dir=Path.home() / ".cache"))
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
        laptop.schema_svc.add_field("encounter", "seen", "date")
        laptop.schema_svc.add_field("encounter", "ok", "boolean")
        laptop.schema_svc.add_field("encounter", "scan", "file")
        laptop.commit()
        connect(laptop)  # seeds the one record and the structure
        t = time.perf_counter()
        _prefill(authority._session.get_bind(), args.prefill)
        print(f"prefilled {args.prefill} rows in {time.perf_counter() - t:.0f}s")

        # Each record cites a file (a pool of them, cited in turn).
        pool = [
            laptop.file_svc.store_bytes(os.urandom(2048), f"f{i}.bin").to_dict()
            for i in range(50)
        ]
        for i in range(n):
            laptop.record_svc.add(
                "study",
                "encounter",
                {
                    "site": f"site-{i % 97}",
                    "depth": 1.5 + i % 40,
                    "notes": f"Observation {i}: " + "lorem ipsum dolor sit " * 5,
                    "count": i,
                    "seen": "2024-05-17",
                    "ok": bool(i % 2),
                    "scan": pool[i % len(pool)],
                },
            )
        laptop.commit()

        counts = Counter(authority._session.get_bind())
        mine = Counter(laptop._session.get_bind())
        transport = laptop._holder["inner"]
        real = transport.push
        spent = {"server": 0.0, "calls": 0}
        results: list = []
        prof = cProfile.Profile() if args.profile else None

        def timed(entries):
            t0 = time.perf_counter()
            if prof:
                prof.enable()
            out = real(entries)
            if prof:
                prof.disable()
            spent["server"] += time.perf_counter() - t0
            spent["calls"] += 1
            results.extend((r.status, r.hub_seq) for r in out.results)
            return out

        transport.push = timed
        t0 = time.perf_counter()
        if args.mode == "seed":
            svc = object.__getattribute__(laptop.sync_svc, "_svc")
            svc._seed(transport, salt="bench", advance=False)
        else:
            laptop.sync_svc.sync()
        total = time.perf_counter() - t0
        client = total - spent["server"]
        records = sum(1 for s, _ in results if s == "applied")
        print(
            f"{args.mode}: {spent['calls']} pushes, {len(results)} entries, "
            f"{records} applied\n"
            f"  authority {spent['server'] / n * 1000:6.2f} ms/record\n"
            f"  client    {client / n * 1000:6.2f} ms/record  "
            f"({client / spent['calls'] * 1000:.0f} ms/batch)\n"
            f"  total     {total / n * 1000:6.2f} ms/record"
        )
        print("  authority statements per record:", end="")
        for kind, c in counts.by.most_common(14):
            print(f"  {kind} {c / n:.2f}", end="")
        print(f"\n  client statements per record: {mine.total / n:.2f} ", end="")
        print(
            "(" + ", ".join(f"{k} {c / n:.2f}" for k, c in mine.by.most_common(6)) + ")"
        )
        if prof:
            pstats.Stats(prof).sort_stats("cumulative").print_stats(35)
    finally:
        projects.close()
        for name in (a_name, d_name):
            with admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


if __name__ == "__main__":
    main()
