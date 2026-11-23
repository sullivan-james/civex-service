"""b5d8f1a3c6e2: PostgreSQL `records` is hash-partitioned by id and `audit_log`
range-partitioned by month, for new and for populated databases, and SQLite is
left alone.

Each test works in its own PostgreSQL schema (search_path), the way civex-hub
lays out one repository per schema. Needs CIVEX_TEST_POSTGRES_URL (see
test_search_vector_trigger.py); the SQLite and pure-Python tests always run.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civex.db import partitioning
from civex.db.migrate import ensure_audit_partitions, ensure_schema_current
from civex.db.models import AuditLog, Dataset, Record, Schema
from civex.config import PartitionLayout

_PG_URL = os.environ.get("CIVEX_TEST_POSTGRES_URL")
_PRE = "e4b9c1a7d2f6"  # the revision before partitioning

pytestmark = pytest.mark.xdist_group("postgres_scratch")  # one shared scratch server

needs_pg = pytest.mark.skipif(
    not _PG_URL,
    reason="set CIVEX_TEST_POSTGRES_URL to a scratch PostgreSQL DB to run this test",
)


def _alembic() -> Config:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/civex/db/migrations"))
    return cfg


@pytest.fixture()
def pg_schema():
    """An engine whose search_path is a fresh schema (as civex-hub lays out one
    repository), in a database made for the test so nothing here touches the
    scratch database other tests share."""
    name = f"civex_part_{uuid.uuid4().hex[:12]}"
    admin = create_engine(_PG_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    base = _PG_URL.rsplit("/", 1)[0] + f"/{name}"
    setup = create_engine(base, isolation_level="AUTOCOMMIT")
    with setup.connect() as c:
        c.execute(text("CREATE SCHEMA repo_t"))
    setup.dispose()
    engine = create_engine(base, connect_args={"options": "-csearch_path=repo_t"})
    yield engine
    engine.dispose()
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture()
def pg_database():
    """An engine on a database of its own (for a test that runs alembic
    downgrades, which must not share the scratch database with other tests)."""
    name = f"civex_part_{uuid.uuid4().hex[:12]}"
    admin = create_engine(_PG_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(_PG_URL.rsplit("/", 1)[0] + f"/{name}")
    yield engine
    engine.dispose()
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


def _kind(engine: Engine, table: str) -> str:
    with engine.connect() as c:
        return c.execute(
            text("SELECT relkind FROM pg_class WHERE oid = to_regclass(:n)"),
            {"n": table},
        ).scalar_one()


def _migrate_to_pre(engine: Engine) -> None:
    cfg = _alembic()
    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, _PRE)
        conn.commit()


def _index_names(engine: Engine, table: str) -> set[str]:
    with engine.connect() as c:
        return {
            r[0]
            for r in c.execute(
                text(
                    "SELECT i.relname FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid "
                    "WHERE x.indrelid = to_regclass(:n)"
                ),
                {"n": table},
            )
        }


@needs_pg
def test_a_new_database_is_partitioned(pg_schema: Engine) -> None:
    ensure_schema_current(pg_schema)
    assert _kind(pg_schema, "records") == "p"
    assert _kind(pg_schema, "audit_log") == "p"
    with pg_schema.connect() as c:
        assert len(partitioning.partitions_of(c, "records")) == 8
        months = partitioning.partitions_of(c, "audit_log")
    assert "audit_log_default" in months
    now = datetime.now(timezone.utc)
    assert f"audit_log_y{now.year}m{now.month:02d}" in months
    # everything older than this month, this month plus two ahead, the default
    assert "audit_log_early" in months
    assert len(months) == 5


@needs_pg
def test_the_layout_can_be_switched_off(pg_schema: Engine) -> None:
    ensure_schema_current(
        pg_schema, PartitionLayout(records_partitions=1, audit_monthly=False)
    )
    assert _kind(pg_schema, "records") == "r"
    assert _kind(pg_schema, "audit_log") == "r"


@needs_pg
def test_modulus_is_configurable(pg_schema: Engine) -> None:
    ensure_schema_current(pg_schema, PartitionLayout(records_partitions=4))
    with pg_schema.connect() as c:
        assert len(partitioning.partitions_of(c, "records")) == 4


@needs_pg
def test_orm_writes_and_reads_through_the_partitioned_tables(
    pg_schema: Engine,
) -> None:
    ensure_schema_current(pg_schema)
    with Session(pg_schema) as s:
        ds, sc = Dataset(name="d"), Schema(name="s")
        s.add_all([ds, sc])
        s.flush()
        parent = Record(dataset_id=ds.id, schema_id=sc.id, data={"a": "hello world"})
        s.add(parent)
        s.flush()
        child = Record(
            dataset_id=ds.id,
            schema_id=sc.id,
            parent_record_id=parent.id,
            data={"a": "child"},
        )
        s.add(child)
        s.add(
            AuditLog(
                action="create", entity_type="record", entity_id=parent.id, new_data={}
            )
        )
        s.commit()
        assert s.get(Record, parent.id).data == {"a": "hello world"}
        parent.data = {"a": "changed words"}
        s.commit()
        # the search-vector trigger still fires on the partitioned table
        assert (
            s.execute(
                text(
                    "SELECT search_vector @@ to_tsquery('simple', 'changed') "
                    "FROM records WHERE id = :i"
                ),
                {"i": parent.id},
            ).scalar_one()
            is True
        )
        assert s.query(AuditLog).count() == 1


@needs_pg
def test_foreign_keys_still_hold_on_a_partitioned_records(pg_schema: Engine) -> None:
    ensure_schema_current(pg_schema)
    with Session(pg_schema) as s:
        ds, sc = Dataset(name="d"), Schema(name="s")
        s.add_all([ds, sc])
        s.flush()
        rec = Record(dataset_id=ds.id, schema_id=sc.id, data={})
        s.add(rec)
        s.flush()
        s.execute(
            text(
                "INSERT INTO record_notes (id, record_id, body, created_at) "
                "VALUES (:i, :r, 'n', now())"
            ),
            {"i": uuid.uuid4(), "r": rec.id},
        )
        s.commit()
        # a child pointing at a parent in another collection is refused at commit
        other = Dataset(name="other")
        s.add(other)
        s.flush()
        s.add(
            Record(
                dataset_id=other.id,
                schema_id=sc.id,
                parent_record_id=rec.id,
                data={},
            )
        )
        with pytest.raises(Exception, match="fk_records_parent_same_dataset"):
            s.commit()
        s.rollback()
        # a note for a record that does not exist is refused
        with pytest.raises(Exception, match="record_notes_record_id_fkey"):
            s.execute(
                text(
                    "INSERT INTO record_notes (id, record_id, body, created_at) "
                    "VALUES (:i, :r, 'n', now())"
                ),
                {"i": uuid.uuid4(), "r": uuid.uuid4()},
            )
        s.rollback()
        # deleting the record cascades to its notes
        s.execute(text("DELETE FROM records WHERE id = :i"), {"i": rec.id})
        assert s.execute(text("SELECT count(*) FROM record_notes")).scalar_one() == 0


@needs_pg
def test_populated_database_keeps_its_data_indexes_and_foreign_keys(
    pg_schema: Engine,
) -> None:
    _migrate_to_pre(pg_schema)
    assert _kind(pg_schema, "records") == "r"
    ds, sc = uuid.uuid4(), uuid.uuid4()
    ids = [uuid.uuid4() for _ in range(300)]
    # old audit history across years, plus a future-dated entry
    stamps = [
        datetime(2019, 3, 4, tzinfo=timezone.utc),
        datetime.now(timezone.utc) - timedelta(days=70),
        datetime.now(timezone.utc),
        datetime(2040, 1, 1, tzinfo=timezone.utc),
    ]
    with pg_schema.begin() as c:
        c.execute(
            text("INSERT INTO schemas (id, name, created_at) VALUES (:i, 's', now())"),
            {"i": sc},
        )
        c.execute(
            text("INSERT INTO datasets (id, name, created_at) VALUES (:i, 'd', now())"),
            {"i": ds},
        )
        for n, rid in enumerate(ids):
            c.execute(
                text(
                    "INSERT INTO records (id, dataset_id, schema_id, parent_record_id, "
                    "data, created_at, updated_at, deleted_at) VALUES "
                    "(:i, :d, :s, :p, CAST(:data AS jsonb), now(), now(), :del)"
                ),
                {
                    "i": rid,
                    "d": ds,
                    "s": sc,
                    "p": ids[0] if n % 10 == 1 else None,
                    "data": json.dumps({"f": f"word{n}"}),
                    "del": datetime.now(timezone.utc) if n % 50 == 7 else None,
                },
            )
        c.execute(
            text(
                "INSERT INTO record_notes (id, record_id, body, created_at) "
                "VALUES (:i, :r, 'n', now())"
            ),
            {"i": uuid.uuid4(), "r": ids[5]},
        )
        for stamp in stamps:
            c.execute(
                text(
                    "INSERT INTO audit_log (id, action, entity_type, entity_id, "
                    "timestamp, hub_seq) VALUES (:i, 'create', 'record', :e, :t, :h)"
                ),
                {"i": uuid.uuid4(), "e": ids[0], "t": stamp, "h": stamps.index(stamp)},
            )
    before_idx = {t: _index_names(pg_schema, t) for t in ("records", "audit_log")}
    with pg_schema.connect() as c:
        fks_before = {
            r[0]
            for r in c.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE contype = 'f' AND conparentid = 0 AND "
                    "(confrelid = to_regclass('records') OR conrelid = to_regclass('records') "
                    "OR conrelid = to_regclass('audit_log'))"
                )
            )
        }

    ensure_schema_current(pg_schema)

    assert _kind(pg_schema, "records") == "p"
    assert _kind(pg_schema, "audit_log") == "p"
    with pg_schema.connect() as c:
        assert c.execute(text("SELECT count(*) FROM records")).scalar_one() == 300
        assert {r[0] for r in c.execute(text("SELECT id FROM records"))} == set(ids)
        assert (
            c.execute(
                text("SELECT count(*) FROM records WHERE deleted_at IS NOT NULL")
            ).scalar_one()
            == 6
        )
        # rows are spread over the partitions
        spread = c.execute(
            text("SELECT count(DISTINCT tableoid) FROM records")
        ).scalar_one()
        assert spread > 1
        # nothing was lost from audit_log; old and far-future rows are kept
        assert c.execute(text("SELECT count(*) FROM audit_log")).scalar_one() == 4
        in_default = c.execute(
            text("SELECT count(*) FROM audit_log_default")
        ).scalar_one()
        assert in_default == 1  # the year-2040 entry
        early = c.execute(text("SELECT count(*) FROM audit_log_early")).scalar_one()
        assert early == 1  # 2019, older than the monthly backfill window
        # the foreign keys are all back, validated, under the same names
        fks_after = {
            r[0]
            for r in c.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE contype = 'f' AND conparentid = 0 AND convalidated AND "
                    "(confrelid = to_regclass('records') OR conrelid = to_regclass('records') "
                    "OR conrelid = to_regclass('audit_log'))"
                )
            )
        }
        assert fks_after == fks_before
        # the first two have a child pointing at ids[0]: still enforced
        assert (
            c.execute(
                text("SELECT count(*) FROM records WHERE parent_record_id = :p"),
                {"p": ids[0]},
            ).scalar_one()
            == 30
        )
    after_idx = {t: _index_names(pg_schema, t) for t in ("records", "audit_log")}
    # (an index a later migration adds is not part of what the conversion keeps)
    after_idx["audit_log"] -= {"ix_audit_log_seeding"}
    # same index names, except the audit_log primary key which now includes
    # the partition key but keeps its name
    assert after_idx == before_idx
    with Session(pg_schema) as s:
        with pytest.raises(Exception):
            s.execute(
                text(
                    "INSERT INTO record_notes (id, record_id, body, created_at) "
                    "VALUES (:i, :r, 'n', now())"
                ),
                {"i": uuid.uuid4(), "r": uuid.uuid4()},
            )
        s.rollback()
        # the trigger came across
        s.execute(
            text("UPDATE records SET data = CAST(:d AS jsonb) WHERE id = :i"),
            {"d": json.dumps({"f": "zebra"}), "i": ids[3]},
        )
        found = (
            s.execute(
                text(
                    "SELECT id FROM records WHERE search_vector @@ to_tsquery('simple','zebra')"
                )
            )
            .scalars()
            .all()
        )
        assert found == [ids[3]]


@needs_pg
def test_downgrade_restores_plain_tables_with_the_data(pg_database: Engine) -> None:
    ensure_schema_current(pg_database)
    with Session(pg_database) as s:
        ds, sc = Dataset(name="d"), Schema(name="s")
        s.add_all([ds, sc])
        s.flush()
        rec = Record(dataset_id=ds.id, schema_id=sc.id, data={"a": "x"})
        s.add(rec)
        s.flush()
        s.add(
            AuditLog(
                action="create", entity_type="record", entity_id=rec.id, new_data={}
            )
        )
        s.commit()
    with pg_database.begin() as conn:
        partitioning.unpartition_records(conn)
        partitioning.unpartition_audit_log(conn)
    assert _kind(pg_database, "records") == "r"
    assert _kind(pg_database, "audit_log") == "r"
    with pg_database.connect() as c:
        assert c.execute(text("SELECT count(*) FROM records")).scalar_one() == 1
        assert c.execute(text("SELECT count(*) FROM audit_log")).scalar_one() == 1
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM pg_constraint WHERE contype = 'p' AND "
                    "conrelid = to_regclass('audit_log') AND conkey = ARRAY[1]::int2[]"
                )
            ).scalar_one()
            == 1
        )


@needs_pg
def test_future_audit_partitions_are_created_and_idempotent(pg_schema: Engine) -> None:
    ensure_schema_current(pg_schema)
    now = datetime.now(timezone.utc)
    later = now + timedelta(days=200)
    created = ensure_audit_partitions(pg_schema, months_ahead=8, now=now)
    assert created  # months 3..8 ahead
    assert len(created) == 6
    with pg_schema.connect() as c:
        names = partitioning.partitions_of(c, "audit_log")
    assert f"audit_log_y{later.year}m{later.month:02d}" in names
    assert ensure_audit_partitions(pg_schema, months_ahead=8, now=now) == []


@needs_pg
def test_history_with_old_timestamps_lands_in_early_not_default(
    pg_schema: Engine,
) -> None:
    """A device pushing years of entries to a new repository."""
    ensure_schema_current(pg_schema)
    with pg_schema.begin() as c:
        for years in (1, 2, 3):
            c.execute(
                text(
                    "INSERT INTO audit_log (id, action, entity_type, entity_id, timestamp) "
                    "VALUES (:i, 'create', 'record', :e, now() - make_interval(years => :y))"
                ),
                {"i": uuid.uuid4(), "e": uuid.uuid4(), "y": years},
            )
        assert c.execute(text("SELECT count(*) FROM audit_log_early")).scalar_one() == 3
        assert (
            c.execute(text("SELECT count(*) FROM audit_log_default")).scalar_one() == 0
        )


@needs_pg
def test_rows_that_arrived_before_their_month_existed_are_moved_in(
    pg_schema: Engine,
) -> None:
    ensure_schema_current(pg_schema)
    far = datetime.now(timezone.utc) + timedelta(days=180)
    with pg_schema.begin() as c:
        c.execute(
            text(
                "INSERT INTO audit_log (id, action, entity_type, entity_id, timestamp) "
                "VALUES (:i, 'create', 'record', :e, :t)"
            ),
            {"i": uuid.uuid4(), "e": uuid.uuid4(), "t": far},
        )
        assert (
            c.execute(text("SELECT count(*) FROM audit_log_default")).scalar_one() == 1
        )
    created = ensure_audit_partitions(pg_schema, months_ahead=8)
    month = f"audit_log_y{far.year}m{far.month:02d}"
    assert month in created
    with pg_schema.connect() as c:
        assert (
            c.execute(text("SELECT count(*) FROM audit_log_default")).scalar_one() == 0
        )
        assert c.execute(text(f"SELECT count(*) FROM {month}")).scalar_one() == 1
        assert c.execute(text("SELECT count(*) FROM audit_log")).scalar_one() == 1


@needs_pg
def test_estimated_count_sums_the_partitions(pg_schema: Engine) -> None:
    from civex.domain.query import ResolvedQuery
    from civex.repositories.local.record_repo import LocalRecordRepository

    ensure_schema_current(pg_schema)
    with Session(pg_schema) as s:
        ds, sc = Dataset(name="d"), Schema(name="s")
        s.add_all([ds, sc])
        s.flush()
        s.execute(
            text(
                "INSERT INTO records (id, dataset_id, schema_id, data, created_at, updated_at) "
                "SELECT gen_random_uuid(), :d, :s, '{}', now(), now() FROM generate_series(1, 2000)"
            ),
            {"d": ds.id, "s": sc.id},
        )
        s.commit()
    with pg_schema.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text("ANALYZE records"))
    with Session(pg_schema) as s:
        repo = LocalRecordRepository(s, is_postgres=True)
        count, estimated = repo.estimate_count(ResolvedQuery())
        assert estimated and 1900 <= count <= 2100


def _spec(kind: str = "text"):
    from civex.domain.field_index import FieldIndexSpec

    return FieldIndexSpec(field_id=uuid.uuid4(), schema_id=uuid.uuid4(), kind=kind)


def _index_state(engine: Engine, name: str) -> tuple[str, bool, int, int]:
    """(relkind, valid, partitions holding a child of it, extended statistics)."""
    with engine.connect() as c:
        kind, valid = c.execute(
            text(
                "SELECT c.relkind, i.indisvalid FROM pg_class c "
                "JOIN pg_index i ON i.indexrelid = c.oid "
                "WHERE c.oid = to_regclass(:n)"
            ),
            {"n": name},
        ).one()
        children = c.execute(
            text("SELECT count(*) FROM pg_inherits WHERE inhparent = to_regclass(:n)"),
            {"n": name},
        ).scalar_one()
        stats = c.execute(
            text("SELECT count(*) FROM pg_statistic_ext WHERE stxname = :n"),
            {"n": f"{name}_stats"},
        ).scalar_one()
        return kind, valid, children, stats


@needs_pg
def test_managed_field_indexes_are_partitioned_indexes_on_the_parent(
    pg_schema: Engine,
) -> None:
    from civex.db import field_indexes, statistics

    ensure_schema_current(pg_schema)
    spec = _spec("number")
    with pg_schema.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        field_indexes.create(c, spec)
        assert spec.name in field_indexes.existing(c)
        statistics.refresh(c, statistics.INDEX_BUILT)
    # a partitioned index ('I'), valid, with a child on each of the 8 partitions
    assert _index_state(pg_schema, spec.name) == ("I", True, 8, 1)
    # building it again is harmless, and dropping removes it and its statistics
    with pg_schema.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        field_indexes.create(c, spec)
        field_indexes.drop(c, spec.name)
        assert spec.name not in field_indexes.existing(c)
    with pg_schema.connect() as c:
        assert (
            c.execute(text("SELECT to_regclass(:n)"), {"n": spec.name}).scalar_one()
            is None
        )


@needs_pg
def test_conversion_recreates_managed_field_indexes_and_their_statistics(
    pg_schema: Engine,
) -> None:
    from civex.db import field_indexes

    _migrate_to_pre(pg_schema)
    spec = _spec()
    with pg_schema.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        field_indexes.create(c, spec)
    assert _index_state(pg_schema, spec.name)[0] == "i"  # a plain index before
    ensure_schema_current(pg_schema)
    assert _index_state(pg_schema, spec.name) == ("I", True, 8, 1)
    with pg_schema.connect() as c:
        assert spec.name in field_indexes.existing(c)


@needs_pg
def test_grants_and_storage_settings_survive_the_rebuild(pg_schema: Engine) -> None:
    _migrate_to_pre(pg_schema)
    with pg_schema.begin() as c:
        c.execute(text("GRANT SELECT ON records TO PUBLIC"))
        c.execute(
            text("ALTER TABLE records SET (autovacuum_vacuum_scale_factor = 0.01)")
        )
    ensure_schema_current(pg_schema)
    with pg_schema.connect() as c:
        assert (
            "=r/"
            in c.execute(
                text(
                    "SELECT relacl::text FROM pg_class WHERE oid = to_regclass('records')"
                )
            ).scalar_one()
        )
        opts = c.execute(
            text(
                "SELECT reloptions::text FROM pg_class "
                "WHERE oid = to_regclass('records_p3')"
            )
        ).scalar_one()
        assert "autovacuum_vacuum_scale_factor=0.01" in opts


@needs_pg
def test_row_level_security_is_refused_not_dropped(pg_schema: Engine) -> None:
    _migrate_to_pre(pg_schema)
    with pg_schema.begin() as c:
        c.execute(text("ALTER TABLE records ENABLE ROW LEVEL SECURITY"))
    with pytest.raises(RuntimeError, match="row-level security"):
        ensure_schema_current(pg_schema)
    assert _kind(pg_schema, "records") == "r"  # rolled back, as it was


@needs_pg
def test_daily_top_up_creates_missing_months_once_a_day(pg_schema: Engine) -> None:
    ensure_schema_current(pg_schema)
    later = datetime.now(timezone.utc) + timedelta(days=62)
    name = f"audit_log_y{later.year}m{later.month:02d}"

    def drop() -> None:
        with pg_schema.begin() as c:
            c.execute(text(f"DROP TABLE IF EXISTS {name}"))

    def exists() -> bool:
        with pg_schema.connect() as c:
            return name in partitioning.partitions_of(c, "audit_log")

    partitioning._topped_up.pop(pg_schema, None)
    drop()
    partitioning.ensure_audit_partitions_daily(pg_schema)
    assert exists()
    drop()
    partitioning.ensure_audit_partitions_daily(pg_schema)  # same day: not again
    assert not exists()
    partitioning._topped_up.pop(pg_schema, None)  # "tomorrow"
    partitioning.ensure_audit_partitions_daily(pg_schema)
    assert exists()


def test_sqlite_keeps_plain_tables(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'p.db'}")
    ensure_schema_current(engine)
    with engine.connect() as c:
        sql = {
            r[0]: r[1]
            for r in c.execute(
                text("SELECT name, sql FROM sqlite_master WHERE type = 'table'")
            )
        }
        assert "PARTITION" not in sql["records"].upper()
        assert "PARTITION" not in sql["audit_log"].upper()
        assert not [n for n in sql if n.startswith(("records_p", "audit_log_y"))]
    assert ensure_audit_partitions(engine) == []
    assert partitioning.partition_records(engine.connect(), 8) is False


def test_layout_rejects_values_that_are_not_counts() -> None:
    from civex.config import DBConfig
    from civex.domain.exceptions import ConfigError

    for bad in ("eight", "-2", "true"):
        with pytest.raises(ConfigError, match="CIVEX_RECORDS_PARTITIONS"):
            PartitionLayout.from_env({"CIVEX_RECORDS_PARTITIONS": bad})
    assert PartitionLayout.for_config(DBConfig(url="x", records_partitions=4), {}) == (
        PartitionLayout(records_partitions=4)
    )
    # the [db] section wins over the environment
    env = {"CIVEX_RECORDS_PARTITIONS": "16"}
    assert PartitionLayout.for_config(DBConfig(url="x"), env).records_partitions == 16
    assert (
        PartitionLayout.for_config(
            DBConfig(url="x", records_partitions=0), env
        ).records_partitions
        == 0
    )


def test_layout_from_environment() -> None:
    assert PartitionLayout.from_env({}) == PartitionLayout()
    assert PartitionLayout.from_env({"CIVEX_RECORDS_PARTITIONS": "16"}) == (
        PartitionLayout(records_partitions=16)
    )
    for off in ("off", "0", "1", "none"):
        assert (
            PartitionLayout.from_env(
                {"CIVEX_RECORDS_PARTITIONS": off}
            ).records_partitions
            < 2
        )
    assert not PartitionLayout.from_env({"CIVEX_AUDIT_PARTITIONS": "off"}).audit_monthly


# --- the public conversion API (civex.db.migrate) ------------------------------


@needs_pg
def test_a_plain_records_table_converts_through_the_public_api(
    pg_schema: Engine,
) -> None:
    from civex.db.migrate import convert_records_partitions, records_partitioning

    ensure_schema_current(pg_schema, PartitionLayout(records_partitions=1))
    assert records_partitioning(pg_schema).partitioned is False
    assert convert_records_partitions(pg_schema, 1).partitioned is False  # < 2: no-op

    status = convert_records_partitions(pg_schema, 4)
    assert (status.supported, status.partitioned, status.partitions) == (True, True, 4)
    assert _kind(pg_schema, "records") == "p"
    # Already partitioned: left as it is, whatever count is asked for.
    assert convert_records_partitions(pg_schema, 8).partitions == 4


def test_the_conversion_api_reports_sqlite_as_unsupported(tmp_path: Path) -> None:
    from civex.db.migrate import convert_records_partitions, records_partitioning

    engine = create_engine(f"sqlite:///{tmp_path / 'c.db'}")
    ensure_schema_current(engine)
    status = records_partitioning(engine)
    assert (status.supported, status.partitioned, status.partitions) == (
        False,
        False,
        0,
    )
    assert convert_records_partitions(engine, 8) == status


@needs_pg
def test_converting_before_the_schema_exists_says_so(pg_schema: Engine) -> None:
    from civex.db.migrate import convert_records_partitions

    with pytest.raises(ValueError, match="ensure_schema_current"):
        convert_records_partitions(pg_schema, 4)
