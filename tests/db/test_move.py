"""Copying a whole civex database from one engine to another.

SQLite -> SQLite runs everywhere; the PostgreSQL round trip needs
CIVEX_TEST_POSTGRES_URL (a scratch database, see test_search_vector_trigger.py)
and is skipped otherwise.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine

from civex.context import AppContext
from civex.db.engine import enable_sqlite_foreign_keys
from civex.db.migrate import ensure_schema_current
from civex.db.models import AiUsageEvent, Record
from civex.db.move import (
    MoveCancelled,
    Progress,
    app_tables,
    copy_database,
    is_empty,
    row_counts,
)

_PG_URL = os.environ.get("CIVEX_TEST_POSTGRES_URL")


def _sqlite(path: Path) -> Engine:
    engine = enable_sqlite_foreign_keys(create_engine(f"sqlite:///{path}"))
    ensure_schema_current(engine)
    return engine


@pytest.fixture()
def populated(ctx: AppContext, make_schema, make_collection) -> Engine:
    """A source database with a three-level schema hierarchy, references, a
    reference list and datetimes -- everything a copy has to carry."""
    make_schema("patient", fields=[("name", "string")])
    make_schema("encounter", fields=[("seen", "datetime"), ("who", "reference")])
    make_schema("cohort", fields=[("members", "reference_list")])
    make_schema("recording", fields=[("rate", "integer")], parent="encounter")
    make_schema("selection", fields=[("label", "string")], parent="recording")
    make_schema("scan", fields=[("doc", "file")])
    make_collection("study")
    patients = [
        ctx.record_svc.add("study", "patient", {"name": f"p{i}"}).id for i in range(30)
    ]
    for i in range(10):
        enc = ctx.record_svc.add(
            "study",
            "encounter",
            {"seen": "2024-03-01T10:00:00+00:00", "who": str(patients[i])},
        )
        rec = ctx.record_svc.add(
            "study", "recording", {"rate": 48000 + i}, parent_record_id=str(enc.id)
        )
        for j in range(3):
            ctx.record_svc.add(
                "study", "selection", {"label": f"s{j}"}, parent_record_id=str(rec.id)
            )
    # A batch with an audit row in it, so the move is tried against both.
    with ctx.history_svc.batch("import", "cohorts.csv"):
        ctx.record_svc.add(
            "study", "cohort", {"members": [str(p) for p in patients[:5]]}
        )

    # The remaining tables, so a copy is checked against every one of them.
    ctx.dataset_svc.update(
        "study",
        schemas=["patient", "encounter", "cohort", "recording", "selection", "scan"],
    )
    ctx.view_svc.create("patient", "everyone", columns=["name"])
    stored = ctx.file_svc.store_bytes(b"hello", "hello.txt")
    ctx.record_svc.add("study", "scan", {"doc": stored.to_dict()})
    job = ctx.job_svc.enqueue_manual("noop", ctx.record_svc.find("study", "patient")[0])
    ctx.commit()
    ctx.job_svc.mark_completed(
        job.id,
        step_executions=[
            {
                "step_id": "a",
                "plugin": "civex.noop",
                "status": "completed",
                "duration_seconds": 0.1,
            }
        ],
        affected_records=[
            {
                "record_id": str(patients[0]),
                "schema_name": "patient",
                "action": "updated",
            }
        ],
    )
    ctx.audit_svc.create_commit("first")
    ctx._session.add(
        AiUsageEvent(provider="anthropic", model="m", input_tokens=1, output_tokens=2)
    )
    _add_storage_transfer(ctx)
    ctx.commit()
    return ctx._session.get_bind()  # type: ignore[return-value]


def _add_storage_transfer(ctx: AppContext) -> None:
    """A finished transfer with everything a real one carries (its plan, a
    failure, a frozen source), so each JSON column is compared after a move."""
    import uuid
    from datetime import datetime, timezone

    from civex.domain.transfers import (
        TargetShare,
        TransferFailure,
        TransferPlan,
        TransferProgress,
        TransferRecord,
        TransferSpec,
    )
    from civex.repositories.local.transfer_repo import LocalTransferRepository

    now = datetime.now(timezone.utc)
    LocalTransferRepository(ctx._session).create(
        TransferRecord(
            id=str(uuid.uuid4()),
            kind="drain",
            status="completed",
            spec=TransferSpec(kind="drain", sources=["default"], targets=["archive"]),
            plan=TransferPlan(
                files=3,
                bytes=3000,
                targets=[TargetShare("archive", 3, 3000, 10**9)],
                warnings=["a warning"],
            ),
            progress=TransferProgress(
                files_total=3,
                files_done=2,
                files_failed=1,
                bytes_total=3000,
                bytes_done=2000,
                message="Finished",
            ),
            failures=[TransferFailure("ab" * 32, "default", "it is corrupt")],
            failures_total=1,
            control="pause",
            frozen={"default": "active"},
            created_at=now,
            started_at=now,
            finished_at=now,
        )
    )


def _table_dump(engine: Engine, table) -> list[str]:
    """Every row of a table (derived columns aside), comparable across engines."""
    from civex.db.move import SKIP_COLUMNS

    import json

    def canon(value):
        # JSONB doesn't keep key order; the data is the same either way.
        if isinstance(value, (dict, list)):
            return json.dumps(value, sort_keys=True, default=str)
        return value

    cols = [c for c in table.columns if c.name not in SKIP_COLUMNS]
    with engine.connect() as conn:
        return sorted(
            repr(tuple(canon(v) for v in r)) for r in conn.execute(select(*cols)).all()
        )


def _assert_same_data(a: Engine, b: Engine) -> None:
    for table in app_tables(a):
        assert _table_dump(a, table) == _table_dump(b, table), f"{table.name} differs"


def _records(engine: Engine) -> dict:
    with engine.connect() as conn:
        return {
            r.id: (r.dataset_id, r.schema_id, r.parent_record_id, r.data, r.created_at)
            for r in conn.execute(
                select(
                    Record.id,
                    Record.dataset_id,
                    Record.schema_id,
                    Record.parent_record_id,
                    Record.data,
                    Record.created_at,
                )
            )
        }


def test_copy_carries_every_row_and_verifies(populated: Engine, tmp_path: Path):
    target = _sqlite(tmp_path / "target.db")
    assert is_empty(target)

    result = copy_database(populated, target)

    assert result.verified, result.problems
    assert row_counts(target) == row_counts(populated)
    assert not is_empty(target)
    assert _records(target) == _records(populated)
    # Rows derived from data come across too, not re-derived or dropped.
    assert (
        result.counts["record_references"]
        == row_counts(populated)["record_references"]
        > 0
    )


def test_progress_reports_rows_and_phases(populated: Engine, tmp_path: Path):
    seen: list[Progress] = []
    copy_database(
        populated,
        _sqlite(tmp_path / "t.db"),
        progress=lambda p: seen.append(Progress(**p.__dict__)),
    )

    assert [p.phase for p in seen][0] == "copy"
    assert {"copy", "verify", "finalize"} <= {p.phase for p in seen}
    last_copy = [p for p in seen if p.phase == "copy"][-1]
    assert last_copy.rows_done == last_copy.rows_total > 0
    assert last_copy.tables_done == last_copy.tables_total
    assert "records" in {p.table for p in seen}


def test_a_failed_copy_leaves_the_target_empty(
    populated: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import civex.db.move as move

    target = _sqlite(tmp_path / "t.db")
    real = move._copy_table
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 5:
            raise RuntimeError("disk on fire")
        return real(*a, **kw)

    monkeypatch.setattr(move, "_copy_table", flaky)
    with pytest.raises(RuntimeError, match="disk on fire"):
        copy_database(populated, target)

    assert is_empty(target)  # nothing half-copied to clean up


def test_cancel_stops_the_copy_and_leaves_the_target_empty(
    populated: Engine, tmp_path: Path
):
    target = _sqlite(tmp_path / "t.db")
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(MoveCancelled):
        copy_database(populated, target, cancel=cancel)

    assert is_empty(target)


def test_verification_catches_a_copy_that_does_not_match(
    populated: Engine, tmp_path: Path
):
    target = _sqlite(tmp_path / "t.db")

    def lose_a_record(p: Progress) -> None:
        if p.phase == "verify":
            with target.begin() as conn:
                conn.execute(
                    text(
                        "DELETE FROM records WHERE id = (SELECT id FROM records "
                        "WHERE parent_record_id IS NOT NULL AND id NOT IN "
                        "(SELECT parent_record_id FROM records "
                        "WHERE parent_record_id IS NOT NULL) LIMIT 1)"
                    )
                )

    result = copy_database(populated, target, progress=lose_a_record)

    assert not result.verified
    assert any("records" in p for p in result.problems)


def test_verification_catches_a_changed_value(populated: Engine, tmp_path: Path):
    target = _sqlite(tmp_path / "t.db")

    def corrupt(p: Progress) -> None:
        if p.phase == "verify":
            with target.begin() as conn:
                conn.execute(text("UPDATE records SET data = '{}'"))

    result = copy_database(populated, target, progress=corrupt, sample=1000)

    assert not result.verified
    assert any("differs" in p for p in result.problems)


def test_memory_stays_flat_however_large_the_database(tmp_path: Path):
    """Rows are streamed and written in capped batches, so peak memory is a
    few batches' worth -- not the size of the data being moved."""
    import tracemalloc
    import uuid
    from datetime import datetime, timezone

    from civex.db.models import Dataset, Schema

    source = _sqlite(tmp_path / "big.db")
    now = datetime.now(timezone.utc)
    ds, sch = Dataset(name="d"), Schema(name="s")
    with source.begin() as conn:
        conn.execute(
            Dataset.__table__.insert(),
            [
                {
                    "id": (d := uuid.uuid4()),
                    "name": "d",
                    "created_at": now,
                    "scope": "local",
                }
            ],
        )
        conn.execute(
            Schema.__table__.insert(),
            [
                {
                    "id": (s_ := uuid.uuid4()),
                    "name": "s",
                    "created_at": now,
                }
            ],
        )
        blob = "x" * 3000  # ~3 KB of JSON per record
        for start in range(0, 24_000, 2000):
            conn.execute(
                Record.__table__.insert(),
                [
                    {
                        "id": uuid.uuid4(),
                        "dataset_id": d,
                        "schema_id": s_,
                        "data": {"k": blob, "n": i},
                        "created_at": now,
                        "updated_at": now,
                    }
                    for i in range(start, start + 2000)
                ],
            )
    data_bytes = 24_000 * 3000  # ~72 MB, which must never all be held at once

    target = _sqlite(tmp_path / "copy.db")
    tracemalloc.start()
    result = copy_database(source, target, sample=10)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert result.verified, result.problems
    assert row_counts(target)["records"] == 24_000
    assert peak < data_bytes / 2, (
        f"peak {peak / 1e6:.0f} MB for {data_bytes / 1e6:.0f} MB of data"
    )


