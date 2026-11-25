"""A device catching up on a feed of record changes: creates, edits, deletes and
restores, `--n` of each, into a SQLite and a PostgreSQL client. Reports the
device's apply time per change, one change at a time (`SyncService._bulk_pull`
off) and applying runs of like changes as a set.

    PG_URL=postgresql+psycopg2://civexhub@localhost:5545/postgres \
        python benchmarks/bench_bulk_pull.py --n 20000

The feed is made of real changes (one record created, edited, deleted and
restored through an authority; their entries are copied with new ids), served
to the device from memory, so the figure is the device's own cost: reading the
feed is not in it. `--db sqlite|postgres` and `--modes old,new` pick what runs
(PG_URL is needed for PostgreSQL).
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
import uuid
from dataclasses import replace
from pathlib import Path

from sqlalchemy import create_engine, text

from civex.domain.sync import FeedPage
from civex.testing import Projects
from civex.testing.peers import build_study, connect, device


class Served:
    """A feed held in memory."""

    def __init__(self, entries) -> None:
        self.entries = entries

    def feed(self, after: int, limit: int) -> FeedPage:
        rest = [e for e in self.entries if (e.hub_seq or 0) > after]
        page = rest[:limit]
        return FeedPage(
            entries=page,
            head_seq=self.entries[-1].hub_seq or 0,
            more=len(rest) > limit,
        )


def _templates(projects, authority) -> dict:
    """One real entry of each kind, made through the authority."""
    laptop = device(projects, authority, "laptop")
    record = build_study(laptop)
    connect(laptop)
    rid = str(record.id)
    laptop.record_svc.update(rid, {"site": "edited", "depth": 3.5})
    laptop.commit()
    laptop.sync_svc.sync()
    laptop.record_svc.delete(rid)
    laptop.commit()
    laptop.sync_svc.sync()
    laptop.record_svc.restore(rid)
    laptop.commit()
    laptop.sync_svc.sync()
    watcher = device(projects, authority, "watcher")
    connect(watcher)
    entries = watcher.sync_svc._transport().feed(0, 1000).entries
    made = {}
    for e in entries:
        if e.entity_type == "record":
            made.setdefault(e.action, e)
    return {"entries": made, "id": rid, "watcher": watcher}


def _like(entry, template_id: str, record_id: uuid.UUID, seq: int):
    """A copy of a real entry about another record."""
    raw = json.dumps(entry.to_dict()).replace(template_id, str(record_id))
    copy = type(entry).from_dict(json.loads(raw))
    return replace(
        copy, id=uuid.uuid4(), entity_id=record_id, hub_seq=seq, op=None, batch=None
    )


def _database(admin, base: str):
    name = f"civex_bench_pull_{uuid.uuid4().hex[:8]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    return name, base.rsplit("/", 1)[0] + f"/{name}"


def run(kind: str, mode: str, n: int, scratch: Path, base: str | None):
    os.environ["CIVEX_USER_STATE"] = str(scratch / f"{kind}-{mode}-state.toml")
    admin = name = url = None
    if kind == "postgres":
        admin = create_engine(base, isolation_level="AUTOCOMMIT")
        name, url = _database(admin, base)
    projects = Projects(scratch / f"{kind}-{mode}")
    try:
        authority = projects("authority")
        tpl = _templates(projects, authority)
        phone = device(
            lambda who: projects(who, db_url=url) if url else projects(who),
            authority,
            "phone",
        )
        connect(phone)
        svc = phone.sync_svc
        svc = object.__getattribute__(svc, "_svc") if hasattr(svc, "_svc") else svc
        svc._bulk_pull = mode == "new"
        ids = [uuid.uuid4() for _ in range(n)]
        seq = phone.sync_repo.meta().cursor
        out = {}
        for action in ("create", "update", "delete", "restore"):
            entries = []
            for rid in ids:
                seq += 1
                entries.append(_like(tpl["entries"][action], tpl["id"], rid, seq))
            served = Served(entries)
            started = time.perf_counter()
            svc._pull(served)
            phone.commit()
            out[action] = (time.perf_counter() - started) * 1000 / n
        got = phone.sync_repo._s.execute(
            text("SELECT count(*) FROM records WHERE deleted_at IS NULL")
        ).scalar()
        assert got == n + 1, got  # every one restored (and the first still here)
        return out
    finally:
        projects.close()
        if admin is not None:
            with admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
            admin.dispose()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20_000)
    ap.add_argument("--db", default="sqlite,postgres")
    ap.add_argument("--modes", default="old,new")
    args = ap.parse_args()
    base = os.environ.get("PG_URL")
    scratch = Path(tempfile.mkdtemp(prefix="civex-bench-pull-"))
    print(f"{args.n} changes of each kind; ms per change")
    print(
        f"{'client':<10}{'mode':<6}{'create':>9}{'update':>9}{'delete':>9}{'restore':>9}"
    )
    for kind in args.db.split(","):
        if kind == "postgres" and not base:
            print("postgres: PG_URL not set, skipped")
            continue
        for mode in args.modes.split(","):
            r = run(kind, mode, args.n, scratch, base)
            print(
                f"{kind:<10}{mode:<6}"
                + "".join(
                    f"{r[a]:>9.3f}" for a in ("create", "update", "delete", "restore")
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
