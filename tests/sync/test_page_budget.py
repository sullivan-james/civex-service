"""One page budget for every paged sync read: a count (an "at most") and bytes,
and `more` is "the page stopped before the end", so an action too big for a
page is delivered over several, and kept whole whenever it fits one."""

from __future__ import annotations

import os
import uuid

import pytest

from civex.db.models import AuditLog
from civex.domain import sync_page
from civex.domain.sync_page import fit, take
from civex.testing.peers import connect, device

from .test_move_records import setup as move_setup
from civex.testing.convergence import differences
from civex.testing.peers import snapshots


def test_fit_is_an_at_most_by_count_and_bytes():
    assert fit([10] * 5, 3, 1000) == 3
    assert fit([400, 400, 400], 10, 1000) == 2
    assert fit([5000, 1], 10, 1000) == 1  # alone, over the budget: still sent
    assert take([1, 2, 3], [1, 1, 1], 2, 100) == ([1, 2], True)
    assert take([1, 2], [1, 1], 2, 100) == ([1, 2], False)


def _action_of(laptop, authority, n: int, **fields) -> tuple[int, int]:
    """`n` new records, made on the laptop, which the authority then holds as
    one action (one `op_id`), as a tree moved to another collection would be.
    Returns the number before it and after it."""
    start = authority.sync_repo.head_seq()
    for i in range(n):
        laptop.record_svc.add(
            "study", "encounter", {"site": f"s{i}", "depth": 1.0} | fields
        )
    laptop.commit()
    laptop.sync_svc.sync()
    authority.sync_repo.sequence_local_entries()
    end = authority.sync_repo.head_seq()
    authority.sync_repo._s.query(AuditLog).filter(
        AuditLog.hub_seq > start, AuditLog.hub_seq <= end
    ).update({"op_id": uuid.uuid4()}, synchronize_session=False)
    authority.commit()
    return start, end


def _pages(authority, after, limit, **kwargs):
    seen = []
    while True:
        entries, more = authority.sync_repo.entries_after(after, limit, **kwargs)
        seen.append((entries, more))
        if not more:
            return seen
        after = entries[-1].hub_seq


def test_an_action_over_a_thousand_entries_is_not_cut_and_called_done(pair, authority):
    laptop, phone, _ = pair
    laptop.sync_svc.sync()
    start, end = _action_of(laptop, authority, 1100)
    assert end - start >= 1100
    # Asked for 200, the page ends with the action, which fits the budget:
    # never cut with "no more" (audit C1).
    page, more = authority.sync_repo.entries_after(start, 200)
    assert len(page) == end - start and more is False
    # An existing client reads it all.
    phone.sync_svc.sync()
    assert differences(snapshots(authority), snapshots(phone)) == []


def test_a_page_of_wide_records_stops_at_the_byte_budget(pair, authority):
    laptop, phone, _ = pair
    laptop.sync_svc.sync()
    start = authority.sync_repo.head_seq()
    wide = "x" * 20_000
    for i in range(30):
        laptop.record_svc.add(
            "study", "encounter", {"site": wide + str(i), "depth": 1.0}
        )
    laptop.commit()
    laptop.sync_svc.sync()
    pages = _pages(authority, start, 200, max_bytes=100_000)
    assert len(pages) > 3
    assert all(more for _, more in pages[:-1]) and not pages[-1][1]
    assert sum(len(e) for e, _ in pages) == authority.sync_repo.head_seq() - start
    phone.sync_svc.sync()
    assert differences(snapshots(authority), snapshots(phone)) == []


def test_an_action_over_the_budget_alone_is_cut_and_says_more(pair, authority):
    laptop, phone, _ = pair
    laptop.sync_svc.sync()
    start, end = _action_of(laptop, authority, 300)
    pages = _pages(authority, start, 200, max_bytes=2_000)
    assert len(pages) > 2
    assert all(more for _, more in pages[:-1]) and not pages[-1][1]
    numbers = [e.hub_seq for entries, _ in pages for e in entries]
    assert numbers == list(range(start + 1, end + 1))


def test_an_action_is_kept_whole_by_ending_the_page_before_it(pair, authority):
    laptop, phone, _ = pair
    laptop.sync_svc.sync()
    for i in range(5):
        laptop.record_svc.add("study", "encounter", {"site": f"a{i}", "depth": 1.0})
    laptop.commit()
    laptop.sync_svc.sync()
    authority.sync_repo.sequence_local_entries()
    before = authority.sync_repo.head_seq()
    start, end = _action_of(laptop, authority, 20)
    assert start == before
    # room for the 5 loose entries and a few of the action, but not all of it
    page, more = authority.sync_repo.entries_after(before - 5, 200, max_bytes=3_000)
    assert more and page[-1].hub_seq == before  # ended before the action


