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
    yield from _pg_authority(tmp_path)


@pytest.fixture()
def pg_single(tmp_path):
    """A second PostgreSQL authority, settling every change on its own."""
    for ctx in _pg_authority(tmp_path / "single"):
        ctx.authority_svc._bulk = False
        yield ctx


def _pg_authority(tmp_path):
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


def test_a_batch_written_in_bulk_is_what_one_at_a_time_writes(
    project, pg_authority, pg_single
):
    from .test_bulk_push import mixed, rows, send

    b, first, batch = mixed(project)
    for authority in (pg_authority, pg_single):
        send(authority, b.structure + first)
    answers = [send(a, batch) for a in (pg_authority, pg_single)]
    assert answers[0] == answers[1]
    assert [r[1] for r in answers[0][0]] == [
        "applied",
        "applied",
        "applied",
        "conflict",
        "applied",
        "rejected",
        "conflict",
    ]
    assert rows(pg_authority) == rows(pg_single)
    assert rows(pg_authority)["file_references"]


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


def test_devices_with_a_narrower_read_scope_on_postgresql(project, pg_authority):
    """Filtering the feed and the copy by collection, and catching up when a
    device is given more, must hold where the authority is PostgreSQL (the
    session-level limit is SQL there too)."""
    from .test_scoped_devices import SECRET, Study, held, text_of

    study = Study(project, pg_authority)
    assert SECRET not in text_of(study.limited)
    study.authority.record_svc.add("vault", "encounter", {"site": f"{SECRET} later"})
    study.authority.record_svc.add("open", "encounter", {"site": "open later"})
    study.authority.commit()
    study.sync(study.limited, study.full)
    assert SECRET not in text_of(study.limited)
    assert len(held(study.limited, "record")) == 3
    study.widen(study.open.id, study.vault.id)
    study.sync(study.limited, study.full)
    assert held(study.limited, "record") == held(study.full, "record")


def test_scoped_catch_up_and_trails_on_postgresql(project, pg_authority):
    """The JSON lookups behind a note's collection at a given number, and behind
    the records that left a collection, run in SQL on PostgreSQL (JSONB)."""
    from .test_scoped_devices import SECRET, Study, held

    study = Study(project, pg_authority)
    mover = study.vault_records[0]  # has a note
    study.authority.record_svc.update(str(mover.id), {"site": f"{SECRET} in vault"})
    study.authority.record_svc.move("open", ids=[str(mover.id)])
    study.authority.record_svc.update(str(mover.id), {"site": "in open"})
    study.authority.commit()
    study.authority.authority_svc.feed(0, 1)  # numbers the authority's own changes
    study.authority.commit()
    repo = study.authority.sync_repo
    trail = repo.collection_trails({mover.id})[mover.id]
    assert trail[0][2] == study.vault.id and trail[-1][2] == study.open.id
    left = repo.snapshots_page("record", None, 50, study.vault.id, 0)
    assert [r["id"] for r in left] == [str(mover.id)]
    study.widen(study.open.id, study.vault.id)
    study.sync(study.limited, study.full)
    assert held(study.limited, "record") == held(study.full, "record")
    assert held(study.limited, "note") == held(study.full, "note")