def test_tables_are_copied_parents_first(populated: Engine, tmp_path: Path):
    """The target enforces foreign keys, so a child row landing before its
    parent would have failed the copy outright."""
    target = _sqlite(tmp_path / "t.db")
    names = [t.name for t in app_tables(target)]
    assert names.index("schemas") < names.index("records")
    assert names.index("datasets") < names.index("records")
    assert copy_database(populated, target).verified


@pytest.mark.skipif(not _PG_URL, reason="set CIVEX_TEST_POSTGRES_URL to run")
def test_round_trip_through_postgres(populated: Engine, tmp_path: Path):
    assert _PG_URL
    pg = create_engine(_PG_URL)
    with pg.begin() as conn:  # a clean slate in the scratch database
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    ensure_schema_current(pg)

    to_pg = copy_database(populated, pg)
    assert to_pg.verified, to_pg.problems
    assert row_counts(pg) == row_counts(populated)
    with pg.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM records WHERE search_vector IS NOT NULL")
            ).scalar_one()
            > 0
        )  # the trigger filled it; the copy didn't try to

    back = _sqlite(tmp_path / "back.db")
    to_sqlite = copy_database(pg, back)
    assert to_sqlite.verified, to_sqlite.problems
    assert _records(back) == _records(populated)
    _assert_same_data(populated, pg)  # every table, both directions
    _assert_same_data(populated, back)


