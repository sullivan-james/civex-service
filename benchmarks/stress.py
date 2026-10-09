"""Stress-test a civex project made by generate.py: its metadata and its files.

Run from inside the project, with the civex you are testing:

    .venv/bin/python benchmarks/stress.py all

Parts (each also on its own):

    bench   time the things people do, over HTTP against a real `civex serve`:
            list pages (first, deep, filtered, sorted, on an ancestor's field),
            a record, search, Activity, file plans and listings, the storage
            report, export as links and as copies, a zip, a clean-up dry run
    load    several readers at once while one writer uploads files and makes
            and edits records; latency, throughput and every error, with
            "database is locked" called out
    chaos   take a volume away (rename its folder) and check reads say so
            instead of failing; kill a file move half way, resume it, and
            check nothing was lost
    check   every file a record uses is on a volume and (with --hash) still
            hashes to its name; the inventory matches the disk; `civex doctor`

`chaos` changes the project (files end up moved off a volume); everything else
only reads, apart from what `load` writes and the exports `bench` makes and
removes. A report is printed and saved as stress-<time>.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import signal
import socket
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

CIVEX = str(Path(sys.executable).with_name("civex"))
REPORT: dict = {"started": datetime.now(timezone.utc).isoformat(), "parts": {}}


# -- talking to the server ----------------------------------------------------


class Server:
    """`civex serve` on a free port, for as long as the `with` block."""

    def __init__(self) -> None:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}/api"
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> "Server":
        self.log = open("stress-server.log", "w")
        self.proc = subprocess.Popen(
            [CIVEX, "serve", "--port", str(self.port)],
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/health", timeout=1
                )
                return self
            except Exception:
                if self.proc.poll() is not None:
                    raise SystemExit("civex serve stopped; see stress-server.log")
                time.sleep(0.3)
        raise SystemExit("civex serve didn't answer within 60 s; see stress-server.log")

    def __exit__(self, *exc) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.log.close()


class Reply:
    def __init__(self, status: int, body: bytes, seconds: float):
        self.status, self.body, self.seconds = status, body, seconds

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self):
        return json.loads(self.body or b"null")

    def text(self) -> str:
        return self.body[:300].decode("utf-8", "replace")


def call(
    base: str,
    method: str,
    path: str,
    body=None,
    params=None,
    data: bytes | None = None,
    timeout: float = 600,
) -> Reply:
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    elif data is not None:
        headers["Content-Type"] = "application/octet-stream"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            # Read in chunks: a download is measured, not held.
            got = (
                bytearray()
                if r.headers.get_content_type() == "application/json"
                else None
            )
            while chunk := r.read(1 << 20):
                if got is not None:
                    got += chunk
            return Reply(r.status, bytes(got or b""), time.perf_counter() - t)
    except urllib.error.HTTPError as e:
        return Reply(e.code, e.read(), time.perf_counter() - t)
    except Exception as e:  # refused, reset, timed out
        return Reply(0, str(e).encode(), time.perf_counter() - t)


# -- what the project holds ---------------------------------------------------


class Project:
    """Names and ids the tests pick from, read once over HTTP."""

    def __init__(self, base: str):
        self.base = base
        cols = call(base, "GET", "/collections").json()
        self.collections = {c["name"]: c for c in cols}
        self.surveys = sorted(n for n in self.collections if n.startswith("survey-"))
        if not self.surveys:
            raise SystemExit(
                "No survey-* collections: run generate.py in this project first."
            )
        self.samples: dict[str, dict[str, list[dict]]] = defaultdict(dict)
        for c in self.surveys:
            for schema in ("encounter", "recording", "selection"):
                page = call(
                    base,
                    "GET",
                    f"/collections/{c}/records",
                    params={"schema": schema, "limit": 200},
                ).json()
                self.samples[c][schema] = page["items"]
                self.samples[c][f"{schema}_total"] = page["total"]  # type: ignore[assignment]
        self.volumes = [v["name"] for v in call(base, "GET", "/store/volumes").json()]

    def pick(self, rnd: random.Random, schema: str) -> tuple[str, dict]:
        c = rnd.choice(self.surveys)
        items = self.samples[c][schema]
        return c, rnd.choice(items)

    def file_shas(self) -> list[str]:
        shas = []
        for c in self.surveys:
            for r in self.samples[c]["recording"]:
                if isinstance(r["data"].get("audio"), dict):
                    shas.append(r["data"]["audio"]["sha256"])
        return shas


# -- timing -------------------------------------------------------------------


def summarise(times: list[float]) -> dict:
    if not times:
        return {}
    s = sorted(times)
    return {
        "n": len(s),
        "p50_ms": round(statistics.median(s) * 1000, 1),
        "p95_ms": round(s[min(len(s) - 1, int(len(s) * 0.95))] * 1000, 1),
        "max_ms": round(s[-1] * 1000, 1),
    }


def table(rows: list[dict], cols: list[str]) -> None:
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    print("  " + "  ".join(c.ljust(widths[c]) for c in cols))
    for r in rows:
        print("  " + "  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))


# -- bench --------------------------------------------------------------------


def bench(srv: Server, reps: int) -> None:
    print(f"\n== bench: each operation {reps} times, over HTTP")
    base, rnd = srv.base, random.Random(7)
    p = Project(base)
    c0 = p.surveys[0]
    total = p.samples[c0]["selection_total"]
    whistles = json.dumps({"field": "label", "op": "eq", "value": "whistle"})
    big_groups = json.dumps(
        {"schema": "encounter", "field": "group_size", "op": "gt", "value": 30}
    )

    def page(**params):
        return lambda: call(
            base,
            "GET",
            f"/collections/{c0}/records",
            params={"schema": "selection", "limit": 50, **params},
        )

    def a_record(schema):
        return lambda: call(base, "GET", f"/records/{p.pick(rnd, schema)[1]['id']}")

    enc = p.samples[c0]["encounter"][0]["id"]
    ops = [
        ("collections", lambda: call(base, "GET", "/collections")),
        ("page: first 50 selections", page()),
        ("page: halfway through", page(offset=max(0, total // 2))),
        ("page: last", page(offset=max(0, total - 50))),
        ("page: filtered (label)", page(filter=whistles)),
        ("page: sorted (confidence)", page(sort="confidence:desc")),
        ("page: on an ancestor's field", page(filter=big_groups)),
        ("page: search", page(search="whistle")),
        ("record: a recording (named files)", a_record("recording")),
        ("record: a selection", a_record("selection")),
        (
            "reference picker search",
            lambda: call(
                base,
                "GET",
                "/records",
                params={
                    "schema": "species",
                    "search": "Species 01",
                    "reachable_from": c0,
                },
            ),
        ),
        (
            "activity: first page",
            lambda: call(base, "GET", "/audit/events", params={"limit": 50}),
        ),
        (
            "files: plan a whole collection",
            lambda: call(base, "POST", "/file-access/plan", {"collection": c0}),
        ),
        (
            "files: list a page of a collection",
            lambda: call(
                base, "POST", "/file-access/files", {"collection": c0, "limit": 100}
            ),
        ),
        (
            "files: zip one encounter",
            lambda: call(
                base,
                "POST",
                "/file-access/zip",
                {
                    "collection": c0,
                    "schema_name": "recording",
                    "within": enc,
                    "below": True,
                    "allow_partial": True,
                },
            ),
        ),
        ("storage: by collection", lambda: call(base, "GET", "/store/collections")),
        ("storage: volumes", lambda: call(base, "GET", "/store/volumes")),
        ("clean-up: dry run", lambda: call(base, "POST", "/store/gc", {})),
        (
            "retention: dry run",
            lambda: call(
                base, "POST", "/retention/run", {"audit_before": "2000-01-01T00:00:00Z"}
            ),
        ),
    ]
    rows = []
    for name, fn in ops:
        times, statuses = [], Counter()
        for _ in range(reps):
            r = fn()
            times.append(r.seconds)
            statuses[r.status] += 1
        bad = {s: n for s, n in statuses.items() if not 200 <= s < 300}
        rows.append(
            {
                "operation": name,
                **summarise(times),
                "errors": ", ".join(f"{s}×{n}" for s, n in bad.items()) or "",
            }
        )
        print(
            f"  {name:<36} p50 {rows[-1]['p50_ms']:>8} ms"
            + (f"   errors {rows[-1]['errors']}" if bad else ""),
            flush=True,
        )

    # Exports make folders: time one of each and take it away again.
    for mode in ("link", "copy"):
        name = f"stress-{mode}-{int(time.time())}"
        r = call(
            base,
            "POST",
            "/file-access/export",
            {
                "collection": c0,
                "schema_name": "recording",
                "within": enc,
                "below": True,
                "mode": mode,
                "name": name,
                "allow_partial": True,
            },
        )
        note = ""
        if not r.ok:
            try:
                note = r.json().get("detail", {}).get("code", "") or r.text()
            except Exception:
                note = r.text()
        else:
            done = r.json()
            note = f"{done.get('linked', 0)} linked, {done.get('copied', 0)} copied"
            gone = call(
                base, "POST", "/file-access/exports/remove", {"paths": [done["dest"]]}
            )
            if not gone.ok or gone.json().get("errors"):
                note += f"; not removed: {gone.text()}"
        rows.append(
            {
                "operation": f"export one encounter ({mode})",
                **summarise([r.seconds]),
                "errors": "" if r.ok else f"{r.status}",
                "note": note,
            }
        )
        print(
            f"  {'export one encounter (' + mode + ')':<36} p50 "
            f"{r.seconds * 1000:>8.1f} ms   {'' if r.ok else r.status} {note}"
        )
    REPORT["parts"]["bench"] = rows


# -- load ---------------------------------------------------------------------


def load(srv: Server, readers: int, seconds: int, upload_kb: int) -> None:
    print(f"\n== load: {readers} readers and 1 writer for {seconds} s")
    base = srv.base
    p = Project(base)
    shas = p.file_shas()
    lats: dict[str, list[float]] = defaultdict(list)
    errors: Counter = Counter()
    locked = Counter()
    lock = threading.Lock()
    stop = time.monotonic() + seconds

    def note(op: str, r: Reply) -> None:
        with lock:
            lats[op].append(r.seconds)
            if not r.ok:
                errors[(op, r.status)] += 1
                if b"locked" in r.body.lower():
                    locked[op] += 1

    def reader(seed: int) -> None:
        rnd = random.Random(seed)
        while time.monotonic() < stop:
            c = rnd.choice(p.surveys)
            kind = rnd.random()
            if kind < 0.4:
                total = p.samples[c]["selection_total"]
                note(
                    "read: page",
                    call(
                        base,
                        "GET",
                        f"/collections/{c}/records",
                        params={
                            "schema": "selection",
                            "limit": 50,
                            "offset": rnd.randrange(max(1, total)),
                        },
                    ),
                )
            elif kind < 0.65:
                _, rec = p.pick(rnd, "recording")
                note("read: record", call(base, "GET", f"/records/{rec['id']}"))
            elif kind < 0.8:
                note(
                    "read: filtered page",
                    call(
                        base,
                        "GET",
                        f"/collections/{c}/records",
                        params={
                            "schema": "selection",
                            "limit": 50,
                            "sort": "confidence:desc",
                            "filter": json.dumps(
                                {
                                    "field": "reviewed",
                                    "op": "eq",
                                    "value": rnd.random() < 0.5,
                                }
                            ),
                        },
                    ),
                )
            elif kind < 0.92 and shas:
                note(
                    "read: download a file",
                    call(base, "GET", f"/files/{rnd.choice(shas)}"),
                )
            else:
                enc = rnd.choice(p.samples[c]["encounter"])["id"]
                note(
                    "read: plan an encounter's files",
                    call(
                        base,
                        "POST",
                        "/file-access/plan",
                        {
                            "collection": c,
                            "schema_name": "recording",
                            "within": enc,
                            "below": True,
                        },
                    ),
                )

    made = Counter()

    def writer() -> None:
        rnd = random.Random(99)
        while time.monotonic() < stop:
            c, enc = p.pick(rnd, "encounter")
            coll_id = p.collections[c]["id"]
            blob = rnd.randbytes(upload_kb * 1024)
            up = call(
                base,
                "PUT",
                "/files/stream",
                data=blob,
                params={"filename": "load.wav", "collection": coll_id},
            )
            note("write: upload", up)
            if not up.ok:
                continue
            ref = up.json()
            rec = call(
                base,
                "POST",
                f"/collections/{c}/records",
                {
                    "schema_name": "recording",
                    "parent_record_id": enc["id"],
                    "data": {
                        "file_name": "load.wav",
                        "duration_s": 12.5,
                        "sample_rate": 96000,
                        "quality": "good",
                        "started_at": "2024-05-01T10:00:00Z",
                        "audio": {k: ref[k] for k in ("sha256", "filename", "size")},
                    },
                },
            )
            note("write: create a recording", rec)
            if rec.ok:
                made["recordings"] += 1
            _, sel = p.pick(rnd, "selection")
            data = {
                **{k: v for k, v in sel["data"].items() if k != "table"},
                "confidence": round(rnd.random(), 3),
            }
            if isinstance(sel["data"].get("table"), dict):
                data["table"] = {
                    k: sel["data"]["table"][k] for k in ("sha256", "filename", "size")
                }
            note(
                "write: edit a selection",
                call(base, "PATCH", f"/records/{sel['id']}", {"data": data}),
            )

    threads = [threading.Thread(target=reader, args=(i,)) for i in range(readers)]
    threads.append(threading.Thread(target=writer))
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rows = [
        {
            "operation": op,
            **summarise(ts),
            "per_s": round(len(ts) / seconds, 1),
            "errors": sum(n for (o, _), n in errors.items() if o == op),
            "locked": locked.get(op, 0),
        }
        for op, ts in sorted(lats.items())
    ]
    table(
        rows,
        ["operation", "n", "per_s", "p50_ms", "p95_ms", "max_ms", "errors", "locked"],
    )
    for (op, status), n in errors.most_common(10):
        print(f"  ! {op}: HTTP {status or 'no answer'} ×{n}")
    REPORT["parts"]["load"] = {
        "rows": rows,
        "recordings_made": made["recordings"],
        "errors": {f"{o} {s}": n for (o, s), n in errors.items()},
    }


# -- check --------------------------------------------------------------------


def check(full_hash: bool) -> bool:
    print(
        "\n== check: files and inventory"
        + (" (hashing every file)" if full_hash else "")
    )
    from sqlalchemy import text

    from civex.config import load_config
    from civex.context import build_local_context

    ctx = build_local_context(load_config())
    store = ctx.file_svc._store
    s = ctx._session
    referenced = [
        r[0]
        for r in s.execute(
            text(
                "SELECT DISTINCT sha256 FROM file_references WHERE record_id IS NOT NULL"
            )
        )
    ]
    copies: dict[str, list[str]] = defaultdict(list)
    for sha, volume in s.execute(text("SELECT sha256, volume FROM stored_objects")):
        copies[sha].append(volume)

    problems: Counter = Counter()
    examples: dict[str, list[str]] = defaultdict(list)

    def bad(kind: str, detail: str) -> None:
        problems[kind] += 1
        if len(examples[kind]) < 5:
            examples[kind].append(detail)

    t0 = time.monotonic()
    for i, sha in enumerate(referenced):
        if not copies.get(sha):
            bad("referenced but in no volume's inventory", sha)
            continue
        found = False
        for volume in copies[sha]:
            path = store.path_on(sha, volume)
            if path is None or not Path(path).exists():
                bad("inventory says here, disk doesn't", f"{sha[:12]} on {volume}")
                continue
            found = True
            if full_hash:
                h = hashlib.sha256()
                with open(path, "rb") as f:
                    while chunk := f.read(1 << 20):
                        h.update(chunk)
                if h.hexdigest() != sha:
                    bad("content doesn't match its hash", f"{sha[:12]} on {volume}")
        if not found:
            bad("no readable copy", sha)
        if (i + 1) % 5000 == 0:
            print(f"  {i + 1:,} of {len(referenced):,} files…", flush=True)

    # Every blob on disk is in the inventory (an orphan costs space and can't be
    # cleaned up by what the inventory knows).
    on_disk = 0
    for name, vc in ctx.store_svc._config.store_config.volumes.items():
        root = store._resolve_path(vc)
        if not root.is_dir():
            bad("volume folder missing", name)
            continue
        for shard in root.iterdir():
            if len(shard.name) != 2 or not shard.is_dir():
                continue
            for f in shard.iterdir():
                if f.suffix:
                    continue  # scratch (.part) files
                on_disk += 1
                if name not in copies.get(shard.name + f.name, []):
                    bad(
                        "on disk but not in the inventory",
                        f"{shard.name}{f.name[:10]} on {name}",
                    )
    ctx.close()

    doctor = subprocess.run([CIVEX, "doctor"], capture_output=True, text=True)
    if doctor.returncode != 0:
        bad(
            "civex doctor reported problems",
            doctor.stdout.strip().splitlines()[-1]
            if doctor.stdout.strip()
            else str(doctor.returncode),
        )

    took = time.monotonic() - t0
    print(
        f"  {len(referenced):,} files records use, {sum(map(len, copies.values())):,} "
        f"copies in the inventory, {on_disk:,} on disk ({took:,.0f} s)"
    )
    if not problems:
        print(
            "  OK: nothing missing, nothing unaccounted for"
            + (", every file hashes to its name" if full_hash else "")
        )
    for kind, n in problems.items():
        print(f"  ! {kind}: {n:,}  e.g. {', '.join(examples[kind])}")
    REPORT["parts"].setdefault("check", []).append(
        {
            "files": len(referenced),
            "on_disk": on_disk,
            "hashed": full_hash,
            "problems": dict(problems),
            "examples": dict(examples),
        }
    )
    return not problems


# -- chaos --------------------------------------------------------------------


def volume_paths() -> dict[str, Path]:
    from civex.config import load_config
    from civex.context import build_local_context

    ctx = build_local_context(load_config())
    store = ctx.file_svc._store
    out = {
        n: store._resolve_path(vc)
        for n, vc in ctx.store_svc._config.store_config.volumes.items()
    }
    ctx.close()
    return out


def unplug(srv: Server) -> list[dict]:
    """Rename a volume's folder (outside the project) and check what reads say."""
    print("  taking a volume away…")
    base = srv.base
    p = Project(base)
    paths = volume_paths()
    usage = call(base, "GET", "/store/volumes").json()
    held = [
        v["name"] for v in usage if v["name"] != "default" and v.get("civex_used_bytes")
    ]
    victim = held[0] if held else next((n for n in paths if n != "default"), None)
    if victim is None:
        return [
            {"check": "unplug", "ok": False, "detail": "no extra volume to take away"}
        ]
    folder = paths[victim]
    away = folder.with_name(folder.name + ".unplugged")
    results = []

    def expect(name: str, ok: bool, detail: str = "") -> None:
        results.append({"check": name, "ok": ok, "detail": detail})
        print(
            f"    {'ok ' if ok else 'FAIL'} {name}" + (f" ({detail})" if detail else "")
        )

    on_victim = [
        r
        for c in p.surveys
        for r in p.samples[c]["recording"]
        if isinstance(r["data"].get("audio"), dict)
        and (r["data"]["audio"].get("location") or {}).get("volume") == victim
    ]
    folder.rename(away)
    try:
        time.sleep(1)
        vols = {v["name"]: v for v in call(base, "GET", "/store/volumes").json()}
        v = vols.get(victim, {})
        expect(
            f"{victim} reported as not usable",
            v.get("available") is False,
            f"state {v.get('state')!r}",
        )
        if on_victim:
            rec = on_victim[0]
            r = call(base, "GET", f"/records/{rec['id']}")
            loc = (r.json()["data"]["audio"].get("location") or {}) if r.ok else {}
            expect("a record whose file is on it still opens", r.ok, f"HTTP {r.status}")
            expect(
                "and says its file can't be reached",
                loc.get("available") is False,
                f"location {loc}",
            )
            dl = call(base, "GET", f"/files/{rec['data']['audio']['sha256']}")
            expect(
                "downloading that file answers 503 naming the drive",
                dl.status == 503 and victim.encode() in dl.body,
                f"HTTP {dl.status}",
            )
            c = next(c for c in p.surveys if rec in p.samples[c]["recording"])
            plan = call(base, "POST", "/file-access/plan", {"collection": c})
            missing = plan.json().get("unavailable") if plan.ok else None
            expect(
                "planning its collection lists what is out of reach",
                bool(missing),
                f"HTTP {plan.status}",
            )
        else:
            expect("a sampled record with a file on it", False, "none in the sample")
    finally:
        away.rename(folder)
    time.sleep(1)
    vols = {v["name"]: v for v in call(base, "GET", "/store/volumes").json()}
    v = vols.get(victim, {})
    expect(
        f"{victim} usable again once back",
        v.get("available") is True,
        f"state {v.get('state')!r}",
    )
    return results


