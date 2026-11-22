"""civex.usage.project_usage: bytes counted once per file, records exact on
SQLite and planner-estimated on PostgreSQL, tenant search_path honoured.

The PostgreSQL half needs CIVEX_TEST_POSTGRES_URL (a scratch database) and is
skipped without it."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civex import usage
from civex.db.migrate import ensure_schema_current
from civex.db.models import Dataset, Record, Schema, StoredObject
from civex.usage import Usage, project_usage

_PG_URL = os.environ.get("CIVEX_TEST_POSTGRES_URL")


def _fill(engine: Engine, records: int) -> None:
    with Session(engine) as s:
        schema = Schema(id=uuid.uuid4(), name=f"s-{uuid.uuid4().hex[:8]}")
        dataset = Dataset(id=uuid.uuid4(), name=f"d-{uuid.uuid4().hex[:8]}")
        s.add_all([schema, dataset])
        s.flush()
        s.add_all(
            Record(id=uuid.uuid4(), dataset_id=dataset.id, schema_id=schema.id, data={})
            for _ in range(records)
        )
        # "a" is on two drives (counts once); "b" on one.
        s.add_all(
            [
                StoredObject(sha256="a" * 64, volume="d1", size=100),
                StoredObject(sha256="a" * 64, volume="d2", size=100),
                StoredObject(sha256="b" * 64, volume="d1", size=50),
            ]
        )
        s.commit()


@pytest.fixture()
def sqlite_engine(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'p.db'}")
    ensure_schema_current(engine)
    yield engine
    engine.dispose()


def test_empty_project(sqlite_engine: Engine) -> None:
    u = project_usage(sqlite_engine)
    assert isinstance(u, Usage)
    assert (u.stored_bytes, u.stored_objects, u.records_estimate) == (0, 0, 0)
    assert u.records_exact is True
    assert u.measured_at.tzinfo is not None


def test_sqlite_counts_exact_and_dedupes_files(sqlite_engine: Engine) -> None:
    _fill(sqlite_engine, 7)
    u = project_usage(sqlite_engine)
    assert u.stored_bytes == 150
    assert u.stored_objects == 2
    assert u.records_estimate == 7
    assert u.records_exact is True


def test_missing_tables_give_none_not_zero(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'bare.db'}")
    u = project_usage(engine)
    assert (u.stored_bytes, u.stored_objects, u.records_estimate) == (None, None, None)
    assert u.records_exact is False
    engine.dispose()


pg = pytest.mark.skipif(not _PG_URL, reason="set CIVEX_TEST_POSTGRES_URL to run")


@pytest.fixture()
def tenant_engine():
    """An engine whose search_path is a fresh schema, as a multi-tenant host
    builds one; the public schema is left alone."""
    assert _PG_URL
    name = f"usage_{uuid.uuid4().hex[:10]}"
    admin = create_engine(_PG_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE SCHEMA "{name}"'))
    url = create_engine(_PG_URL).url.update_query_dict(
        {"options": f"-csearch_path={name}"}
    )
    engine = create_engine(url)
    ensure_schema_current(engine)
    yield engine
    engine.dispose()
    with admin.connect() as c:
        c.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
    admin.dispose()


@pg
def test_pg_never_analysed_counts_up_to_the_cap(tenant_engine: Engine) -> None:
    _fill(tenant_engine, 7)
    u = project_usage(tenant_engine)
    assert u.stored_bytes == 150
    assert u.stored_objects == 2
    assert u.records_estimate == 7
    assert u.records_exact is True  # counted, under the cap


@pg
def test_pg_cap_is_reported_as_inexact(
    tenant_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fill(tenant_engine, 7)
    monkeypatch.setattr(usage, "RECORDS_COUNT_CAP", 3)
    u = project_usage(tenant_engine)
    assert u.records_estimate == 3
    assert u.records_exact is False


@pg
def test_pg_analysed_uses_the_planner_estimate(tenant_engine: Engine) -> None:
    _fill(tenant_engine, 7)
    with tenant_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text("ANALYZE records"))
    u = project_usage(tenant_engine)
    assert u.records_estimate == 7
    assert u.records_exact is False


@pg
def test_pg_timeout_gives_none(
    tenant_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fill(tenant_engine, 1)
    monkeypatch.setattr(usage, "STATEMENT_TIMEOUT_MS", 1)
    monkeypatch.setattr(
        usage, "_stored", lambda conn: conn.execute(text("SELECT pg_sleep(1)"))
    )
    u = project_usage(tenant_engine)
    assert u.stored_bytes is None and u.stored_objects is None
    assert u.records_estimate == 1  # the other measurement is unaffected


@pg
def test_pg_is_read_only(
    tenant_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write(conn):  # type: ignore[no-untyped-def]
        conn.execute(text("DELETE FROM stored_objects"))
        return 0, 0

    monkeypatch.setattr(usage, "_stored", write)
    assert project_usage(tenant_engine).stored_bytes is None


@pg
def test_pg_schema_argument_picks_the_tenant_on_a_shared_engine(
    tenant_engine: Engine,
) -> None:
    _fill(tenant_engine, 4)
    name = tenant_engine.url.query["options"].removeprefix("-csearch_path=")
    assert _PG_URL
    shared = create_engine(_PG_URL)
    try:
        u = project_usage(shared, schema=name)
        assert (u.stored_bytes, u.stored_objects, u.records_estimate) == (150, 2, 4)
    finally:
        shared.dispose()
