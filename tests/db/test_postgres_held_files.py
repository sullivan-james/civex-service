"""The statements behind the files list and a bulk edit, on PostgreSQL: the
same answers as on SQLite (tests/services/test_file_listing_catalog.py and
test_bulk_edit_chunks.py), compiled onto `jsonb` and `string_agg`.

Requires CIVEX_TEST_POSTGRES_URL (see test_search_vector_trigger.py); skipped
otherwise.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civex.db.migrate import ensure_schema_current
from civex.db.models import Dataset, Record, Schema, StoredObject
from civex.domain.query import ResolvedQuery, ResolvedSet, TextSearch
from civex.repositories.local.record_repo import LocalRecordRepository

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


def _sha(n: int) -> str:
    return uuid.uuid4().hex + f"{n:032x}"


def test_the_files_records_hold_and_the_values_an_edit_reads(session: Session) -> None:
    tag = uuid.uuid4().hex[:8]
    ds = Dataset(name=f"ds-{tag}")
    site = Schema(name=f"site_{tag}")
    session.add_all([ds, site])
    session.flush()
    visit = Schema(name=f"visit_{tag}", parent_id=site.id)
    session.add(visit)
    session.flush()
    name, notes, photo, extras, status = (str(uuid.uuid4()) for _ in range(5))
    one, two, three = _sha(1), _sha(2), _sha(3)
    volume = f"vol-{tag}"
    # `one` and `two` are on a drive here; `three` is on none.
    session.add_all(
        [
            StoredObject(sha256=one, volume=volume, size=10),
            StoredObject(sha256=two, volume=volume, size=20),
        ]
    )
    session.flush()

    def file(sha: str, filename: str, size: int) -> dict:
        return {"sha256": sha, "filename": filename, "size": size}

    ridge = Record(
        dataset_id=ds.id,
        schema_id=site.id,
        data={name: "North Ridge", notes: file(one, "ridge-notes.pdf", 10)},
    )
    bare = Record(dataset_id=ds.id, schema_id=site.id, data={name: "No files"})
    session.add_all([ridge, bare])
    session.flush()
    first = Record(
        dataset_id=ds.id,
        schema_id=visit.id,
        parent_record_id=ridge.id,
        data={
            status: "new",
            photo: file(two, "IMG_1.jpg", 20),
            extras: [file(one, "again.pdf", 10), file(three, "far.csv", 30)],
        },
    )
    second = Record(
        dataset_id=ds.id,
        schema_id=visit.id,
        parent_record_id=ridge.id,
        data={status: "done", photo: file(two, "IMG_2.jpg", 20)},
    )
    session.add_all([first, second])
    session.flush()
    repo = LocalRecordRepository(
        session, is_postgres=session.get_bind().dialect.name == "postgresql"
    )
    fields = {notes: "notes", photo: "photo", extras: "extras"}

    def held(picked: ResolvedSet, search: TextSearch | None = None):
        return {
            (uuid.UUID(str(h.record_id)), h.field, h.filename): h
            for h in repo.held_files(picked, fields, search, depth=1)
        }

    # A whole collection: every file value, with the copy its record uses.
    everything = ResolvedSet(queries=[ResolvedQuery(dataset_id=ds.id)])
    found = held(everything)
    assert {(field, filename) for _, field, filename in found} == {
        ("notes", "ridge-notes.pdf"),
        ("photo", "IMG_1.jpg"),
        ("extras", "again.pdf"),
        ("extras", "far.csv"),
        ("photo", "IMG_2.jpg"),
    }
    assert found[(first.id, "photo", "IMG_1.jpg")].volume == volume
    assert found[(first.id, "photo", "IMG_1.jpg")].size == 20
    assert found[(first.id, "extras", "far.csv")].volume is None
    assert found[(first.id, "extras", "far.csv")].stored_on == ()

    # One kind, then everything beneath what it lists.
    sites = ResolvedQuery(dataset_id=ds.id, schema_id=site.id)
    assert len(held(ResolvedSet(queries=[sites]))) == 1
    assert len(held(ResolvedSet(queries=[sites], below=True))) == 5
    # Ticked rows, and only some kinds of record.
    assert len(held(ResolvedSet(ids=[second.id, bare.id]))) == 1
    assert (
        len(held(ResolvedSet(ids=[ridge.id], below=True, schema_ids=[visit.id]))) == 4
    )
    # Beneath, kept only where a query lists it.
    done = ResolvedQuery(
        dataset_id=ds.id, schema_id=visit.id, field_filters=[(status, "done")]
    )
    listed = held(ResolvedSet(queries=[sites], below=True, listed=[done]))
    assert {filename for _, _, filename in listed} == {"ridge-notes.pdf", "IMG_2.jpg"}

    # A search: the file's own name, or its record's or one above it.
    by_name = held(everything, TextSearch("img_2", (name, status)))
    assert {k[2] for k, h in by_name.items() if h.found} == {"IMG_2.jpg"}
    by_parent = held(everything, TextSearch("north ridge", (name, status)))
    assert all(h.found for h in by_parent.values())
    assert not any(
        h.found for h in held(everything, TextSearch("nowhere", (name,))).values()
    )

    # The records that hold a file, and the copies several records use.
    assert [uuid.UUID(str(r)) for r in repo.holders(everything)] == [
        r.id for r in sorted([ridge, first, second], key=lambda r: (r.created_at, r.id))
    ]
    shared = repo.shared_copies()
    assert shared[(two, volume)] == 2 and shared[(one, volume)] == 2
    assert (three, None) not in shared

    # What a bulk edit's plan reads: only the fields asked for, where held.
    rows = {
        uuid.UUID(str(rid)): values
        for rid, _, _, values in repo.field_rows(
            [status, name], query=everything.queries[0]
        )
    }
    assert rows[first.id] == {status: "new"} and rows[bare.id] == {name: "No files"}
    by_ids = repo.field_rows([status], ids=[first.id, second.id, uuid.uuid4()])
    assert sorted(v[status] for _, _, _, v in by_ids) == ["done", "new"]

    # And what it writes: many records in one statement.
    stamp = datetime(2031, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    repo.update_many(
        [(r.id, {**r.data, status: "checked"}) for r in (first, second)], stamp
    )
    after = {r.id: r for r in repo.list_by_ids([first.id, second.id])}
    assert {r.data[status] for r in after.values()} == {"checked"}
    assert {r.updated_at for r in after.values()} == {stamp}
    assert after[first.id].data[photo]["filename"] == "IMG_1.jpg"  # the rest kept
