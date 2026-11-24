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
