"""A first upload to a PostgreSQL authority: seed N records, send M small files
and a few large ones, then time resuming a seed that stopped half way.

    PG_URL=postgresql+psycopg2://civexhub@localhost:5545/postgres \
        python benchmarks/bench_first_upload.py --records 5000 --small 400 \
        --large 2 --latency 0.005

`--latency` adds that many seconds to every call to the authority (a push, a
file check, a file upload), standing in for the network. The database it makes
is dropped afterwards. The numbers are for comparing two checkouts of civex,
not absolute.
"""

from __future__ import annotations

import argparse
import os
import tempfile
import time
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text

from civex.config import load_config
from civex.context import build_local_context
from civex.domain.sync import SyncError
from civex.project import scaffold_project
from civex.services import sync_service
from civex.testing import Projects
from civex.testing.peers import build_study, connect, device


def _authority(scratch: Path, base_url: str):
    name = f"civex_bench_{uuid.uuid4().hex[:10]}"
    admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    root = scratch / "authority"
    scaffold_project(root, db_url=base_url.rsplit("/", 1)[0] + f"/{name}")
    previous = os.getcwd()
    os.chdir(root)
    try:
        ctx = build_local_context(load_config())
    finally:
        os.chdir(previous)

    def drop() -> None:
        ctx.close()
        ctx._session.get_bind().dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()

    return ctx, drop


def _watch(latency: float):
    """Count calls, and the entries and files they carried, and slow each."""
    seen = {"push": 0, "entries": 0, "check": 0, "upload": 0}
    real = sync_service.SyncService._transport

    def transport(self):
        t = real(self)
        if getattr(t, "_watched", False):
            return t
        t._watched = True
        for method, key in (("push", "push"), ("missing_files", "check")):
            inner = getattr(t, method)

            def wrapped(*a, _inner=inner, _key=key):
                seen[_key] += 1
                if _key == "push":
                    seen["entries"] += len(a[0])
                time.sleep(latency)
                return _inner(*a)

            setattr(t, method, wrapped)
        up = t.upload_file

        def upload(*a):
            seen["upload"] += 1
            time.sleep(latency)
            return up(*a)

        t.upload_file = upload
        return t

    sync_service.SyncService._transport = transport  # type: ignore[method-assign]
    return seen, lambda: setattr(sync_service.SyncService, "_transport", real)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", type=int, default=5000)
    ap.add_argument("--small", type=int, default=400)
    ap.add_argument("--large", type=int, default=2)
    ap.add_argument("--small-kb", type=int, default=20)
    ap.add_argument("--large-mb", type=int, default=12)
    ap.add_argument("--latency", type=float, default=0.005)
    ap.add_argument("--batch", type=int, help="changes per push (PUSH_BATCH)")
    args = ap.parse_args()
    if args.batch:
        sync_service.PUSH_BATCH = args.batch
    base = os.environ["PG_URL"]
    scratch = Path(tempfile.mkdtemp(prefix="civex-bench-", dir=Path.home() / ".cache"))
    os.environ["CIVEX_USER_STATE"] = str(scratch / "user-state.toml")
    project = Projects(scratch)
    authority, drop = _authority(scratch, base)
    try:
        laptop = device(project, authority, "laptop")
        build_study(laptop)
        laptop.schema_svc.add_field("encounter", "scan", "file")
        laptop.commit()
        for i in range(args.records):
            laptop.record_svc.add("study", "encounter", {"site": f"s{i}", "depth": 1.0})
        sizes = [args.small_kb * 1024] * args.small + [args.large_mb << 20] * args.large
        for i, size in enumerate(sizes):
            ref = laptop.file_svc.store_bytes(
                os.urandom(size), f"f{i}.bin"
            )
            laptop.record_svc.add(
                "study", "encounter", {"site": f"f{i}", "scan": ref.to_dict()}
            )
        laptop.commit()
        total = laptop.sync_repo.entity_count()
        print(f"records+files: {args.records}+{len(sizes)}  entities: {total}")

        seen, restore = _watch(args.latency)
        # 1. a seed that stops half way, then resumes
        original = sync_service.SyncService._seed
        half = max(1, args.records // 2)

        def stop_half(self, transport, *rest, **kw):
            real = transport.push
            sent = 0

            def push(entries):
                nonlocal sent
                if sent >= half:
                    raise SyncError("connection lost", retryable=True)
                sent += len(entries)
                return real(entries)

            transport.push = push
            try:
                return original(self, transport, *rest, **kw)
            finally:
                transport.push = real

        sync_service.SyncService._seed = stop_half  # type: ignore[method-assign]
        t0 = time.monotonic()
        try:
            connect(laptop)
        except SyncError:
            pass
        first = time.monotonic() - t0
        sync_service.SyncService._seed = original  # type: ignore[method-assign]
        before = dict(seen)
        t0 = time.monotonic()
        laptop.sync_svc.sync()
        resume = time.monotonic() - t0
        pushed = seen["entries"] - before["entries"]
        print(
            f"seed up to the break: {first:6.1f}s  entries {before['entries']}\n"
            f"seed resumed:         {resume:6.1f}s  entries {pushed}  "
            f"pushes {seen['push'] - before['push']}"
        )
        # 2. the files
        before = dict(seen)
        t0 = time.monotonic()
        report = laptop.sync_svc.send_files()
        files = time.monotonic() - t0
        print(
            f"files:                {files:6.1f}s  sent {report.sent}  "
            f"uploads {seen['upload'] - before['upload']}"
        )
        print(f"TOTAL                 {first + resume + files:6.1f}s")
        restore()
    finally:
        drop()
        project.close()


if __name__ == "__main__":
    main()
