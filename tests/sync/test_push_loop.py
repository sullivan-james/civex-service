"""A push keeps going while it makes progress: a byte budget that cuts a batch
short, or a server that answers fewer entries than were sent, only means the
rest goes in the next request of the same pass."""

from __future__ import annotations

from civex.services import sync_service
from civex.testing.peers import build_study, connect, device, snapshots


def _connected_with_new_records(project, authority, n):
    laptop = device(project, authority, "laptop")
    build_study(laptop)
    laptop.commit()
    connect(laptop)
    for i in range(n):
        laptop.record_svc.add("study", "encounter", {"site": f"n{i}", "depth": 1.0})
    laptop.commit()
    laptop.base = len(snapshots(authority)["record"])
    return laptop


def _wrap_push(monkeypatch, wrap):
    sent: list[int] = []
    real = sync_service.SyncService._transport

    def transport(self):
        t = real(self)
        push = t.push

        def counting(entries):
            sent.append(len(entries))
            return wrap(push, entries)

        t.push = counting
        return t

    monkeypatch.setattr(sync_service.SyncService, "_transport", transport)
    return sent


def test_a_tiny_byte_budget_sends_one_action_a_request_and_all_arrive(
    project, authority, monkeypatch
):
    laptop = _connected_with_new_records(project, authority, 6)
    monkeypatch.setattr(sync_service, "PUSH_BUDGET_BYTES", 1)
    sent = _wrap_push(monkeypatch, lambda push, entries: push(entries))
    laptop.sync_svc.sync()
    laptop.commit()
    assert len(sent) >= 6 and all(n >= 1 for n in sent)
    assert laptop.sync_repo.count_pending() == 0
    assert len(snapshots(authority)["record"]) == laptop.base + 6


def test_a_short_answer_goes_on_with_the_rest_in_the_same_pass(
    project, authority, monkeypatch
):
    laptop = _connected_with_new_records(project, authority, 8)
    sent = _wrap_push(monkeypatch, lambda push, entries: push(entries[:3]))
    laptop.sync_svc.sync()
    laptop.commit()
    assert sent[0] >= 8 and len(sent) >= 3
    assert laptop.sync_repo.count_pending() == 0
    assert len(snapshots(authority)["record"]) == laptop.base + 8


def test_an_answer_that_settles_nothing_ends_the_pass_not_loops(
    project, authority, monkeypatch
):
    laptop = _connected_with_new_records(project, authority, 4)
    sent = _wrap_push(monkeypatch, lambda push, entries: push([]))
    laptop.sync_svc.sync()
    assert len(sent) <= 2
    assert laptop.sync_repo.count_pending() == 4
