"""An authority on PostgreSQL, devices on SQLite: the migrations' PostgreSQL
parts (the write order is a sequence there), history as deltas, settling whole
actions under PostgreSQL's locking, and the random scenarios of
`test_invariants` must all hold.

Runs only when CIVEX_TEST_POSTGRES_URL names a server it may create databases
on (a throwaway one), e.g. postgresql+psycopg2://civex@127.0.0.1:54329/postgres.
Each test makes a database of its own."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from civex.config import load_config
from civex.context import build_local_context
from civex.project import scaffold_project

from civex.testing.peers import build_study, connect, device, snapshots
from civex.testing.convergence import differences
from civex.testing.invariants import scenario

_SERVER = os.environ.get("CIVEX_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not _SERVER, reason="CIVEX_TEST_POSTGRES_URL not set")


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
    problems = scenario(project, pg_authority, seed)
    assert not problems, f"seed {seed}:\n" + "\n".join(problems[:20])