def test_a_device_follows_a_cut_action_across_pages(pair, authority, monkeypatch):
    """The client's mid-action handling: the action arrives in pieces (a tiny
    budget) and the device still ends identical."""
    laptop, phone, _ = pair
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    _action_of(laptop, authority, 300)
    monkeypatch.setattr(sync_page, "PAGE_BUDGET_BYTES", 2_000)
    phone.sync_svc.sync()
    assert differences(snapshots(authority), snapshots(phone)) == []


def _big_delete(project, authority, records: int):
    """A collection of `records` records, deleted by a device: one action of
    records + 1 entries. (The authority does not keep the device's `op` for a
    cascade it applies itself, so it is stamped on what it wrote: noted in the
    sync audit as a separate finding.)"""
    a, b, _, _ = move_setup(project, authority)
    for i in range(records):
        a.record_svc.add("archive", "site", {"name": f"r{i}"})
    a.commit()
    a.sync_svc.sync()
    b.sync_svc.sync()
    authority.sync_repo.sequence_local_entries()
    start = authority.sync_repo.head_seq()
    a.dataset_svc.delete("archive")
    a.commit()
    a.sync_svc.sync()
    authority.sync_repo.sequence_local_entries()
    # The authority writes the cascade as entries of its own; hold them as the
    # one action the device made, as the feed carries an action (`op_id`).
    authority.sync_repo._s.query(AuditLog).filter(AuditLog.hub_seq > start).update(
        {"op_id": uuid.uuid4()}, synchronize_session=False
    )
    authority.commit()
    return a, b, start


def _one_op(authority, start: int) -> int:
    rows = (
        authority.sync_repo._s.query(AuditLog.op_id)
        .filter(AuditLog.hub_seq > start)
        .all()
    )
    ops = {r[0] for r in rows}
    assert len(ops) == 1 and None not in ops, ops
    return len(rows)


def test_a_real_collection_delete_of_a_thousand_records_arrives_whole(
    project, authority
):
    a, b, start = _big_delete(project, authority, 600)
    size = _one_op(authority, start)
    assert size >= 601
    page, more = authority.sync_repo.entries_after(start, 200)
    assert len(page) == size and more is False  # whole, not cut (audit C1)
    b.sync_svc.sync()
    assert differences(snapshots(authority), snapshots(b)) == []
    assert b.sync_svc.conflicts() == []


def test_a_real_collection_delete_cut_by_a_tiny_budget_still_arrives(
    project, authority, monkeypatch
):
    """The action is over the budget: it travels in pieces, each saying more
    follows, and the device (which holds what it has until the rest comes)
    ends identical."""
    a, b, start = _big_delete(project, authority, 600)
    monkeypatch.setattr(sync_page, "PAGE_BUDGET_BYTES", 20_000)
    pages = _pages(authority, start, 200)
    assert len(pages) > 3 and all(more for _, more in pages[:-1])
    assert sum(len(e) for e, _ in pages) == _one_op(authority, start)
    b.sync_svc.sync()
    assert differences(snapshots(authority), snapshots(b)) == []
    assert b.sync_svc.conflicts() == []


def test_a_join_reads_snapshot_pages_cut_by_bytes(
    pair, authority, project, monkeypatch
):
    """Pages of wide records stop at the budget (the same knob as the feed's)
    and the joining device follows `next`, not a short page."""
    laptop, _, _ = pair
    wide = "y" * 5_000
    for i in range(60):
        laptop.record_svc.add(
            "study", "encounter", {"site": f"{wide}{i}", "depth": float(i)}
        )
    laptop.commit()
    laptop.sync_svc.sync()
    monkeypatch.setattr(sync_page, "PAGE_BUDGET_BYTES", 20_000)
    pages = []
    after = None
    while True:
        page = authority.authority_svc.snapshot("record", after, 200)
        pages.append(page)
        if not page.more:
            break
        after = page.next
    assert len(pages) > 5 and all(p.next for p in pages[:-1])
    late = device(project, authority, "late")
    connect(late)  # joins, reading every kind a page at a time
    assert differences(snapshots(authority), snapshots(late)) == []


