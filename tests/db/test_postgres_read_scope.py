"""PostgreSQL: a caller limited to some collections is served from the indexes.
The history rule probes `records` by key for each entry (never a scan of the
table, which `IN (subquery)` under OR becomes), and counting stops at a cap.
Requires CIVEX_TEST_POSTGRES_URL (see test_postgres_keyset.py)."""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import pytest
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from civex.db import read_scope
from civex.db.migrate import ensure_schema_current
from civex.db.models import AuditLog, Dataset, Record, Schema
from civex.domain.permissions import ReadScope
from civex.domain.query import ResolvedQuery
from civex.repositories.local import record_repo
from civex.repositories.local.record_repo import LocalRecordRepository

_PG_URL = os.environ.get("CIVEX_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.xdist_group("postgres_scratch"),
    pytest.mark.skipif(not _PG_URL, reason="set CIVEX_TEST_POSTGRES_URL"),
]

RECORDS = 30_000


@pytest.fixture()
def seeded():
    engine = create_engine(_PG_URL)
    ensure_schema_current(engine)
    with Session(engine) as s:
        shown = Dataset(name=f"shown-{uuid.uuid4().hex[:8]}")
        hidden = Dataset(name=f"hidden-{uuid.uuid4().hex[:8]}")
        schema = Schema(name=f"sch_{uuid.uuid4().hex[:8]}")
        s.add_all([shown, hidden, schema])
        s.flush()
        rows, entries = [], []
        for i in range(RECORDS):
            rid = uuid.uuid4()
            rows.append(
                {
                    "id": rid,
                    "dataset_id": shown.id if i % 3 == 0 else hidden.id,
                    "schema_id": schema.id,
                    "data": {"k": i},
                }
            )
            for action in ("create", "update"):
                entries.append(
                    {
                        "action": action,
                        "entity_type": "record",
                        "entity_id": rid,
                        "sync_state": "synced",
                    }
                )
        s.execute(insert(Record), rows)
        s.execute(insert(AuditLog), entries)
        s.execute(text("ANALYZE records"))
        s.execute(text("ANALYZE audit_log"))
        s.flush()
        yield s, shown, hidden, rows[0]["id"], rows[1]["id"]
        s.rollback()
    engine.dispose()


def _plan(session: Session, statement: Any) -> Any:
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    return json.loads(
        json.dumps(session.execute(text(f"EXPLAIN (FORMAT JSON) {sql}")).scalar())
    )[0]["Plan"]


def _seq_scans_of(plan: dict[str, Any], table: str) -> list[dict[str, Any]]:
    found = []
    # (`records` is partitioned: its leaves are records_p0, records_p1, ...)
    if plan.get("Node Type") == "Seq Scan" and str(
        plan.get("Relation Name", "")
    ).startswith(table):
        found.append(plan)
    for child in plan.get("Plans", []):
        found += _seq_scans_of(child, table)
    return found


def _restricted_history(session: Session, shown: Dataset, entity: uuid.UUID):
    scope = ReadScope(only=frozenset({shown.id}))
    return (
        select(AuditLog)
        .where(AuditLog.entity_id == entity)
        .order_by(AuditLog.timestamp.desc())
        .limit(50)
        .options(*read_scope.criteria(scope))
    )


def test_one_records_history_never_scans_the_records_table(seeded) -> None:
    session, shown, hidden, visible_id, hidden_id = seeded
    for entity in (visible_id, hidden_id):
        plan = _plan(session, _restricted_history(session, shown, entity))
        assert _seq_scans_of(plan, "records") == [], json.dumps(plan, indent=1)


def test_the_whole_activity_feed_probes_by_key_too(seeded) -> None:
    session, shown, *_ = seeded
    scope = ReadScope(only=frozenset({shown.id}))
    feed = (
        select(AuditLog)
        .order_by(AuditLog.timestamp.desc())
        .limit(50)
        .options(*read_scope.criteria(scope))
    )
    assert _seq_scans_of(_plan(session, feed), "records") == []


def test_the_rule_still_hides_and_shows_the_right_entries(seeded) -> None:
    session, shown, hidden, visible_id, hidden_id = seeded
    scope = ReadScope(only=frozenset({shown.id}))
    seen = session.execute(
        select(AuditLog.entity_id)
        .where(AuditLog.entity_id.in_([visible_id, hidden_id]))
        .options(*read_scope.criteria(scope))
    ).all()
    assert {e for (e,) in seen} == {visible_id}


def test_a_restricted_history_query_is_fast(seeded) -> None:
    session, shown, hidden, visible_id, hidden_id = seeded
    started = time.perf_counter()
    for _ in range(20):
        session.execute(_restricted_history(session, shown, visible_id)).all()
    assert (time.perf_counter() - started) / 20 < 0.05


def test_a_restricted_count_stops_at_the_cap(seeded, monkeypatch) -> None:
    session, shown, hidden, *_ = seeded
    read_scope.install(session, lambda: ReadScope(only=frozenset({shown.id})))
    repo = LocalRecordRepository(session, is_postgres=True)
    query = ResolvedQuery()
    exact = repo.count(query)
    assert exact == RECORDS // 3
    # under the cap: exact; over it: the cap, flagged as not exact
    assert repo.estimate_count(query) == (exact, False)
    monkeypatch.setattr(record_repo, "RESTRICTED_COUNT_CAP", 500)
    assert repo.estimate_count(query) == (500, True)
    # the planner's figure of the whole table is never what is reported
    assert repo.estimate_count(query)[0] != RECORDS
