"""An authority on PostgreSQL, devices on SQLite: the migrations' PostgreSQL
parts (the write order is a sequence there), history as deltas, settling whole
actions under PostgreSQL's locking, and the random scenarios of
`test_invariants` must all hold.

Runs only when CIVEX_TEST_POSTGRES_URL names a server it may create databases
on (a throwaway one), e.g. postgresql+psycopg2://civex@127.0.0.1:54329/postgres.
Each test makes a database of its own."""

from __future__ import annotations

import os
import random
import uuid

import pytest
from sqlalchemy import create_engine, text

from civex.config import load_config
from civex.context import build_local_context
from civex.domain.sync import SyncError
from civex.project import scaffold_project

from .peers import build_study, connect, device, flaky, snapshots
from .test_convergence import differences, quiesce
from .test_invariants import act, broken_rules, populate

_SERVER = os.environ.get("CIVEX_TEST_POSTGRES_URL")
pytestmark = [
    pytest.mark.skipif(not _SERVER, reason="CIVEX_TEST_POSTGRES_URL not set"),
    pytest.mark.usefixtures("strict_schema_lists"),
]


@pytest.fixture()
def pg_authority(tmp_path):
    name = f"civex_{uuid.uuid4().hex[:12]}"
    admin = create_engine(_SERVER, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = _SERVER.rsplit("/", 1)[0] + f"/{name}"
    root = tmp_path / "authority"
    scaffold_project(root, db_url=url)
    previous = os.getcwd()
    os.chdir(root)
    try:
        ctx = build_local_context(load_config())
    finally:
        os.chdir(previous)
    yield ctx
    ctx.close()
    ctx._session.get_bind().dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


def test_history_on_postgresql_is_numbered_in_write_order_and_stored_as_deltas(
    pg_authority,
):
    ctx = pg_authority
    record = build_study(ctx)
    ctx.record_svc.update(str(record.id), {"site": "y", "depth": 1.0})
    ctx.commit()
    rows = ctx._session.execute(
        text(
            "SELECT action, local_seq, format FROM audit_log "
            "WHERE entity_id = :i ORDER BY local_seq"
        ),
        {"i": record.id},
    ).all()
    assert [r.action for r in rows] == ["create", "update"]
    assert rows[0].local_seq < rows[1].local_seq
    assert rows[1].format == 2


def test_devices_and_a_postgresql_authority_agree(project, pg_authority):
    laptop = device(project, pg_authority, "laptop")
    record = build_study(laptop)
    connect(laptop)
    phone = device(project, pg_authority, "phone")
    assert connect(phone) == "joined"
    laptop.record_svc.update(str(record.id), {"site": "laptop", "depth": 1.0})
    phone.record_svc.update(str(record.id), {"site": "x", "depth": 9.0})
    laptop.commit()
    phone.commit()
    for ctx in (laptop, phone, laptop, phone):
        ctx.sync_svc.sync()
    expected = snapshots(pg_authority)
    assert differences(expected, snapshots(laptop)) == []
    assert differences(expected, snapshots(phone)) == []


@pytest.mark.parametrize("seed", range(int(os.environ.get("CIVEX_PG_SEEDS", "5"))))
def test_random_changes_with_a_postgresql_authority_keep_the_rules(
    project, pg_authority, seed
):
    rng = random.Random(f"invariants-{seed}")
    first = device(project, pg_authority, "d1", flaky=True)
    populate(first)
    connect(first)
    devices = [first]
    for name in ("d2", "d3"):
        other = device(project, pg_authority, name, flaky=True)
        connect(other)
        devices.append(other)
    quiesce(devices)
    for step in range(40):
        act(rng.choice(devices), rng, step)
        if rng.random() < 0.35:
            who = rng.choice(devices)
            if rng.random() < 0.3:
                flaky(who).fail(
                    rng.choice(["push", "feed", "hello"]),
                    rng.choice(["refuse", "lose_reply"]),
                )
            try:
                who.sync_svc.sync()
            except SyncError:
                pass
    quiesce(devices)
    problems = [f"authority: {p}" for p in broken_rules(pg_authority)]
    expected = snapshots(pg_authority)
    for ctx in devices:
        waiting = {str(c.entity_id)[:8] for c in ctx.sync_svc.conflicts()}
        problems += [
            d
            for d in differences(expected, snapshots(ctx))
            if d.split()[1].rstrip(":") not in waiting
        ]
    assert not problems, f"seed {seed}:\n" + "\n".join(problems[:20])