@pytest.mark.skipif(
    not os.environ.get("CIVEX_TEST_POSTGRES_URL"),
    reason="CIVEX_TEST_POSTGRES_URL not set",
)
def test_postgres_pages_stop_at_the_byte_budget(tmp_path):
    """The size of an entry's payload is read in SQL (JSONB cast to text)."""
    from .test_postgres_authority import _pg_authority

    for pg in _pg_authority(tmp_path):
        for i in range(40):
            pg.schema_svc.create(f"s_{i}")
        pg.commit()
        pg.sync_repo.sequence_local_entries()
        rows = pg.sync_repo._keys_after(0, 1000)
        assert rows and all(size > 0 for _, _, size in rows)
        total = len(rows)
        pages = _pages(pg, 0, 200, max_bytes=2_000)
        assert len(pages) > 2
        assert all(more for _, more in pages[:-1]) and not pages[-1][1]
        assert sum(len(e) for e, _ in pages) == total
        one, more = pg.sync_repo.entries_after(0, 200)
        assert len(one) == total and more is False


def test_only_the_rows_of_the_page_are_loaded(pair, authority):
    """Choosing a page reads keys and sizes; the (wide) rows are loaded only
    for what the page holds."""
    from sqlalchemy import event

    laptop, _, _ = pair
    laptop.sync_svc.sync()
    start = authority.sync_repo.head_seq()
    for i in range(40):
        laptop.record_svc.add(
            "study", "encounter", {"site": "w" * 5_000 + str(i), "depth": 1.0}
        )
    laptop.commit()
    laptop.sync_svc.sync()
    authority.sync_repo.sequence_local_entries()
    loaded: list[int] = []

    def count(target, context):
        loaded.append(1)

    event.listen(AuditLog, "load", count)
    try:
        page, more = authority.sync_repo.entries_after(start, 200, max_bytes=30_000)
    finally:
        event.remove(AuditLog, "load", count)
    assert more and 0 < len(page) < 40
    assert len(loaded) == len(page)


def _held_action(pair, authority):
    """An action (10 updates, one `op`) that reaches, in its last entry, a
    record the phone has an unsent edit to: the phone must hold all of it."""
    laptop, phone, _ = pair
    ids = [
        str(
            laptop.record_svc.add(
                "study", "encounter", {"site": f"h{i}", "depth": 1.0}
            ).id
        )
        for i in range(10)
    ]
    laptop.commit()
    laptop.sync_svc.sync()
    phone.sync_svc.sync()
    authority.sync_repo.sequence_local_entries()
    start = authority.sync_repo.head_seq()
    for i, rid in enumerate(ids):
        laptop.record_svc.update(rid, {"depth": 50.0 + i})
    laptop.commit()
    laptop.sync_svc.sync()
    authority.sync_repo.sequence_local_entries()
    authority.sync_repo._s.query(AuditLog).filter(AuditLog.hub_seq > start).update(
        {"op_id": uuid.uuid4()}, synchronize_session=False
    )
    authority.commit()
    phone.record_svc.update(ids[-1], {"depth": 7.0})
    phone.commit()
    return phone, ids, start


def test_a_device_holds_a_whole_action_that_fits_a_page_but_not_the_limit(
    pair, authority, monkeypatch
):
    """The server keeps an action in one page while it fits the budget, however
    small the entry limit: the device sees all of it at once and holds it."""
    from civex.services import sync_service

    phone, ids, start = _held_action(pair, authority)
    monkeypatch.setattr(sync_service, "FEED_PAGE", 4)
    page, more = authority.sync_repo.entries_after(start, 4)
    assert len(page) == 10 and more is False
    phone.sync_svc._pull(phone.sync_svc._transport())  # the feed only, no push
    phone.commit()
    assert phone.record_svc.get(ids[0]).data["depth"] == 1.0


@pytest.mark.xfail(
    reason="CLIENT: an action over the page budget alone is cut across pages "
    "and the device's `waiting` is decided per page (sync_service._pull), so "
    "the part before the entry that touches its unsent edit is applied. Needs "
    "the client to carry `waiting` across pages while `more` is true.",
    strict=True,
)
def test_a_device_holds_an_over_budget_action_cut_across_pages(
    pair, authority, monkeypatch
):
    phone, ids, start = _held_action(pair, authority)
    monkeypatch.setattr(sync_page, "PAGE_BUDGET_BYTES", 1_500)
    assert len(_pages(authority, start, 200)) > 2
    phone.sync_svc._pull(phone.sync_svc._transport())
    phone.commit()
    assert phone.record_svc.get(ids[0]).data["depth"] == 1.0