def interrupted_move(kill_after: float) -> list[dict]:
    """Start emptying a volume, kill the process mid-copy, resume, compare."""
    print("  moving files off a volume and killing the move half way…")
    paths = volume_paths()
    usage = {}
    for name, folder in paths.items():
        usage[name] = (
            sum(1 for shard in folder.glob("??") for _ in shard.iterdir())
            if folder.is_dir()
            else 0
        )
    sources = [n for n in usage if n != "default" and usage[n]]
    results = []

    def expect(name: str, ok: bool, detail: str = "") -> None:
        results.append({"check": name, "ok": ok, "detail": detail})
        print(
            f"    {'ok ' if ok else 'FAIL'} {name}" + (f" ({detail})" if detail else "")
        )

    if not sources:
        expect("a volume with files to move", False, "none")
        return results
    source = max(sources, key=usage.get)
    before = usage[source]
    from civex.config import load_config
    from civex.context import build_local_context

    def latest():
        ctx = build_local_context(load_config())
        try:
            found = ctx.transfer_svc.recent(1)
        finally:
            ctx.close()
        return found[0] if found else None

    known = getattr(latest(), "id", None)
    proc = subprocess.Popen(
        [CIVEX, "store", "move", "--off", source, "--to", "default"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    # Kill once it has really copied something (plus --kill-after), so the
    # point is mid-move whatever the project's size or the CLI's start-up time.
    deadline = time.monotonic() + 120
    while proc.poll() is None and time.monotonic() < deadline:
        t = latest()
        if t and t.id != known and t.progress.bytes_done > 0:
            break
        time.sleep(0.05)
    time.sleep(kill_after)
    if proc.poll() is not None:
        expect(
            "the move was still running when killed",
            False,
            "it finished first; give it more files (a bigger --file-budget-gb)",
        )
    else:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        expect("killed mid-move", True)

    latest_move = latest()
    latest = [latest_move] if latest_move and latest_move.id != known else []
    if not latest:
        expect("the move was recorded", False)
        return results
    t = latest[0]
    print(
        f"    killed with {t.progress.files_done:,} of {t.progress.files_total:,} "
        f"files done; the move says {t.status!r}"
    )
    if t.status != "completed":
        # A killed move still says "running" until its lock is free and it has
        # been silent for a short grace period; retry as a person would.
        killed_at = time.monotonic()
        while True:
            resumed = subprocess.run(
                [CIVEX, "store", "transfers", "resume", t.id],
                capture_output=True,
                text=True,
            )
            said = (resumed.stdout + resumed.stderr).strip()
            if "is running" not in said or time.monotonic() - killed_at > 120:
                break
            time.sleep(2)
        waited = time.monotonic() - killed_at
        expect(
            "resume finished",
            resumed.returncode == 0,
            f"could resume {waited:.0f} s after the kill; "
            + (said.splitlines()[-1] if said else ""),
        )
    after = (
        sum(1 for shard in paths[source].glob("??") for _ in shard.iterdir())
        if paths[source].is_dir()
        else 0
    )
    expect(f"{source} emptied", after == 0, f"{before:,} files before, {after:,} after")
    return results


def chaos(srv: Server, kill_after: float) -> bool:
    print("\n== chaos")
    results = unplug(srv)
    # The move runs from the CLI, as a person would; the server is stopped so
    # its own transfer thread can't pick the move up instead.
    srv.__exit__(None, None, None)
    results += interrupted_move(kill_after)
    ok = check(full_hash=True)
    REPORT["parts"]["chaos"] = results
    return ok and all(r["ok"] for r in results)


# -----------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("part", choices=["bench", "load", "chaos", "check", "all"])
    ap.add_argument(
        "--reps", type=int, default=5, help="bench: times each operation runs"
    )
    ap.add_argument("--readers", type=int, default=4, help="load: reader threads")
    ap.add_argument("--seconds", type=int, default=60, help="load: how long")
    ap.add_argument(
        "--upload-kb", type=int, default=512, help="load: size of each upload"
    )
    ap.add_argument("--hash", action="store_true", help="check: hash every file")
    ap.add_argument(
        "--kill-after",
        type=float,
        default=0.0,
        help="chaos: seconds after the move starts copying before it is killed",
    )
    args = ap.parse_args()

    if not Path("_civex").is_dir():
        raise SystemExit(
            "Run this from inside a civex project (a folder with _civex/)."
        )
    if not Path(CIVEX).exists():
        raise SystemExit(
            f"No civex next to {sys.executable}; run with the venv's python."
        )

    ok = True
    if args.part in ("bench", "load", "all"):
        with Server() as srv:
            if args.part in ("bench", "all"):
                bench(srv, args.reps)
            if args.part in ("load", "all"):
                load(srv, args.readers, args.seconds, args.upload_kb)
    if args.part in ("chaos", "all"):
        with Server() as srv:
            ok = chaos(srv, args.kill_after) and ok
    elif args.part in ("check",):
        ok = check(args.hash)

    out = Path(f"stress-{datetime.now():%Y%m%d-%H%M%S}.json")
    out.write_text(json.dumps(REPORT, indent=2, default=str))
    print(f"\nreport: {out}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
