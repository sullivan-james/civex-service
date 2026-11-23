"""Space on PostgreSQL: the empty room in a table that once held more, found
from the catalogs, and VACUUM FULL of just the tables where it is worth it.

Requires CIVEX_TEST_POSTGRES_URL (see test_search_vector_trigger.py); skipped
otherwise.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from civex.domain.exceptions import FeatureUnavailableError
from civex.repositories.local import db_space
from civex.repositories.local.db_space import LocalDbSpace

_PG_URL = os.environ.get("CIVEX_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.xdist_group("postgres_scratch"),
    pytest.mark.skipif(
        not _PG_URL,
        reason="set CIVEX_TEST_POSTGRES_URL to a scratch PostgreSQL DB to run this test",
    ),
]


@pytest.fixture()
def engine(monkeypatch):
    monkeypatch.setattr(db_space, "WORTH_BYTES", 2 * 1024 * 1024)
    monkeypatch.setattr(db_space, "MIN_BYTES", 256 * 1024)
    # A schema of its own per test, so nothing else touching the shared
    # scratch database can pull it out from under the test.
    SCHEMA = f"space_{uuid.uuid4().hex[:12]}"
    eng = create_engine(_PG_URL)
    with eng.begin() as c:
        c.execute(text(f"CREATE SCHEMA {SCHEMA}"))
    # Every connection of this engine is scoped to the schema, as the hub does.
    scoped = create_engine(_PG_URL, connect_args={"options": f"-csearch_path={SCHEMA}"})
    yield scoped
    scoped.dispose()
    with eng.begin() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
    eng.dispose()


def _bloat(engine, table: str) -> None:
    with engine.begin() as c:
        c.execute(text(f"CREATE TABLE {table} (id int PRIMARY KEY, note text)"))
        c.execute(
            text(
                f"INSERT INTO {table} SELECT g, repeat('x', 200) "
                "FROM generate_series(1, 40000) g"
            )
        )
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text(f"ANALYZE {table}"))
        c.execute(text(f"DELETE FROM {table} WHERE id <= 36000"))
        c.execute(text(f"VACUUM {table}"))  # reusable, but the table stays big


def _size(engine, table: str) -> int:
    with engine.connect() as c:
        return c.execute(text(f"SELECT pg_relation_size('{table}')")).scalar()


def test_space_estimates_empty_room_in_this_schema_only(engine) -> None:
    _bloat(engine, "bloated")
    with engine.begin() as c:  # a table that is full, and one elsewhere
        c.execute(text("CREATE TABLE tight (id int PRIMARY KEY, note text)"))
        c.execute(
            text("INSERT INTO tight SELECT g, 'y' FROM generate_series(1, 5000) g")
        )
        c.execute(text("ANALYZE tight"))
        c.execute(text("CREATE TABLE public.space_elsewhere AS SELECT 1 AS x"))
    try:
        space = LocalDbSpace(engine).space()
    finally:
        with engine.begin() as c:
            c.execute(text("DROP TABLE public.space_elsewhere"))
    assert space is not None and space.estimate
    assert [t.name for t in space.tables] == ["bloated"]
    held = _size(engine, "bloated")
    assert 0.6 * held < space.tables[0].free_bytes < held  # most of it is empty
    assert space.free_bytes >= space.tables[0].free_bytes
    assert space.size_bytes >= held  # the schema's tables, not the database


def test_reclaim_shrinks_only_the_worthwhile_table(engine) -> None:
    _bloat(engine, "bloated")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE tight (id int PRIMARY KEY, note text)"))
        c.execute(
            text("INSERT INTO tight SELECT g, 'y' FROM generate_series(1, 5000) g")
        )
    before, tight_before = _size(engine, "bloated"), _size(engine, "tight")
    svc = LocalDbSpace(engine)
    svc.reclaim()
    assert _size(engine, "bloated") < before / 4
    assert _size(engine, "tight") == tight_before  # not worth rewriting
    after = svc.space()
    assert after is not None and after.tables == []


def test_hosted_reclaim_is_refused_but_space_still_reported(engine) -> None:
    _bloat(engine, "bloated")
    before = _size(engine, "bloated")
    svc = LocalDbSpace(engine, may_vacuum_full=False)
    space = svc.space()
    assert space is not None and not space.can_reclaim and space.tables
    with pytest.raises(FeatureUnavailableError):
        svc.reclaim()
    assert _size(engine, "bloated") == before


def test_partitions_are_rewritten_not_the_parent(engine) -> None:
    with engine.begin() as c:
        c.execute(
            text("CREATE TABLE parted (id int, note text) PARTITION BY HASH (id)")
        )
        for i in range(2):
            c.execute(
                text(
                    f"CREATE TABLE parted_{i} PARTITION OF parted "
                    f"FOR VALUES WITH (MODULUS 2, REMAINDER {i})"
                )
            )
        c.execute(
            text(
                "INSERT INTO parted SELECT g, repeat('x', 200) "
                "FROM generate_series(1, 40000) g"
            )
        )
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text("ANALYZE parted_0"))
        c.execute(text("ANALYZE parted_1"))
        c.execute(text("DELETE FROM parted WHERE id <= 38000"))
        c.execute(text("VACUUM parted"))
    svc = LocalDbSpace(engine)
    names = {t.name for t in svc.space().tables}
    assert names == {"parted_0", "parted_1"}
    svc.reclaim()
    assert svc.space().tables == []


def test_table_without_stats_is_not_guessed_at(engine) -> None:
    with engine.begin() as c:
        c.execute(
            text(
                "CREATE TABLE fresh (id int, note text) WITH (autovacuum_enabled = false)"
            )
        )
        c.execute(
            text(
                "INSERT INTO fresh SELECT g, repeat('x', 200) FROM generate_series(1, 40000) g"
            )
        )
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text("VACUUM fresh"))  # sets reltuples, writes no pg_stats
    space = LocalDbSpace(engine).space()
    assert space is not None and space.tables == [] and space.free_bytes == 0
