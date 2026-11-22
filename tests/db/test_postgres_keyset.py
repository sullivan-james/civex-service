"""PostgreSQL: keyset paging walks sorted lists (ties, nulls last, both
directions) to exactly the order OFFSET gives, and estimated counts come from
the planner. Requires CIVEX_TEST_POSTGRES_URL (see test_postgres_scaling.py)."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from civex.db.migrate import ensure_schema_current
from civex.db.models import Dataset, Record, Schema
from civex.domain.filters import SortKey
from civex.domain.query import ResolvedQuery
from civex.repositories.local.record_repo import LocalRecordRepository

_PG_URL = os.environ.get("CIVEX_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.xdist_group("postgres_scratch"),
    pytest.mark.skipif(not _PG_URL, reason="set CIVEX_TEST_POSTGRES_URL"),
]


@pytest.fixture()
def session():
    engine = create_engine(_PG_URL)
    ensure_schema_current(engine)
    with Session(engine) as s:
        yield s
        s.rollback()
    engine.dispose()


def _seed(session: Session, n: int = 120) -> tuple[Dataset, Schema]:
    ds = Dataset(name=f"ds-{uuid.uuid4().hex[:8]}")
    sch = Schema(name=f"sch_{uuid.uuid4().hex[:8]}")
    session.add_all([ds, sch])
    session.flush()
    for i in range(n):
        data = {"k": i % 9, "s": f"v{i % 5}"} if i % 7 else {"s": "x"}
        session.add(Record(dataset_id=ds.id, schema_id=sch.id, data=data))
    session.flush()
    return ds, sch


def _walk(repo: LocalRecordRepository, q: ResolvedQuery, limit: int):
    ids, key = [], None
    while True:
        page, key, _ = repo.list_keyset(q, limit, key)
        ids += [r.id for r in page]
        if key is None:
            return ids


@pytest.mark.parametrize(
    "sort",
    [
        [],
        [SortKey(field_id="k", numeric=True)],
        [SortKey(field_id="k", numeric=True, descending=True)],
        [SortKey(field_id="s"), SortKey(field_id="k", numeric=True, descending=True)],
        [SortKey(field_id="", meta="@created_at", descending=True)],
    ],
)
def test_keyset_matches_offset(session: Session, sort) -> None:
    ds, sch = _seed(session)
    repo = LocalRecordRepository(session, is_postgres=True)
    q = ResolvedQuery(dataset_id=ds.id, schema_id=sch.id, sort=sort)
    whole = [r.id for r in repo.list_filtered(q, 0, 1000)]
    assert len(whole) == 120
    for limit in (1, 7, 120):
        assert _walk(repo, q, limit) == whole


def test_estimate_uses_the_planner(session: Session) -> None:
    ds, sch = _seed(session, 500)
    session.execute(text("ANALYZE records"))
    repo = LocalRecordRepository(session, is_postgres=True)
    count, estimated = repo.estimate_count(ResolvedQuery(dataset_id=ds.id))
    assert estimated and 250 <= count <= 1000
    whole, estimated = repo.estimate_count(ResolvedQuery())
    assert estimated and whole >= 1
