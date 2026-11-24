"""An action cut across feed pages is held or applied as a whole: the device
decides once the action's last entry has arrived, never page by page."""

from __future__ import annotations

import uuid
from dataclasses import replace

from civex.db.models import AuditLog


def _action(pair, authority, unsent_on_last: bool):
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
    if unsent_on_last:
        phone.record_svc.update(ids[-1], {"depth": 7.0})
        phone.commit()
    return phone, ids


def _cut(phone, size: int) -> list[int]:
    """The phone's feed, served `size` entries at a time (an action cut across
    pages); answers how many entries each page had."""
    transport = phone.sync_svc._transport()
    real = transport.feed
    sizes: list[int] = []

    def feed(after, limit):
        page = real(after, 1000)
        taken = page.entries[:size]
        sizes.append(len(taken))
        return replace(
            page,
            entries=taken,
            more=len(page.entries) > size or page.more,
            through=None,
        )

    transport.feed = feed
    return sizes


def test_a_device_holds_an_action_cut_across_pages(pair, authority):
    phone, ids = _action(pair, authority, unsent_on_last=True)
    sizes = _cut(phone, 3)
    phone.sync_svc._pull(phone.sync_svc._transport())
    phone.commit()
    assert len(sizes) > 2  # it really was cut
    assert phone.record_svc.get(ids[0]).data["depth"] == 1.0  # all of it held


def test_an_action_cut_across_pages_is_applied_whole_when_nothing_holds_it(
    pair, authority
):
    phone, ids = _action(pair, authority, unsent_on_last=False)
    sizes = _cut(phone, 3)
    phone.sync_svc._pull(phone.sync_svc._transport())
    phone.commit()
    assert len(sizes) > 2
    assert [phone.record_svc.get(i).data["depth"] for i in ids] == [
        50.0 + i for i in range(10)
    ]
    assert phone.sync_repo.meta().cursor == authority.sync_repo.head_seq()


# -- a big action, from disk --------------------------------------------------


def _fake_action(pair, authority, n: int):
    """`n` created records as one action, made from a real entry; the phone is
    told of them through a feed of our own (pages of 1000, cut mid-action)."""
    import copy
    from dataclasses import replace as _replace

    laptop, phone, _ = pair
    start = authority.sync_repo.head_seq()
    laptop.record_svc.add("study", "encounter", {"site": "t", "depth": 1.0})
    laptop.commit()
    laptop.sync_svc.sync()
    authority.sync_repo.sequence_local_entries()
    [template] = [
        e
        for e in authority.sync_repo.entries_after(start, 50)[0]
        if e.entity_type == "record" and e.action == "create"
    ]
    phone.sync_svc.sync()  # caught up to where the action will start
    base = authority.sync_repo.head_seq()
    op = str(uuid.uuid4())
    entries = []
    for i in range(n):
        rid = uuid.uuid4()
        data = copy.deepcopy(template.new_data)
        data["id"] = str(rid)
        data["data"] = {**data["data"], **{k: f"x{i}" for k in list(data["data"])[:1]}}
        entries.append(
            _replace(
                template,
                id=uuid.uuid4(),
                entity_id=rid,
                new_data=data,
                hub_seq=base + 1 + i,
                op=op,
            )
        )
    return phone, entries, base


def _serve(phone, entries, base, page=1000, stop_after=None):
    from civex.domain.sync import FeedPage

    transport = phone.sync_svc._transport()
    calls = {"n": 0}

    def feed(after, limit):
        calls["n"] += 1
        if stop_after is not None and calls["n"] > stop_after:
            from civex.domain.sync import SyncError

            raise SyncError("the connection dropped")
        lo = after - base
        chunk = entries[lo : lo + page]
        return FeedPage(
            entries=chunk,
            head_seq=base + len(entries),
            more=lo + page < len(entries),
            through=chunk[-1].hub_seq if chunk else None,
        )

    transport.feed = feed


