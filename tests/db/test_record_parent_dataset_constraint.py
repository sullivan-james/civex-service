"""CIVEX-168: parent_record_id -> dataset_id is a functional dependency,
enforced at the DB layer by a composite FK (parent_record_id, dataset_id) ->
(records.id, records.dataset_id), not just by RecordService.add()'s explicit
check.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy import create_engine, text

from civex.db.engine import enable_sqlite_foreign_keys
from civex.db.migrate import ensure_schema_current


def test_repository_write_with_cross_dataset_parent_fails_at_db_layer(
    ctx, make_collection, make_schema
):
    """Going straight through the repository -- skipping RecordService.add()'s
    dataset_id equality check entirely -- must still be rejected by the DB."""
    ds1 = make_collection("ds1")
    ds2 = make_collection("ds2")
    make_schema("parent", fields=[])
    child_schema = make_schema("child", parent="parent")

    parent = ctx.record_svc._records.create(
        dataset_id=ds1.id, schema_id=child_schema.parent_id, data={}
    )
    ctx.commit()

    with pytest.raises(IntegrityError):
        ctx.record_svc._records.create(
            dataset_id=ds2.id,
            schema_id=child_schema.id,
            data={},
            parent_record_id=parent.id,
        )


def test_repository_write_with_matching_dataset_parent_succeeds(
    ctx, make_collection, make_schema
):
    ds1 = make_collection("ds1")
    make_schema("parent", fields=[])
    child_schema = make_schema("child", parent="parent")

    parent = ctx.record_svc._records.create(
        dataset_id=ds1.id, schema_id=child_schema.parent_id, data={}
    )
    ctx.commit()

    child = ctx.record_svc._records.create(
        dataset_id=ds1.id,
        schema_id=child_schema.id,
        data={},
        parent_record_id=parent.id,
    )
    ctx.commit()

    assert child.parent_record_id == parent.id


def test_migration_repairs_pre_existing_cross_dataset_parent_links(tmp_path) -> None:
    """A DB created before CIVEX-168 could already contain a child whose
    dataset_id disagrees with its parent's. Upgrading must detect and repair
    it (clear the dangling parent link) rather than failing opaquely when the
    new composite FK is added."""
    from pathlib import Path

    import uuid
    from datetime import datetime, timezone

    from alembic import command
    from alembic.config import Config
    from sqlalchemy.orm import Session

    from civex.db.models import Record

    db_path = tmp_path / "legacy.db"
    migrations_dir = Path(__file__).resolve().parents[2] / "src/civex/db/migrations"
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_dir))

    # Build the DB at the revision immediately before CIVEX-168's, so the old
    # single-column parent_record_id FK is in place but the new composite one
    # (and its data repair) isn't -- then seed a violation only that older
    # schema would allow. Seeded via Core against that revision's own column
    # set (not the ORM models, which reflect *current* head and would include
    # columns -- e.g. schemas.display_template -- that don't exist yet at this
    # revision).
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as c:
        cfg.attributes["connection"] = c
        command.upgrade(cfg, "f70228df9305")
        c.commit()

    # SQLAlchemy's Uuid type binds/stores as 32-char hex without dashes on
    # SQLite (see models.Schema.id etc., all plain `Mapped[uuid.UUID]`) --
    # seed with `.hex` so the migration's own Core queries (which go through
    # that same type) can find and update these rows by id.
    now = datetime.now(timezone.utc)
    ds1_id, ds2_id, sch_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    parent_id, bad_child_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO datasets (id, name, created_at) VALUES (:id, :name, :created_at)"
            ),
            [
                {"id": ds1_id.hex, "name": "ds1", "created_at": now},
                {"id": ds2_id.hex, "name": "ds2", "created_at": now},
            ],
        )
        c.execute(
            text(
                "INSERT INTO schemas (id, name, created_at) VALUES (:id, :name, :created_at)"
            ),
            {"id": sch_id.hex, "name": "sch", "created_at": now},
        )
        c.execute(
            text(
                "INSERT INTO records (id, dataset_id, schema_id, parent_record_id, data, created_at, updated_at) "
                "VALUES (:id, :dataset_id, :schema_id, :parent_record_id, :data, :created_at, :updated_at)"
            ),
            [
                {
                    "id": parent_id.hex,
                    "dataset_id": ds1_id.hex,
                    "schema_id": sch_id.hex,
                    "parent_record_id": None,
                    "data": "{}",
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": bad_child_id.hex,
                    "dataset_id": ds2_id.hex,
                    "schema_id": sch_id.hex,
                    "parent_record_id": parent_id.hex,
                    "data": "{}",
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )

    engine = enable_sqlite_foreign_keys(create_engine(f"sqlite:///{db_path}"))
    ensure_schema_current(engine)

    with engine.connect() as c:
        violations = c.execute(text("PRAGMA foreign_key_check")).fetchall()
        assert violations == []

    with Session(engine) as session:
        assert session.get(Record, bad_child_id).parent_record_id is None
