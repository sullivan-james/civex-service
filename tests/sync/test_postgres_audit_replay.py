"""Replaying an audit event on PostgreSQL stores it once.

`audit_log` is range-partitioned there, so its primary key is (id, timestamp)
and the database no longer refuses a second row with the same id on its own.
Every path that writes an entry made elsewhere (a device's push to the
authority, a device pulling the feed, history backfill) must therefore decide
by id itself. These tests drive each real path twice, with the event's time
also spelled differently (another offset, coarser precision), which would
slip past the primary key, and check that one row per id remains.

Runs only when CIVEX_TEST_POSTGRES_URL is set (see test_postgres_authority)."""

from __future__ import annotations

import os
import threading
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from civex.config import load_config
from civex.context import build_local_context
from civex.domain.sync import SyncEntry
from civex.project import scaffold_project
from civex.testing.peers import (
    build_study,
    connect,
    device,
    device_uuid,
    principal,
    wire,
)

_SERVER = os.environ.get("CIVEX_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not _SERVER, reason="CIVEX_TEST_POSTGRES_URL not set")


def _open(root):
    previous = os.getcwd()
    os.chdir(root)
    try:
        return build_local_context(load_config())
    finally:
        os.chdir(previous)


@pytest.fixture()
def authority(tmp_path):
    name = f"civex_{uuid.uuid4().hex[:12]}"
    admin = create_engine(_SERVER, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    root = tmp_path / "authority"
    scaffold_project(root, db_url=_SERVER.rsplit("/", 1)[0] + f"/{name}")
    ctx = _open(root)
    yield ctx
    ctx.close()
    ctx._session.get_bind().dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


def _count(ctx, entry_id) -> int:
    ctx._session.rollback()  # a fresh snapshot
    return ctx._session.execute(
        text("SELECT count(*) FROM audit_log WHERE id = :i"), {"i": entry_id}
    ).scalar_one()


def _respelled(entry: SyncEntry) -> SyncEntry:
    """The same instant, written another way: a +02:00 offset, whole seconds
    (a replay through a client that normalised or truncated the time)."""
    when = datetime.fromisoformat(entry.timestamp).astimezone(
        timezone(timedelta(hours=2))
    )
    return replace(entry, timestamp=when.replace(microsecond=0).isoformat())


def _pending(laptop) -> list[SyncEntry]:
    return [
        SyncEntry.from_dict(wire(e.to_dict()))
        for e in laptop.sync_repo.pending_entries(1000)
    ]


def test_a_push_replayed_stores_each_event_once(project, authority):
    laptop = project("laptop")
    build_study(laptop)
    entries = _pending(laptop)
    assert entries
    who = principal(authority, "laptop", device_uuid("laptop"))

    authority.authority_svc.push(who, entries)
    authority.commit()
    authority.authority_svc.push(who, entries)
    authority.commit()
    # same events, the time spelled differently: the primary key would not see
    # a repeat, the authority's record of what it has taken must
    authority.authority_svc.push(who, [_respelled(e) for e in entries])
    authority.commit()

    for e in entries:
        assert _count(authority, e.id) == 1
        # and a lookup by id still finds it
        assert authority.sync_repo.has_entry(e.id)
        assert authority.sync_repo.get_entry(e.id).id == e.id


def test_a_feed_pulled_twice_stores_each_event_once(project, authority):
    laptop = device(project, authority, "laptop")
    build_study(authority)
    assert connect(laptop) == "joined"
    phone = device(project, authority, "phone")
    connect(phone)
    laptop.schema_svc.create("extra")
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()

    ids = [e.id for e in authority.sync_repo.entries_after(0, 1000)[0]]
    assert ids
    for i in ids:
        assert _count(authority, i) == 1
    # pull everything again from the start, as after a lost cursor
    phone.sync_repo.set_cursor(0)
    phone.commit()
    phone.sync_svc.sync()
    for i in ids:
        assert _count(authority, i) == 1


def test_history_backfill_replayed_stores_each_event_once(authority):
    build_study(authority)
    source = authority.sync_repo.pending_entries(1000)
    # an event as another device made it, kept on this (PostgreSQL) copy the
    # way a pull or a history backfill does, three times, the last with the
    # time spelled differently
    foreign = replace(source[0], id=uuid.uuid4(), hub_seq=None)
    for variant in (foreign, foreign, _respelled(foreign)):
        if not authority.sync_repo.has_entry(variant.id):
            authority.sync_repo.insert_entry(variant, hub_seq=None)
        authority.commit()
    assert _count(authority, foreign.id) == 1
    assert authority.sync_repo.get_entry(foreign.id).id == foreign.id


def test_two_concurrent_replays_of_one_push_leave_one_row(project, authority):
    """Both pass the 'already taken?' check before either commits. The one
    that commits second hits the `sync_ops` primary key (a table that is not
    partitioned, so it keeps a unique index on the event id) and rolls back
    whole: it never stores a second copy."""
    laptop = project("laptop")
    build_study(laptop)
    entries = _pending(laptop)
    who = principal(authority, "laptop", device_uuid("laptop"))
    authority.commit()
    other = _open(authority.config.project_root)
    try:
        authority.authority_svc.push(who, entries)  # not committed yet
        outcome: list[object] = []

        def second():
            try:
                other.authority_svc.push(who, entries)
                other.commit()
                outcome.append("committed")
            except IntegrityError as e:
                other._session.rollback()
                outcome.append(e)

        t = threading.Thread(target=second)
        t.start()
        t.join(timeout=2)  # waits on the first's uncommitted unique key
        authority.commit()
        t.join(timeout=30)
        assert not t.is_alive()
        # whichever way the second ended, one row per event
        for e in entries:
            assert _count(authority, e.id) == 1
        # and a retry after the failure is answered from the record
        again = other.authority_svc.push(who, entries)
        other.commit()
        assert all(r.status for r in again.results)
        for e in entries:
            assert _count(authority, e.id) == 1
    finally:
        other.close()
        other._session.get_bind().dispose()