def test_a_six_thousand_entry_action_is_applied_whole_from_disk_in_bounded_memory(
    pair, authority
):
    """The mechanism, not the cost of applying (that is the same per entry as
    any pull's): every step is a no-op here, so what is measured is what the
    pull keeps in memory while an action of 6,000 entries is cut over pages."""
    import tracemalloc

    from civex.db.models import AuditLog

    phone, entries, base = _fake_action(pair, authority, 6_000)
    _serve(phone, entries, base)
    svc = object.__getattribute__(phone.sync_svc, "_svc")
    steps: list[int] = []
    svc._replay = lambda thing, seq: steps.append(seq)
    states_seen: list[int] = []
    repo_cls = type(phone.sync_repo)
    real = repo_cls.arriving_entries

    def watching(self, op, after, limit):
        if not states_seen:  # the first read: every entry is on disk by now
            states_seen.append(
                self._s.query(AuditLog)
                .filter(AuditLog.apply_state == "arriving")
                .count()
            )
        return real(self, op, after, limit)

    repo_cls.arriving_entries = watching  # type: ignore[method-assign]
    tracemalloc.start()
    try:
        phone.sync_svc._pull(phone.sync_svc._transport())
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        repo_cls.arriving_entries = real  # type: ignore[method-assign]
    phone.commit()
    assert states_seen == [6_000]  # decided only after the last arrived
    assert len(steps) == 6_000
    assert phone.sync_repo.arriving_action() == (None, False)
    assert phone.sync_repo.meta().cursor == base + 6_000
    applied = (
        phone.sync_repo._s.query(AuditLog)
        .filter(AuditLog.hub_seq > base, AuditLog.apply_state == "applied")
        .count()
    )
    assert applied == 6_000
    assert peak < 40 * 1024 * 1024, peak


def test_a_stop_in_the_middle_of_an_action_resumes_from_disk(pair, authority):
    phone, entries, base = _fake_action(pair, authority, 2_500)
    _serve(phone, entries, base, page=1000, stop_after=2)  # two pages, then it drops
    import pytest

    from civex.domain.sync import SyncError

    with pytest.raises(SyncError, match="dropped"):
        phone.sync_svc._pull(phone.sync_svc._transport())
    phone.commit()
    op, held = phone.sync_repo.arriving_action()
    assert op == entries[0].op and held is False
    assert phone.sync_repo.meta().cursor == base + 2_000  # past what is on disk
    before = len(phone.record_svc.find("study", "encounter", limit=5_000))
    assert before < 100  # none of the action applied yet
    _serve(phone, entries, base)  # a new pass, from the stored cursor
    phone.sync_svc._pull(phone.sync_svc._transport())
    phone.commit()
    assert phone.sync_repo.arriving_action() == (None, False)
    assert len(phone.record_svc.find("study", "encounter", limit=5_000)) >= 2_500


def test_an_entry_on_the_last_page_holds_the_whole_action_on_disk(pair, authority):
    phone, entries, base = _fake_action(pair, authority, 2_500)
    laptop, _, _ = pair
    # the phone has an unsent edit to the very last record of the action
    last = entries[-1]
    from civex.domain.sync import SyncEntry

    assert isinstance(last, SyncEntry)
    from civex.db.models import Record

    phone.record_svc  # (the record doesn't exist yet: make it, then edit it)
    created = phone.record_svc.add("study", "encounter", {"site": "mine", "depth": 1.0})
    phone.commit()
    phone.sync_svc.sync()
    phone.record_svc.update(str(created.id), {"depth": 9.0})
    phone.commit()
    # the action's last entry touches that record
    import copy
    from dataclasses import replace as _replace

    data = copy.deepcopy(last.new_data)
    data["id"] = str(created.id)
    entries[-1] = _replace(last, entity_id=created.id, new_data=data, action="update")
    _serve(phone, entries, base)
    phone.sync_svc._pull(phone.sync_svc._transport())
    phone.commit()
    held = phone.sync_repo.held_entries()
    assert len(held) >= 2_499 and {e.op for e in held} == {entries[0].op}
    assert phone.sync_repo.arriving_action() == (None, False)
    assert Record is not None
