"""How fast files come down from an authority: many small files plus a few
large ones, over HTTP to an authority in its own process. A second device
joins and `fetch_files` is the only thing timed.

    PYTHONPATH=src python benchmarks/bench_bulk_download.py --small 2000 --big 3

Numbers are files/s and MB/s of file bytes. Everything is made under --work
and deleted afterwards. Runs on any checkout, to compare before and after.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bench_bulk_files import _content, _free_port, _wait  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--small", type=int, default=2000)
    ap.add_argument("--small-kb", type=float, default=11.0)
    ap.add_argument("--big", type=int, default=3)
    ap.add_argument("--big-mb", type=float, default=50.0)
    ap.add_argument("--work", default=str(Path.home() / ".cache" / "bench-download"))
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    work = Path(args.work)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    os.environ["CIVEX_USER_STATE"] = str(work / "user-state.json")
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
    scaffold_project(root, db_url=f"sqlite:///{(root / 'civex.db').as_posix()}")
    toml = root / "_civex" / "config.toml"
    toml.write_text(toml.read_text() + "\n[sync]\nserve = true\n")
    authority = build_local_context(load_config_at(root))
    _, invite = authority.device_keys.invite("laptop")
    _, invite2 = authority.device_keys.invite("phone")
    authority.commit()
    authority.close()
    port = _free_port()
    code = (
        "import os, uvicorn; os.chdir(%r); from civex.server.app import create_app; "
        "uvicorn.run(create_app(), host='127.0.0.1', port=%d, log_level='error')"
        % (str(root), port)
    )
    procs.append(subprocess.Popen([sys.executable, "-c", code]))
    _wait(port)
    url = f"http://127.0.0.1:{port}"

    projects = Projects(work / "devices")
    laptop = projects("laptop")
    build_study(laptop)
    laptop.schema_svc.add_field("encounter", "scan", "file")
    sizes = [int(args.small_kb * 1024)] * args.small + [
        int(args.big_mb * 1024 * 1024)
    ] * args.big
    for i, size in enumerate(sizes):
        ref = laptop.file_svc.store_bytes(_content(i, size), f"f{i}.bin")
        laptop.record_svc.add(
            "study", "encounter", {"site": f"s{i}", "scan": ref.to_dict()}
        )
        if i % 500 == 499:
            laptop.commit()
    laptop.commit()
    laptop.sync_svc.connect(url, invite)
    laptop.commit()
    laptop.sync_svc.sync()
    laptop.sync_svc.send_files()
    laptop.commit()

    phone = projects("phone")
    phone.sync_svc.connect(url, invite2)
    phone.commit()
    phone.sync_svc.sync()
    phone.commit()
    phone.sync_svc.set_download_files("all")
    phone.commit()
    start = time.monotonic()
    report = phone.sync_svc.fetch_files()
    phone.commit()
    took = time.monotonic() - start
    total = sum(sizes)
    projects.close()
    return {
        "files": len(sizes),
        "fetched": report.fetched,
        "absent": len(report.absent),
        "bytes": total,
        "seconds": round(took, 1),
        "files_per_s": round(report.fetched / took, 1),
        "MB_per_s": round(total / 1e6 / took, 1),
    }


if __name__ == "__main__":
    main()
