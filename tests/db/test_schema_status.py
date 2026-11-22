"""civex.db.migrate.schema_status: where a database stands against this civex,
read without migrating (a host asking about many tenants must not trigger a
migration per tenant). Runs on SQLite, and on PostgreSQL inside non-default
schemas chosen by `search_path`, the way a multi-tenant host routes tenants
(needs CIVEX_TEST_POSTGRES_URL; skipped otherwise).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import URL, Engine, make_url

from civex.db import migrate
from civex.db.migrate import ensure_schema_current, head_revision, schema_status
from civex.domain.exceptions import DatabaseTooNewError


def _parent_of_head() -> str:
    parent = migrate._script_directory().get_revision(head_revision()).down_revision
    assert isinstance(parent, str)
    return parent


def _stamp(engine: Engine, revision: str) -> None:
    with engine.begin() as c:
        c.execute(text("UPDATE alembic_version SET version_num = :r"), {"r": revision})


def _stamped(engine: Engine) -> list[str]:
    with engine.connect() as c:
        return [
            r[0] for r in c.execute(text("SELECT version_num FROM alembic_version"))
        ]


def _tables(engine: Engine) -> list[str]:
    return inspect(engine).get_table_names()


def _check_four_states(make_engine: Callable[[str], Engine]) -> list[Engine]:
    """The four states, against engines `make_engine(name)` builds for
    separate, initially empty databases."""
    empty = make_engine("empty")
    status = schema_status(empty)
    assert (status.current, status.behind, status.too_new) == (None, True, False)
    assert status.head == head_revision()
    assert not status.up_to_date
    assert not _tables(empty)  # asking created nothing

    current = make_engine("current")
    ensure_schema_current(current)
    status = schema_status(current)
    assert (status.current, status.behind, status.too_new) == (
        head_revision(),
        False,
        False,
    )
    assert status.up_to_date

    behind = make_engine("behind")
    ensure_schema_current(behind)
    _stamp(behind, _parent_of_head())
    status = schema_status(behind)
    assert (status.current, status.behind, status.too_new) == (
        _parent_of_head(),
        True,
        False,
    )

    newer = make_engine("newer")
    ensure_schema_current(newer)
    _stamp(newer, "ffffffffffff")
    status = schema_status(newer)
    assert (status.current, status.behind, status.too_new) == (
        "ffffffffffff",
        False,
        True,
    )
    assert not status.up_to_date

    # Nothing above changed what was stamped.
    assert _stamped(behind) == [_parent_of_head()]
    assert _stamped(newer) == ["ffffffffffff"]
    assert not _tables(empty)
    return [empty, current, behind, newer]


def test_schema_status_on_sqlite(tmp_path: Path) -> None:
    engines: list[Engine] = []

    def make(name: str) -> Engine:
        engine = create_engine(f"sqlite:///{tmp_path / name}.db")
        engines.append(engine)
        return engine

    _check_four_states(make)
    for e in engines:
        e.dispose()


def test_schema_status_runs_only_reads(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'a.db'}")
    ensure_schema_current(engine)
    _stamp(engine, _parent_of_head())
    seen: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, *args):
        seen.append(statement)

    schema_status(engine)
    verbs = {s.lstrip().split(None, 1)[0].upper() for s in seen}
    assert verbs <= {"SELECT", "PRAGMA"}, seen
    assert sum("alembic_version" in s and "SELECT version_num" in s for s in seen) == 1
    engine.dispose()


def test_schema_status_does_not_mark_the_engine_migrated(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'a.db'}")
    schema_status(engine)
    assert engine not in migrate._migrated_engines
    ensure_schema_current(engine)  # still migrates afterwards
    assert schema_status(engine).up_to_date
    engine.dispose()


def test_pre_alembic_database_reports_behind(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'a.db'}")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE schemas (id INTEGER)"))
    status = schema_status(engine)
    assert (status.current, status.behind, status.too_new) == (None, True, False)
    assert "alembic_version" not in _tables(engine)
    engine.dispose()


def test_check_structure_names_what_is_missing(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'a.db'}")
    ensure_schema_current(engine)
    assert schema_status(engine).missing_structure is None
    assert schema_status(engine, check_structure=True).missing_structure == ()
    with engine.begin() as c:
        c.execute(text("DROP TABLE step_executions"))
    missing = schema_status(engine, check_structure=True).missing_structure
    assert missing == ("step_executions",)
    engine.dispose()


def test_head_is_computed_once() -> None:
    assert migrate._script_directory() is migrate._script_directory()


def test_migration_status_agrees(tmp_path: Path) -> None:
    from civex.services.db_service import migration_status

    url = f"sqlite:///{tmp_path / 'a.db'}"
    engine = create_engine(url)
    ensure_schema_current(engine)
    assert migration_status(url).up_to_date
    _stamp(engine, "ffffffffffff")
    info = migration_status(url)
    assert info.too_new and not info.up_to_date
    assert info.current_revision == "ffffffffffff"
    engine.dispose()


def test_ensure_still_refuses_a_newer_database(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'a.db'}")
    ensure_schema_current(engine)
    _stamp(engine, "ffffffffffff")
    fresh = create_engine(f"sqlite:///{tmp_path / 'a.db'}")
    with pytest.raises(DatabaseTooNewError):
        ensure_schema_current(fresh)
    engine.dispose()
    fresh.dispose()


# -- PostgreSQL, tenants chosen by search_path --------------------------------

_PG_URL = os.environ.get("CIVEX_TEST_POSTGRES_URL")


@pytest.mark.xdist_group("postgres_scratch")
@pytest.mark.skipif(not _PG_URL, reason="CIVEX_TEST_POSTGRES_URL not set")
def test_schema_status_on_postgres_with_search_path() -> None:
    assert _PG_URL is not None
    base_url = make_url(_PG_URL)
    admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
    created: list[str] = []
    engines: list[Engine] = []

    def make(name: str) -> Engine:
        schema = f"ss_{name}_{uuid.uuid4().hex[:8]}"
        with admin.connect() as c:
            c.execute(text(f'CREATE SCHEMA "{schema}"'))
        created.append(schema)
        url: URL = base_url.update_query_dict({"options": f"-csearch_path={schema}"})
        engine = create_engine(url)
        engines.append(engine)
        return engine

    try:
        empty, current, *_ = _check_four_states(make)
        # Each tenant is read through its own search_path, not its neighbour's.
        assert schema_status(empty).current is None
        assert schema_status(current).current == head_revision()
    finally:
        for e in engines:
            e.dispose()
        with admin.connect() as c:
            for schema in created:
                c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
