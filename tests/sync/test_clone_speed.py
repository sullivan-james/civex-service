"""Copying a project onto a new device is fast: pages sized by bytes (asked for
only of an authority that offers them), the next page read while this one is
written, a page of records written in a few statements, and an index that makes
the read by `(created_at, id)` a scan. What the device ends up holding is what
writing each thing one at a time gives."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import inspect, text

import civex.services.sync_service as sync_service
from civex.db.models import Record
from civex.domain.sync import SNAPSHOT_PAGE_MAX
from civex.testing import connect, device, snapshots
from civex.testing.peers import Loopback, build_study

from .test_bulk_push import TABLES


def _rows(ctx) -> dict[str, list]:
    ctx.commit()
    names = ("records", "file_references", "record_references")
    return {
        n: [tuple(map(str, r)) for r in ctx._session.execute(text(TABLES[n])).all()]
        for n in names
    }


def _study(authority, n: int = 40):
    build_study(authority)
    authority.schema_svc.create("sample", parent="encounter")
    authority.schema_svc.add_field("sample", "label", "string")
    authority.schema_svc.add_field(
        "encounter", "mate", "reference", restrictions={"schema": "encounter"}
    )
    first = authority.record_svc.add("study", "encounter", {"site": "first"})
    kids = []
    for i in range(n):
        kids.append(
            authority.record_svc.add(
                "study", "encounter", {"site": f"s{i}", "mate": str(first.id)}
            )
        )
    for i in range(n // 2):
        authority.record_svc.add(
            "study", "sample", {"label": f"l{i}"}, parent_record_id=str(kids[i].id)
        )
    authority.commit()
    return first, kids


def _spy_limits(monkeypatch) -> list[tuple[str, int]]:
    seen: list[tuple[str, int]] = []
    real = Loopback.snapshot

    def snapshot(self, kind, after, limit, *rest):
        seen.append((kind, limit))
        return real(self, kind, after, limit, *rest)

    monkeypatch.setattr(Loopback, "snapshot", snapshot)
    return seen


def test_a_copy_asks_for_big_pages_and_reads_each_kind_in_one_request(
    project, authority, monkeypatch
):
    _study(authority)
    seen = _spy_limits(monkeypatch)
    phone = device(project, authority, "phone")
    assert connect(phone) == "joined"
    assert {limit for _, limit in seen} == {SNAPSHOT_PAGE_MAX}
    assert [k for k, _ in seen].count("record") == 1
    assert snapshots(phone) == snapshots(authority)


def test_an_authority_without_big_pages_is_asked_for_200(
    project, authority, monkeypatch
):
    _study(authority)
    monkeypatch.setattr(
        authority.authority_svc, "_capabilities", ("library", "device_login")
    )
    seen = _spy_limits(monkeypatch)
    phone = device(project, authority, "phone")
    assert connect(phone) == "joined"
    assert {limit for _, limit in seen} == {sync_service.SNAPSHOT_PAGE}
    assert snapshots(phone) == snapshots(authority)


@pytest.mark.parametrize("page", [1, 3, 7, 1000])
def test_writing_a_page_in_bulk_leaves_what_writing_one_at_a_time_does(
    project, authority, monkeypatch, page
):
    """Parents, references, a child older than its parent, and a parent on a
    later page: the same rows, whatever the page size."""
    first, kids = _study(authority)
    s = authority._session
    # a child made on a clock that was behind: older than the record it sits under
    parent = kids[-1]
    child = authority.record_svc.add(
        "study", "sample", {"label": "early"}, parent_record_id=str(parent.id)
    )
    authority.commit()
    s.get(Record, child.id).created_at = s.get(
        Record, parent.id
    ).created_at - timedelta(days=1)
    authority.commit()

    monkeypatch.setattr(sync_service, "SNAPSHOT_PAGE_BIG", page)
    fast = device(project, authority, "fast")
    assert connect(fast) == "joined"

    def one_by_one(self, kind, snaps, waiting):
        present = self._repo.existing_ids(
            kind, {p for s in snaps if (p := sync_service._sits_under(kind, s))}
        )
        for snap in snaps:
            self._join_one(kind, snap, present, waiting)

    monkeypatch.setattr(sync_service.SyncService, "_join_page", one_by_one)
    slow = device(project, authority, "slow")
    assert connect(slow) == "joined"

    assert snapshots(fast) == snapshots(authority)
    assert _rows(fast) == _rows(slow)
    assert _rows(fast)["record_references"]


def test_a_copy_that_stopped_part_way_is_finished_by_copying_again(
    project, authority, monkeypatch
):
    """Some of the records are held already (a copy cut short, run again): they
    are written as they were and the rest go in together."""
    _study(authority)
    monkeypatch.setattr(sync_service, "SNAPSHOT_PAGE_BIG", 9)
    phone = device(project, authority, "phone")
    real = Loopback.snapshot
    calls = {"n": 0}

    def cut(self, kind, after, limit, *rest):
        # (the third page of records is the one asked for while the second is
        # written: its failure arrives after two pages were committed)
        if kind == "record":
            calls["n"] += 1
            if calls["n"] == 3:
                raise sync_service.SyncError("the connection dropped")
        return real(self, kind, after, limit, *rest)

    monkeypatch.setattr(Loopback, "snapshot", cut)
    with pytest.raises(sync_service.SyncError):
        phone.sync_svc.connect("https://authority.test", phone._invite)
    phone.commit()
    held = phone.sync_repo.all_ids("record")
    assert len(held) == 18  # two pages of 9 were written and kept
    assert held != authority.sync_repo.all_ids("record")
    monkeypatch.setattr(Loopback, "snapshot", real)
    assert connect(phone) == "joined"
    assert snapshots(phone) == snapshots(authority)


def test_the_snapshot_read_has_an_index_on_created_and_id():
    from civex.db.models import Record as R

    names = {i.name for i in R.__table__.indexes}
    assert "ix_records_created_id" in names


def test_the_index_is_made_by_a_migration(authority):
    authority.commit()
    found = inspect(authority._session.get_bind()).get_indexes("records")
    assert any(i["column_names"] == ["created_at", "id"] for i in found)


def test_a_wide_page_is_cut_by_bytes_and_read_a_chunk_at_a_time(
    project, authority, monkeypatch
):
    """Asked for 1000 records of ~1 KB each with a budget of 20 KB, the
    authority reads no more than the budget and one chunk, and the pages that
    follow still cover every record once."""
    from civex.services import sync_authority

    build_study(authority)
    for i in range(150):
        authority.record_svc.add(
            "study", "encounter", {"site": f"{i:04d}" + "x" * 1000}
        )
    authority.commit()
    monkeypatch.setattr(sync_authority, "SNAPSHOT_PAGE_BYTES", 20_000)
    monkeypatch.setattr(sync_authority, "SNAPSHOT_CHUNK", 5)
    read: list[int] = []
    real = authority.sync_repo.snapshots_page

    def spy(kind, after, limit, *rest):
        out = real(kind, after, limit, *rest)
        if kind == "record":
            read.append(len(out))
        return out

    monkeypatch.setattr(authority.sync_repo, "snapshots_page", spy)
    svc = authority.authority_svc
    seen: list[str] = []
    after = None
    pages = 0
    while True:
        before = len(read)
        page = svc.snapshot("record", after, 1000)
        pages += 1
        seen += [i["id"] for i in page.items]
        assert max(read[before:]) <= 5  # never more than a chunk at once
        assert sum(read[before:]) <= 20  # about the budget (1 KB rows) + a chunk
        if not page.more:
            break
        assert 5 <= len(page.items) <= 20
        after = page.next
    assert pages > 5
    assert len(seen) == len(set(seen)) == 151
    assert set(seen) == authority.sync_repo.all_ids("record")


def test_a_refused_big_page_falls_back_to_200_for_the_rest_of_the_copy(
    project, authority, monkeypatch
):
    """An older authority (reached mid-copy) answers 422 to a limit over 500."""
    _study(authority)
    monkeypatch.setattr(sync_service, "SNAPSHOT_PAGE", 25)
    limits: list[int] = []
    real = Loopback.snapshot

    def old(self, kind, after, limit, *rest):
        limits.append(limit)
        if limit > 500:
            raise sync_service.SyncError("too big", retryable=False, status=422)
        return real(self, kind, after, limit, *rest)

    monkeypatch.setattr(Loopback, "snapshot", old)
    phone = device(project, authority, "phone")
    assert connect(phone) == "joined"
    assert limits[0] > 500 and set(limits[1:]) == {25, SNAPSHOT_PAGE_MAX} - {
        SNAPSHOT_PAGE_MAX
    }
    assert snapshots(phone) == snapshots(authority)
