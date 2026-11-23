"""How fast files go to an authority: many small files (the 0.3 MB research
case) or a few huge ones, over HTTP to an authority in its own process, files
on its drive or in a bucket (moto standing in for S3, handing out presigned
URLs: files go direct).

    python benchmarks/bench_bulk_files.py --shape small --gb 10 --store fs
    python benchmarks/bench_bulk_files.py --shape huge --big-count 5 --big-gb 2 \
        --store s3

Only the upload is timed (`send_files`, after the records went). The numbers
are MB/s of file bytes; on loopback the line is not the limit, so they show
what the two ends can do, to compare with 62 MB/s (500 Mbps) to 125 MB/s
(1 Gbps). Everything is made under --work (default ~/.cache/bench-bulk) and
deleted afterwards. The same script runs on any checkout (`PYTHONPATH=src`).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

BLOCK = os.urandom(1024 * 1024)


def _content(i: int, size: int) -> bytes:
    head = i.to_bytes(8, "big")
    reps = size // len(BLOCK) + 1
    return (head + BLOCK * reps)[:size]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(port: int) -> None:
    for _ in range(300):
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("server did not start")


class _Dropper:
    """Stands in the list of processes to stop: drops the database at the end."""

    def __init__(self, admin, name: str) -> None:
        self._admin, self._name = admin, name

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        pass

    def wait(self, timeout: float | None = None) -> None:
        from sqlalchemy import text

        # WITH (FORCE) ends any connection the stopped server left.
        with self._admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{self._name}" WITH (FORCE)'))
        self._admin.dispose()


def _proxy(spec: str) -> None:
    """listen:target:MBps — forward to the target, each connection held to MB/s
    (what arrives from the client; answers are small)."""
    import asyncio

    listen, target, rate = spec.split(":")
    rate_bps = float(rate) * 1e6

    async def pipe(r, w, paced: bool) -> None:
        began = time.monotonic()
        total = 0
        try:
            while data := await r.read(65536):
                w.write(data)
                await w.drain()
                if paced:
                    total += len(data)
                    ahead = total / rate_bps - (time.monotonic() - began)
                    if ahead > 0:
                        await asyncio.sleep(ahead)
        except ConnectionError:
            pass
        finally:
            w.close()

    async def handle(cr, cw) -> None:
        sr, sw = await asyncio.open_connection("127.0.0.1", int(target))
        await asyncio.gather(pipe(cr, sw, True), pipe(sr, cw, False))

    async def main() -> None:
        server = await asyncio.start_server(handle, "127.0.0.1", int(listen))
        async with server:
            await server.serve_forever()

    asyncio.run(main())


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--proxy":
        return _proxy(sys.argv[2])
    ap = argparse.ArgumentParser()
    ap.add_argument("--shape", choices=["small", "huge"], required=True)
    ap.add_argument("--store", choices=["fs", "s3"], default="fs")
    ap.add_argument("--gb", type=float, default=10.0)
    ap.add_argument("--small-mb", type=float, default=0.3)
    ap.add_argument("--big-count", type=int, default=5)
    ap.add_argument("--big-gb", type=float, default=2.0)
    ap.add_argument(
        "--per-conn-mb",
        type=float,
        default=0.0,
        help="cap each connection to the authority at this many MB/s (a proxy "
        "stands in for a link where one TCP stream cannot fill the line)",
    )
    ap.add_argument("--work", default=str(Path.home() / ".cache" / "bench-bulk"))
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    work = Path(args.work)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    os.environ["CIVEX_USER_STATE"] = str(work / "user-state.json")
    os.environ.update(
        AWS_ACCESS_KEY_ID="bench", AWS_SECRET_ACCESS_KEY="bench-secret-key"
    )
    procs: list[subprocess.Popen] = []
    try:
        result = run(args, work, procs)
    finally:
        for p in procs:
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        shutil.rmtree(work, ignore_errors=True)
    result["label"] = args.label
    print(json.dumps(result))


def run(args, work: Path, procs: list) -> dict:
    from civex.config import load_config_at
    from civex.context import build_local_context
    from civex.project import scaffold_project
    from civex.testing import Projects
    from civex.testing.peers import build_study

    root = work / "authority"
    if os.environ.get("PG_URL"):
        # PG_URL=postgresql+psycopg2://civexhub@localhost:5545/postgres: the
        # authority's database is made here and dropped afterwards (SQLite
        # serialises the authority's parallel uploads on its write lock).
        from sqlalchemy import create_engine, text

        base = os.environ["PG_URL"]
        name = f"civex_bench_{os.getpid()}"
        admin = create_engine(base, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        procs.append(_Dropper(admin, name))  # type: ignore[arg-type]
        scaffold_project(root, db_url=base.rsplit("/", 1)[0] + f"/{name}")
    else:
        scaffold_project(root, db_url=f"sqlite:///{(root / 'civex.db').as_posix()}")
    toml = root / "_civex" / "config.toml"
    extra = "\n[sync]\nserve = true\n"
    if args.store == "s3":
        import boto3

        port = _free_port()
        moto = Path(
            os.environ.get("MOTO_SERVER")
            or Path.home() / ".cache" / "bulk-moto-venv" / "bin" / "moto_server"
        )
        procs.append(
            subprocess.Popen(
                [str(moto), "-H", "127.0.0.1", "-p", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        _wait(port)
        endpoint = f"http://127.0.0.1:{port}"
        boto3.client(
            "s3", endpoint_url=endpoint, region_name="us-east-1"
        ).create_bucket(Bucket="bench")
        extra += (
            f'\n[store.s3]\nbucket = "bench"\nprefix = "p"\n'
            f'endpoint = "{endpoint}"\nregion = "us-east-1"\n'
        )
    toml.write_text(toml.read_text() + extra)
    authority = build_local_context(load_config_at(root))
    _, invite = authority.device_keys.invite("laptop")
    authority.commit()
    authority.close()

    port = _free_port()
    code = (
        "import os, uvicorn; os.chdir(%r); from civex.server.app import create_app; "
        "uvicorn.run(create_app(), host='127.0.0.1', port=%d, log_level='error')"
        % (str(root), port)
    )
    if os.environ.get(
        "BENCH_PROFILE_SERVER"
    ):  # stacks of the authority's threads, every 3 s
        code = (
            "import faulthandler; faulthandler.dump_traceback_later(3, repeat=True)\n"
            + code
        )
    procs.append(subprocess.Popen([sys.executable, "-c", code]))
    _wait(port)
    if args.per_conn_mb:
        shaped = _free_port()
        procs.append(
            subprocess.Popen(
                [
                    sys.executable,
                    __file__,
                    "--proxy",
                    f"{shaped}:{port}:{args.per_conn_mb}",
                ]
            )
        )
        _wait(shaped)
        port = shaped
    url = f"http://127.0.0.1:{port}"

    projects = Projects(work / "devices")
    laptop = projects("laptop")
    build_study(laptop)
    laptop.schema_svc.add_field("encounter", "scan", "file")
    sizes: list[int]
    if args.shape == "small":
        size = int(args.small_mb * 1024 * 1024)
        sizes = [size] * int(args.gb * 1024**3 // size)
    else:
        sizes = [int(args.big_gb * 1024**3)] * args.big_count
    t0 = time.monotonic()
    scratch = work / "big.bin"
    for i, size in enumerate(sizes):
        if size > 64 * 1024 * 1024:
            with scratch.open("wb") as f:
                f.write(i.to_bytes(8, "big"))
                left = size - 8
                while left:
                    n = min(left, len(BLOCK))
                    f.write(BLOCK[:n])
                    left -= n
            ref = laptop.file_svc.store(scratch, None, f"big{i}.bin")
            scratch.unlink()
        else:
            ref = laptop.file_svc.store_bytes(_content(i, size), f"f{i}.bin")
        laptop.record_svc.add(
            "study", "encounter", {"site": f"s{i}", "scan": ref.to_dict()}
        )
        if i % 500 == 499:
            laptop.commit()
    laptop.commit()
    prepared = time.monotonic() - t0
    laptop.sync_svc.connect(url, invite)
    laptop.commit()
    laptop.sync_svc.sync()
    laptop.commit()
    total = sum(sizes)
    start = time.monotonic()
    if os.environ.get("BENCH_PROFILE"):  # stacks of the sending threads, every 3 s
        import faulthandler

        faulthandler.dump_traceback_later(3, repeat=True)
        report = laptop.sync_svc.send_files()
        faulthandler.cancel_dump_traceback_later()
    else:
        report = laptop.sync_svc.send_files()
    laptop.commit()
    took = time.monotonic() - start
    projects.close()
    return {
        "shape": args.shape,
        "store": args.store,
        "files": len(sizes),
        "bytes": total,
        "sent": report.sent,
        "owed": len(report.owed),
        "seconds": round(took, 1),
        "MB_per_s": round(total / 1e6 / took, 1),
        "prepare_seconds": round(prepared, 1),
    }


if __name__ == "__main__":
    main()
