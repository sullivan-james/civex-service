"""civex.db.migrate.ensure_schema_current: the three states every install can
be in the first time it connects (brand new / pre-Alembic legacy / already
migrated).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from civex.db.migrate import ensure_schema_current
from civex.db.models import Base


def _alembic_revision(engine) -> str | None:
    with engine.connect() as c:
        row = c.execute(text("select version_num from alembic_version")).fetchone()
        return row[0] if row else None


def test_fresh_project_ends_at_head_with_all_tables(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'new.db'}")
    ensure_schema_current(engine)

    tables = set(inspect(engine).get_table_names())
    assert {
        "schemas",
        "fields",
        "datasets",
        "records",
        "commits",
        "audit_log",
        "workflow_jobs",
    } <= tables
    assert _alembic_revision(engine) == "0001"


def test_legacy_db_is_stamped_not_replayed(tmp_path: Path) -> None:
    """A pre-Alembic install already has tables matching the baseline shape
    (the old ad hoc migration list kept it current on every connection) --
    replaying `create_table` against them would fail, so it must be stamped
    instead, and any existing data must survive untouched."""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(engine)
    with engine.connect() as c:
        assert "alembic_version" not in inspect(c).get_table_names()

    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO schemas (id, name, created_at) VALUES ('11111111-1111-1111-1111-111111111111', 'patient', '2024-01-01')"
            )
        )

    ensure_schema_current(engine)

    assert _alembic_revision(engine) == "0001"
    with engine.connect() as c:
        names = c.execute(text("select name from schemas")).fetchall()
    assert names == [("patient",)]


def test_already_migrated_db_is_a_noop(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'twice.db'}")
    ensure_schema_current(engine)
    ensure_schema_current(
        create_engine(f"sqlite:///{tmp_path / 'twice.db'}")
    )  # fresh engine object, cache miss
    assert _alembic_revision(engine) == "0001"


def test_repeated_call_on_same_engine_object_is_cached_noop(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'cached.db'}")
    ensure_schema_current(engine)
    ensure_schema_current(engine)  # in-process cache hit -- must not re-run and error
    assert _alembic_revision(engine) == "0001"
