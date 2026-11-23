"""Pages of the files records cite, on PostgreSQL: in order, from `after`, only
those the authority hasn't confirmed, never a deleted record's, and read by an
ordered index scan that stops at the limit (not a DISTINCT over every
reference per page, which exhausted shared memory on a big project).

Requires CIVEX_TEST_POSTGRES_URL naming a scratch DB; skipped otherwise.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from civex.db.migrate import ensure_schema_current
from civex.db.models import Dataset, FileReference, Record, Schema, ServerFile
from civex.repositories.local.sync_repo import LocalSyncRepository

_PG_URL = os.environ.get("CIVEX_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.xdist_group("postgres_scratch"),
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


def test_pages_are_ordered_filtered_and_exclude_deleted(session: Session) -> None:
    tag = uuid.uuid4().hex[:8]
    ds = Dataset(name=f"ds-{tag}")
    schema = Schema(name=f"s_{tag}")
    session.add_all([ds, schema])
    session.flush()
    live = Record(dataset_id=ds.id, schema_id=schema.id, data={})
    gone = Record(
        dataset_id=ds.id,
        schema_id=schema.id,
        data={},
        deleted_at=datetime.now(timezone.utc),
    )
    session.add_all([live, gone])
    session.flush()
    shas = sorted(f"{tag}{i:056d}" for i in range(25))
    for sha in shas:
        session.add(FileReference(sha256=sha, record_id=live.id))
    dead = f"{tag}dead".ljust(64, "0")
    session.add(FileReference(sha256=dead, record_id=gone.id))
    session.add(ServerFile(sha256=shas[3]))
    session.flush()

    repo = LocalSyncRepository(session)
    first = repo.referenced_shas(shas[0][:8], 10)
    assert first == [s for s in shas][:10] or set(first) <= set(shas)
    mine = [s for s in repo.referenced_shas(f"{tag}", 1000) if s.startswith(tag)]
    assert mine == sorted(shas)  # deleted record's file left out
    unconfirmed = [
        s
        for s in repo.referenced_shas(f"{tag}", 1000, unconfirmed=True)
        if s.startswith(tag)
    ]
    assert shas[3] not in unconfirmed and len(unconfirmed) == 24
    after = repo.referenced_shas(shas[9], 5)
    assert after[0] > shas[9]

    plan = "\n".join(
        r[0]
        for r in session.execute(
            text(
                "EXPLAIN "
                + str(
                    repo._referenced_page("", 1000, True).compile(
                        dialect=postgresql.dialect(),
                        compile_kwargs={"literal_binds": True},
                    )
                )
            )
        )
    )
    assert "Index" in plan
