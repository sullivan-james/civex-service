"""A device whose own database is PostgreSQL: what sync writes there must fit
its columns (SQLite does not hold a value to its declared length).

Runs only when CIVEX_TEST_POSTGRES_URL names a server it may create databases
on (a throwaway one). Each test makes a database of its own."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from civex.testing.peers import build_study, connect, device, follow

_SERVER = os.environ.get("CIVEX_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not _SERVER, reason="CIVEX_TEST_POSTGRES_URL not set")


@pytest.fixture()
def pg_url():
    assert _SERVER
    name = f"civex_{uuid.uuid4().hex[:12]}"
    admin = create_engine(_SERVER, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    yield _SERVER.rsplit("/", 1)[0] + f"/{name}"
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


def test_following_another_server_with_conflicts_open(
    project, authority, pg_url, request
):
    """What was waiting for review is settled when the laptop moves on to
    another server, in a value its column holds."""
    laptop = device(lambda name: project(name, db_url=pg_url), authority, "laptop")
    request.addfinalizer(lambda: (laptop.close(), laptop._session.get_bind().dispose()))
    record = build_study(laptop)
    connect(laptop)
    phone = device(project, authority, "phone")
    connect(phone)
    phone.record_svc.update(str(record.id), {"site": "phone"})
    phone.commit()
    phone.sync_svc.sync()
    laptop.record_svc.update(str(record.id), {"site": "laptop"})
    laptop.commit()
    laptop.sync_svc.sync()
    assert [c for c in laptop.sync_svc.conflicts() if c.status == "open"]

    server = project("server")
    follow(laptop, server, "laptop")
    assert connect(laptop, "https://server.test") == "seeded"

    assert [c for c in laptop.sync_svc.conflicts() if c.status == "open"] == []
