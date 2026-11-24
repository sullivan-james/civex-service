"""One page budget for every paged sync read: a count (an "at most") and bytes,
and `more` is "the page stopped before the end", so an action too big for a
page is delivered over several, and kept whole whenever it fits one."""

from __future__ import annotations

import uuid

from civex.db.models import AuditLog
from civex.domain.sync_page import fit, take
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
    cls = type(authority.sync_repo)
    original = cls.entries_after

    def small(self, seq, limit, max_bytes=2_000):
        return original(self, seq, limit, 2_000)

    monkeypatch.setattr(cls, "entries_after", small)
    phone.sync_svc.sync()
    assert differences(snapshots(authority), snapshots(phone)) == []
