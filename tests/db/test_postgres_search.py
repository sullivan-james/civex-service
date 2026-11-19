"""Text search on PostgreSQL: the same rule as on SQLite (tests/services/
test_record_search.py), compiled onto `jsonb_each`/`jsonb_array_elements`.

Requires CIVEX_TEST_POSTGRES_URL (see test_search_vector_trigger.py); skipped
otherwise.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civex.db.migrate import ensure_schema_current
from civex.db.models import Dataset, Record, Schema
from civex.domain.query import ResolvedQuery, TextSearch
from civex.repositories.local.record_repo import LocalRecordRepository

_PG_URL = os.environ.get("CIVEX_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.xdist_group("postgres_scratch"),  # one scratch DB: see test_move.py
    pytest.mark.skipif(
        not _PG_URL,
        reason="set CIVEX_TEST_POSTGRES_URL to a scratch PostgreSQL DB to run this test",
    ),
]


@pytest.fixture()
def session():
    engine = create_engine(_PG_URL)
    ensure_schema_current(engine)
    with Session(engine) as s:
        yield s
        s.rollback()
    engine.dispose()


def test_values_match_and_internals_do_not(session: Session) -> None:
    ds = Dataset(name=f"ds-{uuid.uuid4().hex[:8]}")
    sch = Schema(name=f"sch_{uuid.uuid4().hex[:8]}")
    session.add_all([ds, sch])
    session.flush()
    label, depth, tags, scan, extras = (str(uuid.uuid4()) for _ in range(5))
    sha = "e4a3" + "0" * 60
    rows = {
        "basalt": {label: "Basalt", depth: 12.5},
        "shale": {label: "Shale", tags: ["fossil", "grey"]},
        "granite": {
            label: "Granite",
            scan: {"sha256": sha, "filename": "core_photo.png", "size": 10},
            extras: [{"sha256": sha, "filename": "field_sheet.pdf", "size": 3}],
        },
    }
    for data in rows.values():
        session.add(Record(dataset_id=ds.id, schema_id=sch.id, data=data))
    session.flush()
    repo = LocalRecordRepository(session, is_postgres=True)
    every = (label, depth, tags, scan, extras)

    def found(term: str, fields: tuple[str, ...] = every) -> set[str]:
        query = ResolvedQuery(
            dataset_id=ds.id, schema_id=sch.id, search=TextSearch(term, fields)
        )
        return {r.data[label] for r in repo.list_filtered(query, 0, 50)}

    assert found("BASALT") == {"Basalt"}
    assert found("12.5") == {"Basalt"}
    assert found("fossil") == {"Shale"}
    assert found("photo") == {"Granite"}
    assert found("sheet") == {"Granite"}
    for term in ("e4a3", label[:8], "sha256", "filename", "size"):
        assert found(term) == set(), term
    assert found("a", (label,)) == {"Basalt", "Shale", "Granite"}
    assert found("photo", (label,)) == set()
    assert found("50%") == set()  # LIKE wildcards are literal
    assert len(repo.search_all(TextSearch("granite", every), dataset_id=ds.id)) == 1
    assert repo.count_schema_matches(sch.id, TextSearch("grey", every)) == 1
