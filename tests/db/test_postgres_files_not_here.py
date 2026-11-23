"""The files a device still has to download, on PostgreSQL: each comes with a
collection that uses it, picked with an aggregate that SQLite allows on a uuid
and PostgreSQL does not (`min(uuid)` does not exist there).

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
from civex.db.models import Dataset, FileReference, Record, Schema
from civex.repositories.local.sync_repo import LocalSyncRepository

_PG_URL = os.environ.get("CIVEX_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.xdist_group("postgres_scratch"),  # one shared scratch DB
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


def test_files_not_here_names_a_collection_on_postgres(session: Session) -> None:
    tag = uuid.uuid4().hex[:8]
    ds = Dataset(name=f"ds-{tag}")
    site = Schema(name=f"site_{tag}")
    session.add_all([ds, site])
    session.flush()
    rec = Record(dataset_id=ds.id, schema_id=site.id, data={})
    session.add(rec)
    session.flush()
    sha = uuid.uuid4().hex + uuid.uuid4().hex  # cited here, held by no drive
    session.add(FileReference(sha256=sha, record_id=rec.id))
    session.flush()

    repo = LocalSyncRepository(session)
    assert repo.count_files_not_here({ds.id}) >= 1
    rows = repo.files_not_here("", 1000, [sha], {ds.id})
    assert rows == [(sha, ds.id)]
    assert isinstance(rows[0][1], uuid.UUID)
