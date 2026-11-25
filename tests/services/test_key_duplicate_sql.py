"""`has_key_duplicate` (the database narrows, the first confirmed group ends
it) answers as `key_duplicates` (every record read) does, on SQLite and
PostgreSQL."""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civex.db.migrate import ensure_schema_current
from civex.db.models import Dataset, Record, Schema
from civex.repositories.local.record_repo import LocalRecordRepository

K = "f1"  # the field id the key is on
L = "f2"

# (name, records as (dataset index, parent index or None, data, deleted), expect)
CASES: list[tuple[str, list[tuple[int, int | None, dict[str, Any], bool]], bool]] = [
    ("none", [], False),
    ("distinct", [(0, None, {K: "a"}, False), (0, None, {K: "b"}, False)], False),
    ("same string", [(0, None, {K: "a"}, False), (0, None, {K: "a"}, False)], True),
    ("number written two ways", [(0, None, {K: 1}, False), (0, None, {K: 1.0}, False)], True),
    ("number and text", [(0, None, {K: 1}, False), (0, None, {K: "1"}, False)], False),
    ("bool and number", [(0, None, {K: True}, False), (0, None, {K: 1}, False)], False),
    ("two bools", [(0, None, {K: True}, False), (0, None, {K: True}, False)], True),
    ("blanks", [(0, None, {K: " "}, False), (0, None, {K: " "}, False)], False),
    ("missing", [(0, None, {}, False), (0, None, {}, False)], False),
    ("json null", [(0, None, {K: None}, False), (0, None, {K: None}, False)], False),
    ("other collection", [(0, None, {K: "a"}, False), (1, None, {K: "a"}, False)], False),
    ("other parent", [(0, 0, {K: "a"}, False), (0, 1, {K: "a"}, False)], False),
    ("same parent", [(0, 0, {K: "a"}, False), (0, 0, {K: "a"}, False)], True),
    ("parent and none", [(0, 0, {K: "a"}, False), (0, None, {K: "a"}, False)], False),
    ("deleted", [(0, None, {K: "a"}, False), (0, None, {K: "a"}, True)], False),
    ("blank beside real", [(0, None, {K: " "}, False), (0, None, {K: "a"}, False), (0, None, {K: "a"}, False)], True),
    ("second key field differs", [(0, None, {K: "a", L: 1}, False), (0, None, {K: "a", L: 2}, False)], False),
    ("both key fields", [(0, None, {K: "a", L: 1}, False), (0, None, {K: "a", L: 1.0}, False)], True),
    ("key with a quote", [(0, None, {K: "it's"}, False), (0, None, {K: "it's"}, False)], True),
]  # fmt: skip


def _check(session: Session, name: str, records, expect: bool) -> None:
    from datetime import datetime, timezone

    schema = Schema(name=f"s_{uuid.uuid4().hex[:8]}")
    sets = [Dataset(name=f"d_{uuid.uuid4().hex[:8]}") for _ in range(2)]
    session.add_all([schema, *sets])
    session.flush()
    parents = []
    for i in range(2):
        parent = Record(dataset_id=sets[0].id, schema_id=schema.id, data={})
        session.add(parent)
        parents.append(parent)
    session.flush()
    for where, parent, data, gone in records:
        session.add(
            Record(
                dataset_id=sets[where].id,
                schema_id=schema.id,
                parent_record_id=parents[parent].id if parent is not None else None,
                data=data,
                deleted_at=datetime.now(timezone.utc) if gone else None,
            )
        )
    session.flush()
    repo = LocalRecordRepository(
        session, is_postgres=session.get_bind().dialect.name == "postgresql"
    )
    for key in ([K], [K, L]):
        had = bool(repo.key_duplicates(schema.id, key))
        assert repo.has_key_duplicate(schema.id, key) == had, (name, key)
        if key == [K] and not any(L in d for _, _, d, _ in records):
            assert had == expect, name


@pytest.mark.parametrize("name,records,expect", CASES, ids=[c[0] for c in CASES])
def test_sqlite(name, records, expect, ctx):
    session = ctx._session
    _check(session, name, records, expect)


_PG_URL = os.environ.get("CIVEX_TEST_POSTGRES_URL")


@pytest.mark.skipif(not _PG_URL, reason="set CIVEX_TEST_POSTGRES_URL")
@pytest.mark.parametrize("name,records,expect", CASES, ids=[c[0] for c in CASES])
def test_postgres(name, records, expect):
    engine = create_engine(_PG_URL)
    ensure_schema_current(engine)
    try:
        with Session(engine) as session:
            _check(session, name, records, expect)
            session.rollback()
    finally:
        engine.dispose()