# ---------------------------------------------------------------------------
# Guards against the copier drifting from the schema as civex evolves.
#
# The copier is generic -- it walks `Base.metadata` -- so a new table or column
# is picked up on its own. What these tests add is that a *new* table can't go
# unexercised, and that anything needing special handling gets noticed.
# ---------------------------------------------------------------------------

# Tables the realistic fixture above leaves empty. Adding a table to civex means
# either populating it in `populated` (preferred: then every column of it is
# compared after a copy) or listing it here on purpose.
UNPOPULATED: set[str] = set()


def test_every_table_is_populated_by_the_fixture_or_excluded_on_purpose(
    populated: Engine,
):
    empty = {name for name, n in row_counts(populated).items() if n == 0}
    assert empty <= UNPOPULATED, (
        f"{sorted(empty - UNPOPULATED)} have no rows in the `populated` fixture, so a "
        "database move is never tested against them. Populate them there (or add "
        "them to UNPOPULATED, knowingly)."
    )
    assert UNPOPULATED <= set(row_counts(populated)), "stale name in UNPOPULATED"


def test_every_row_of_every_table_survives_a_copy(populated: Engine, tmp_path: Path):
    """Not just records: every column of every table is compared, so a new
    column that doesn't survive the trip fails here."""
    target = _sqlite(tmp_path / "t.db")
    assert copy_database(populated, target).verified
    _assert_same_data(populated, target)


def test_the_set_of_self_referencing_foreign_keys_is_the_one_the_copier_orders():
    """Rows that point at other rows of their own table must be inserted
    parents-first. `_copy_table` does that for exactly these two; a new
    self-referencing table needs the same treatment, so this fails to say so."""
    from sqlalchemy import ForeignKeyConstraint

    from civex.db.models import Base

    found = set()
    for table in Base.metadata.tables.values():
        for fk in table.constraints:
            if isinstance(fk, ForeignKeyConstraint) and fk.referred_table is table:
                found.add(table.name)
    assert found == {"schemas", "records"}, (
        f"self-referencing tables are now {sorted(found)}: teach "
        "civex.db.move._copy_table to insert their parents first"
    )


def test_no_table_dependency_cycles():
    """`sorted_tables` can't order a cycle (it warns and guesses), and the
    copier relies on that order."""
    import warnings

    from civex.db.models import Base

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        Base.metadata.sorted_tables
