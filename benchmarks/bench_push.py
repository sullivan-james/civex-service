"""
Benchmark: what the authority does for one push of 100 entries, and for asking
which of 1000 files it lacks (`missing_files`).

Counts the statements the authority's database runs (SQLAlchemy's
`before_cursor_execute`) and the wall time, for 100 new records, 100 edits of
those records, and `missing_files` over 1000 hashes. Devices are SQLite; the
authority is SQLite unless PG_URL names a PostgreSQL server it may create a
database on (disposable).

Usage:
    python benchmarks/bench_push.py                       # SQLite authority
    PG_URL=postgresql+psycopg2://user@localhost:5432/postgres \
        python benchmarks/bench_push.py                   # PostgreSQL authority
Run it with this checkout's virtualenv.
"""

from __future__ import annotations

import collections
import os
import re
import tempfile
import time
import uuid
from pathlib import Path

from sqlalchemy import create_engine, event, text

from civex.config import load_config
from civex.context import build_local_context
from civex.project import scaffold_project
from civex.testing import Projects, build_study, connect, device

ENTRIES = 100
FILES = 1000


def _authority(root: Path, pg_url: str | None):
    if not pg_url:
        return Projects(root)("authority"), lambda: None
    name = f"civex_{uuid.uuid4().hex[:12]}"
    admin = create_engine(pg_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = pg_url.rsplit("/", 1)[0] + f"/{name}"
    scaffold_project(root / "authority", db_url=url)
    previous = os.getcwd()
    os.chdir(root / "authority")
    try:
        ctx = build_local_context(load_config())
    finally:
        os.chdir(previous)

    def drop() -> None:
        ctx.close()
        ctx._session.get_bind().dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))

    return ctx, drop


def _kind(sql: str) -> str:
    m = re.match(
        r"\s*(SELECT|INSERT INTO|UPDATE|DELETE FROM|SAVEPOINT|RELEASE|"
        r"ROLLBACK TO|BEGIN|COMMIT|SET|PRAGMA)\b",
        sql,
        re.I,
    )
    verb = m.group(1).upper() if m else sql[:12]
    table = re.search(r"(?:FROM|INTO|UPDATE)\s+\"?(\w+)", sql, re.I)
    return (
        f"{verb} {table.group(1)}"
        if table and verb in ("SELECT", "INSERT INTO", "UPDATE", "DELETE FROM")
        else verb
    )


class Counter:
    def __init__(self, engine) -> None:
        self.by: collections.Counter[str] = collections.Counter()
        event.listen(engine, "before_cursor_execute", self._count)

    def _count(self, conn, cursor, statement, *a) -> None:  # noqa: ANN001
        self.by[_kind(statement)] += 1

    def reset(self) -> None:
        self.by.clear()

    @property
    def total(self) -> int:
        return sum(self.by.values())


def _report(label: str, counter: Counter, seconds: float, n: int) -> None:
    print(
        f"\n{label}: {counter.total} statements ({counter.total / n:.2f} per "
        f"item), {seconds * 1000:.0f} ms"
    )
    for kind, count in counter.by.most_common(12):
        print(f"    {count:5d}  {kind}")


def main() -> None:
    pg_url = os.environ.get("PG_URL")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["CIVEX_USER_STATE"] = str(Path(tmp) / "user-state.toml")
        root = Path(tmp)
        authority, drop = _authority(root, pg_url)
        projects = Projects(root)
        try:
            laptop = device(projects, authority, "laptop")
            build_study(laptop)
            connect(laptop)
            laptop.sync_svc.sync()
            counter = Counter(authority._session.get_bind())

            ids = [
                laptop.record_svc.add(
                    "study", "encounter", {"site": f"s{i}", "depth": 1.0}
                ).id
                for i in range(ENTRIES)
            ]
            laptop.commit()
            counter.reset()
            t = time.perf_counter()
            laptop.sync_svc.sync()
            _report(
                f"push of {ENTRIES} new records (+ feed)",
                counter,
                time.perf_counter() - t,
                ENTRIES,
            )

            for i, rid in enumerate(ids):
                laptop.record_svc.update(str(rid), {"site": f"e{i}", "depth": 2.0})
            laptop.commit()
            counter.reset()
            t = time.perf_counter()
            laptop.sync_svc.sync()
            _report(
                f"push of {ENTRIES} edits (+ feed)",
                counter,
                time.perf_counter() - t,
                ENTRIES,
            )

            shas = [uuid.uuid4().hex + uuid.uuid4().hex for _ in range(FILES)]
            transport = laptop._holder["inner"]
            counter.reset()
            t = time.perf_counter()
            transport.missing_files(shas)
            _report(
                f"missing_files over {FILES} hashes",
                counter,
                time.perf_counter() - t,
                FILES,
            )
        finally:
            projects.close()
            drop()


if __name__ == "__main__":
    main()
