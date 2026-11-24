"""Numbering an authority's own writes: one statement in the database, in the
write order, and once however many callers ask at the same time."""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from civex.db.models import AuditLog, SyncMeta
from civex.repositories.local.sync_repo import LocalSyncRepository

_SERVER = os.environ.get("CIVEX_TEST_POSTGRES_URL")


def _repo(ctx) -> LocalSyncRepository:
    return LocalSyncRepository(ctx._session)


def _old_way(repo: LocalSyncRepository) -> int:
    """What it did before: every row loaded, one counter update each."""
    from civex.repositories.local.sync_repo import _SYNCED, _WRITE_ORDER

    rows = (
        repo._s.query(AuditLog)
        .filter(AuditLog.hub_seq.is_(None), AuditLog.sync_state == "pending", _SYNCED)
        .order_by(*_WRITE_ORDER)
        .all()
    )
    for row in rows:
        row.hub_seq = repo.next_hub_seq()
        row.sync_state = "synced"
    repo._s.flush()
    return len(rows)


def _fill(session: Session, n: int, *, shuffle: bool = False) -> None:
    """n pending deletes, with ties in local_seq, equal timestamps, a few
    entries with no local_seq, several in one action (op_id)."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ops = [uuid.UUID(int=10_000 + k) for k in range(5)]
    rows = []
    for i in range(n):
        rows.append(
            AuditLog(
                id=uuid.UUID(int=(i * 7919) % (n * 3) + 1),
                action="delete",
                entity_type="record",
                entity_id=uuid.uuid4(),
                old_data={"i": i},
                new_data=None,
                timestamp=base + timedelta(seconds=(n - i) // 3),
                op_id=ops[i % 5] if i % 4 == 0 else None,
                local_seq=None if i % 11 == 0 else i // 2,
                sync_state="pending",
            )
        )
    session.add_all(rows)
    session.flush()


def _numbered(session: Session):
    return [
        (r.id, r.hub_seq, r.sync_state, r.op_id)
        for r in session.query(AuditLog)
        .filter(AuditLog.hub_seq.is_not(None))
        .order_by(AuditLog.hub_seq)
    ]


def test_numbers_match_the_old_one_by_one_way_row_for_row(project):
    new, old = project("new"), project("old")
    for ctx in (new, old):
        ctx.commit()
        ctx._session.query(AuditLog).delete()
        ctx.commit()
    import random

    state = random.getstate()
    for ctx in (new, old):
        random.setstate(state)
        _fill(ctx._session, 60)
        ctx.commit()
    head = _repo(new).head_seq()
    assert _repo(new).sequence_local_entries() == 60
    assert _old_way(_repo(old)) == 60
    new._session.expire_all()
    old._session.expire_all()
    a, b = _numbered(new._session), _numbered(old._session)
    assert a == b and [r[1] for r in a] == list(range(head + 1, head + 61))
    assert _repo(new).head_seq() == _repo(old).head_seq() == head + 60
    assert _repo(new).sequence_local_entries() == 0


def test_not_synced_kinds_and_non_pending_rows_are_left_alone(project):
    ctx = project("a")
    ctx.commit()
    ctx._session.query(AuditLog).delete()
    _fill(ctx._session, 5)
    ctx._session.add(
        AuditLog(
            action="create",
            entity_type="record",
            entity_id=uuid.uuid4(),
            new_data={},
            sync_state="seeding",
        )
    )
    ctx.commit()
    assert _repo(ctx).sequence_local_entries() == 5
    states = dict(
        ctx._session.execute(
            select(AuditLog.sync_state, func.count()).group_by(AuditLog.sync_state)
        ).all()
    )
    assert states == {"synced": 5, "seeding": 1}


def test_100k_pending_deletes_are_numbered_in_seconds(project):
    ctx = project("a")
    ctx.commit()
    ctx._session.query(AuditLog).delete()
    ctx.commit()
    s = ctx._session
    s.execute(
        text(
            "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n "
            "WHERE i < 100000) "
            "INSERT INTO audit_log (id, action, entity_type, entity_id, old_data, "
            "timestamp, local_seq, sync_state) "
            "SELECT lower(hex(randomblob(16))), 'delete', 'record', "
            "lower(hex(randomblob(16))), '{\"a\": 1}', '2026-01-01 00:00:00', i, "
            "'pending' FROM n"
        )
    )
    ctx.commit()
    started = time.perf_counter()
    assert _repo(ctx).sequence_local_entries() == 100_000
    took = time.perf_counter() - started
    assert took < 10, took
    assert _repo(ctx).head_seq() >= 100_000


# -- PostgreSQL ---------------------------------------------------------------

pg = pytest.mark.skipif(not _SERVER, reason="CIVEX_TEST_POSTGRES_URL not set")


@pytest.fixture()
def pg_url():
    name = f"civex_{uuid.uuid4().hex[:12]}"
    admin = create_engine(_SERVER, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = _SERVER.rsplit("/", 1)[0] + f"/{name}"
    from civex.db.migrate import ensure_schema_current

    engine = create_engine(url)
    ensure_schema_current(engine)
    engine.dispose()
    yield url
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


def _pg_fill(engine, n: int) -> None:
    with engine.begin() as c:
        c.execute(text("DELETE FROM audit_log"))
        c.execute(text("UPDATE sync_meta SET head_seq = 0"))
        c.execute(
            text(
                "INSERT INTO audit_log (id, action, entity_type, entity_id, old_data, "
                "timestamp, sync_state) "
                "SELECT gen_random_uuid(), 'delete', 'record', gen_random_uuid(), "
                "'{\"a\": 1}', now(), 'pending' FROM generate_series(1, :n)"
            ),
            {"n": n},
        )


@pg
def test_pg_100k_pending_deletes_are_numbered_in_seconds(pg_url):
    engine = create_engine(pg_url)
    _pg_fill(engine, 100_000)
    with Session(engine) as s:
        started = time.perf_counter()
        assert LocalSyncRepository(s).sequence_local_entries() == 100_000
        took = time.perf_counter() - started
        s.commit()
        print(f"100k numbered in {took:.2f}s")
        assert took < 5, took
        assert LocalSyncRepository(s).head_seq() == 100_000
        assert s.execute(select(func.max(AuditLog.hub_seq))).scalar_one() == 100_000
    engine.dispose()


@pg
def test_pg_a_second_session_waiting_on_the_counter_numbers_nothing(pg_url):
    import threading

    engine = create_engine(pg_url)
    _pg_fill(engine, 5_000)
    results: dict[str, int] = {}
    first_has_lock = threading.Event()
    second_started = threading.Event()

    def first() -> None:
        with Session(engine) as s:
            repo = LocalSyncRepository(s)
            results["first"] = repo.sequence_local_entries()
            first_has_lock.set()
            second_started.wait(5)
            time.sleep(0.5)  # the second is now blocked on the counter
            s.commit()

    def second() -> None:
        first_has_lock.wait(5)
        with Session(engine) as s:
            second_started.set()
            results["second"] = LocalSyncRepository(s).sequence_local_entries()
            results["head"] = LocalSyncRepository(s).head_seq()
            s.commit()

    threads = [threading.Thread(target=f) for f in (first, second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert results["first"] == 5_000 and results["second"] == 0
    assert results["head"] == 5_000
    with Session(engine) as s:
        assert s.execute(select(SyncMeta.head_seq)).scalar_one() == 5_000
        assert s.execute(select(func.max(AuditLog.hub_seq))).scalar_one() == 5_000
    engine.dispose()
