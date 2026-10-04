"""records.search_vector must stay in sync with `data` no matter which code
path writes the row (CIVEX-173). On PostgreSQL this is enforced by a trigger
(migration c6e4c3b2bbe8) rather than by LocalRecordRepository -- this test
writes a record with a raw INSERT, bypassing the repo entirely, and confirms
it's still found via a search_vector query.

Requires a real PostgreSQL reachable at CIVEX_TEST_POSTGRES_URL (e.g.
postgresql+psycopg2://postgres@localhost:5432/civex_test); skipped otherwise,
same as this repo's other environment-gated tests (see
tests/plugins/test_subprocess_runtime_uv_e2e.py). SQLite doesn't use
search_vector at all (see models._TSVECTOR) so there's nothing to verify there.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from civex.db.migrate import ensure_schema_current

_PG_URL = os.environ.get("CIVEX_TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not _PG_URL,
    reason="set CIVEX_TEST_POSTGRES_URL to a scratch PostgreSQL DB to run this test",
)


@pytest.fixture()
def pg_engine():
    engine = create_engine(_PG_URL)
    ensure_schema_current(engine)
    yield engine
    engine.dispose()


def _insert_schema_and_dataset(
    conn, schema_id: uuid.UUID, dataset_id: uuid.UUID
) -> None:
    conn.execute(
        text("INSERT INTO schemas (id, name, created_at) VALUES (:id, :name, now())"),
        {"id": schema_id, "name": f"trial-{schema_id}"},
    )
    conn.execute(
        text("INSERT INTO datasets (id, name, created_at) VALUES (:id, :name, now())"),
        {"id": dataset_id, "name": f"study-{dataset_id}"},
    )


def test_raw_insert_outside_record_repo_is_still_searchable(pg_engine) -> None:
    schema_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    record_id = uuid.uuid4()

    with pg_engine.begin() as conn:
        _insert_schema_and_dataset(conn, schema_id, dataset_id)
        # Deliberately bypass LocalRecordRepository.create -- no search_vector
        # supplied, as a bulk import or a direct session write would do.
        conn.execute(
            text(
                """
                INSERT INTO records (id, dataset_id, schema_id, data, created_at, updated_at)
                VALUES (:id, :dataset_id, :schema_id, :data, now(), now())
                """
            ),
            {
                "id": record_id,
                "dataset_id": dataset_id,
                "schema_id": schema_id,
                "data": '{"subject": "S02-unique-search-token"}',
            },
        )

    with pg_engine.connect() as conn:
        found = conn.execute(
            text(
                "SELECT id FROM records WHERE search_vector @@ plainto_tsquery('simple', :q)"
            ),
            {"q": "S02-unique-search-token"},
        ).fetchone()

    assert found is not None
    assert found[0] == record_id


def test_raw_update_outside_record_repo_refreshes_the_vector(pg_engine) -> None:
    schema_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    record_id = uuid.uuid4()

    with pg_engine.begin() as conn:
        _insert_schema_and_dataset(conn, schema_id, dataset_id)
        conn.execute(
            text(
                """
                INSERT INTO records (id, dataset_id, schema_id, data, created_at, updated_at)
                VALUES (:id, :dataset_id, :schema_id, :data, now(), now())
                """
            ),
            {
                "id": record_id,
                "dataset_id": dataset_id,
                "schema_id": schema_id,
                "data": '{"subject": "before-update-token"}',
            },
        )

    with pg_engine.begin() as conn:
        conn.execute(
            text("UPDATE records SET data = :data WHERE id = :id"),
            {"id": record_id, "data": '{"subject": "after-update-token"}'},
        )

    with pg_engine.connect() as conn:
        stale = conn.execute(
            text(
                "SELECT id FROM records WHERE search_vector @@ plainto_tsquery('simple', :q)"
            ),
            {"q": "before-update-token"},
        ).fetchone()
        fresh = conn.execute(
            text(
                "SELECT id FROM records WHERE search_vector @@ plainto_tsquery('simple', :q)"
            ),
            {"q": "after-update-token"},
        ).fetchone()

    assert stale is None
    assert fresh is not None
    assert fresh[0] == record_id
