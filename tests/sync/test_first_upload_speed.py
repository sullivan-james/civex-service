"""A first upload is quick and keeps what it has done: an interrupted seed
resumes after what the authority answered (not from the start), records go in
big batches, and files go several at a time when small, alone when large, each
group kept even when a later one fails."""

from __future__ import annotations

import dataclasses
import threading
import time
import urllib.request

import pytest

from civex.domain.sync import SyncError
from civex.services import sync_service
from civex.db.models import Record, SeedAck

from civex.testing.peers import build_study, connect, device


def _laptop_with_records(project, authority, n):
    laptop = device(project, authority, "laptop")
    build_study(laptop)
    for i in range(n):
        laptop.record_svc.add("study", "encounter", {"site": f"s{i}", "depth": 1.0})
    laptop.commit()
    return laptop


def _count_pushes(monkeypatch):
    sent: list[int] = []
    real = sync_service.SyncService._transport

    def transport(self):
        t = real(self)
        push = t.push

        def counting(entries):
            sent.append(len(entries))
            return push(entries)

        t.push = counting
        return t

    monkeypatch.setattr(sync_service.SyncService, "_transport", transport)
    return sent


def test_a_resumed_seed_skips_what_the_authority_answered(
    project, authority, monkeypatch
):
    monkeypatch.setattr(sync_service, "PUSH_BATCH", 5)
    laptop = _laptop_with_records(project, authority, 30)
    original = sync_service.SyncService._seed
    calls = {"n": 0}

    def seed_then_stop(self, transport, *rest, **kw):
        real = transport.push

        def push(entries):
            calls["n"] += 1
            if calls["n"] == 4:
                raise SyncError("connection lost", retryable=True)
            return real(entries)

        transport.push = push
        try:
            return original(self, transport, *rest, **kw)
        finally:
            del transport.push

    monkeypatch.setattr(sync_service.SyncService, "_seed", seed_then_stop)
    with pytest.raises(SyncError):
        connect(laptop)
    monkeypatch.setattr(sync_service.SyncService, "_seed", original)
    acked = laptop.sync_repo.seed_acked()
    assert len(acked) == 15  # three pushes of five were answered, and kept

    sent = _count_pushes(monkeypatch)
    laptop.sync_svc.sync()
    everything = laptop.sync_repo.entity_count()
    assert sum(sent) <= everything - 15  # the answered ones did not go again
    assert laptop.sync_svc.status().seeding == 0
    assert laptop.sync_repo._s.query(SeedAck).count() == 0  # cleared when done
    assert {r.id for r in authority.sync_repo._s.query(Record)} == {
        r.id for r in laptop.sync_repo._s.query(Record)
    }
    # and it is done: another sync sends nothing
    sent.clear()
    laptop.sync_svc.sync()
    assert sum(sent) == 0


def test_a_seed_goes_in_big_batches(project, authority, monkeypatch):
    laptop = _laptop_with_records(project, authority, 120)
    sent = _count_pushes(monkeypatch)
    connect(laptop)
    assert 100 < sync_service.PUSH_BATCH <= 500
    assert max(sent) > 100
    assert max(sent) <= sync_service.PUSH_BATCH


class _FileDevice:
    """A device holding records with files, and a transport that watches
    uploads and confirmations."""

    def __init__(self, project, authority, monkeypatch, sizes):
        self.laptop = device(project, authority, "laptop")
        build_study(self.laptop)
        self.laptop.schema_svc.add_field("encounter", "scan", "file")
        self.laptop.commit()
        self.shas: list[str] = []
        for i, size in enumerate(sizes):
            ref = self.laptop.file_svc.store_bytes(
                (f"{i}:".encode() * (size // 3 + 1))[:size], f"f{i}.bin"
            )
            self.laptop.record_svc.add(
                "study", "encounter", {"site": f"s{i}", "scan": ref.to_dict()}
            )
            self.shas.append(ref.sha256)
        self.laptop.commit()
        connect(self.laptop)
        self.log: list[tuple] = []  # ("upload", sha, threads) / ("confirm", n)
        self.active = 0
        self.peak = 0
        self.lock = threading.Lock()
        self.fail_on: set[str] = set()
        real = sync_service.SyncService._transport
        me = self

        def transport(self_):
            t = real(self_)
            upload = t.upload_file
            t.upload_threads = me.threads

            def counting(sha, source, size):
                with me.lock:
                    me.active += 1
                    me.peak = max(me.peak, me.active)
                    me.log.append(("upload", sha, size))
                try:
                    time.sleep(0.02)
                    if sha in me.fail_on:
                        raise SyncError("rate limited", retryable=True, status=429)
                    if threading.current_thread() is not threading.main_thread():
                        source.read()  # the in-process authority is not for threads
                        return None
                    return upload(sha, source, size)
                finally:
                    with me.lock:
                        me.active -= 1

            t.upload_file = counting
            return t

        self.threads = 4
        monkeypatch.setattr(sync_service.SyncService, "_transport", transport)
        repo = type(self.laptop.sync_repo)
        real_confirm = repo.confirm_on_server

        def confirm(self_, shas):
            shas = list(shas)
            me.log.append(("confirm", len(shas), frozenset(shas)))
            return real_confirm(self_, shas)

        monkeypatch.setattr(repo, "confirm_on_server", confirm)

    def confirmed(self):
        return {s for e in self.log if e[0] == "confirm" for s in e[2]}


def test_small_files_go_in_parallel_and_are_confirmed_in_groups(
    project, authority, monkeypatch
):
    d = _FileDevice(project, authority, monkeypatch, [1000 + i for i in range(40)])
    report = d.laptop.sync_svc.send_files()
    assert report.sent == 40
    assert d.peak > 1  # several at once
    uploads = [e for e in d.log if e[0] == "upload"]
    uploaded_shas = {e[1] for e in uploads}
    assert uploaded_shas == set(d.shas)
    confirms = [e for e in d.log if e[0] == "confirm" and e[1] and len(e[2]) > 1]
    assert confirms  # grouped, not one by one
    assert d.laptop.sync_svc.status().files_to_send == 0


def test_a_large_file_is_sent_alone_and_confirmed_at_once(
    project, authority, monkeypatch
):
    monkeypatch.setattr(sync_service, "LARGE_FILE_BYTES", 5000)
    d = _FileDevice(project, authority, monkeypatch, [100, 200, 300, 9000, 400, 500])
    big = d.shas[3]
    d.laptop.sync_svc.send_files()
    events = [e for e in d.log if e[0] == "upload" or (e[0] == "confirm" and e[1])]
    at = next(i for i, e in enumerate(events) if e[0] == "upload" and e[1] == big)
    # Everything sent before it was confirmed before it began (it never shares
    # a group), and it is confirmed on its own before anything else goes.
    earlier = {e[1] for e in events[:at] if e[0] == "upload"}
    confirmed_before = {s for e in events[:at] if e[0] == "confirm" for s in e[2]}
    assert earlier == confirmed_before
    assert events[at + 1][0] == "confirm" and events[at + 1][2] == frozenset({big})
    assert d.laptop.sync_svc.status().files_to_send == 0


def test_a_failure_in_a_group_keeps_the_files_that_arrived(
    project, authority, monkeypatch
):
    d = _FileDevice(project, authority, monkeypatch, [1000 + i for i in range(12)])
    d.fail_on = {sorted(d.shas)[7]}
    with pytest.raises(SyncError):
        d.laptop.sync_svc.send_files()
    kept = d.confirmed()
    assert sorted(d.shas)[7] not in kept
    assert len(kept) >= 1
    left = d.laptop.sync_svc.status().files_to_send
    assert left == 12 - len(kept)
    d.fail_on = set()
    d.laptop.sync_svc.send_files()
    assert d.laptop.sync_svc.status().files_to_send == 0


def test_a_failure_with_one_thread_keeps_the_files_that_arrived(
    project, authority, monkeypatch
):
    d = _FileDevice(project, authority, monkeypatch, [1000 + i for i in range(6)])
    d.threads = 1
    d.fail_on = {sorted(d.shas)[4]}
    with pytest.raises(SyncError):
        d.laptop.sync_svc.send_files()
    assert len(d.confirmed()) == 4
    assert d.laptop.sync_svc.status().files_to_send == 2


def _interrupted_seed(project, authority, monkeypatch):
    """A laptop whose first upload answered three pushes of five, then lost
    the connection."""
    monkeypatch.setattr(sync_service, "PUSH_BATCH", 5)
    laptop = _laptop_with_records(project, authority, 30)
    original = sync_service.SyncService._seed
    calls = {"n": 0}

    def seed_then_stop(self, transport, *rest, **kw):
        real = transport.push

        def push(entries):
            calls["n"] += 1
            if calls["n"] == 4:
                raise SyncError("connection lost", retryable=True)
            return real(entries)

        transport.push = push
        try:
            return original(self, transport, *rest, **kw)
        finally:
            del transport.push

    monkeypatch.setattr(sync_service.SyncService, "_seed", seed_then_stop)
    with pytest.raises(SyncError):
        connect(laptop)
    monkeypatch.setattr(sync_service.SyncService, "_seed", original)
    assert len(laptop.sync_repo.seed_acked()) == 15
    return laptop


def _seed_again(laptop, monkeypatch, **hello_changes):
    """Run the seed again against an authority whose hello says otherwise;
    returns how many entries were pushed."""
    sent = _count_pushes(monkeypatch)
    transport = laptop.sync_svc._transport()
    real = transport.hello
    transport.hello = lambda: dataclasses.replace(real(), **hello_changes)
    laptop.sync_svc._seed(transport)
    return sum(sent)


def test_seed_acks_are_dropped_when_the_authority_is_empty(
    project, authority, monkeypatch
):
    laptop = _interrupted_seed(project, authority, monkeypatch)
    total = laptop.sync_repo.entity_count()
    assert _seed_again(laptop, monkeypatch, empty=True) >= total


def test_seed_acks_are_dropped_when_the_authority_went_backwards(
    project, authority, monkeypatch
):
    # Restored from a backup taken mid-seed: not empty, still listing this
    # device, but behind where it was when it answered.
    laptop = _interrupted_seed(project, authority, monkeypatch)
    total = laptop.sync_repo.entity_count()
    head = laptop.sync_repo.seed_acked_head()
    assert head > 0
    sent = _seed_again(
        laptop, monkeypatch, empty=False, head_seq=head - 1, seeded_by="x"
    )
    assert sent >= total


def test_seed_acks_are_kept_when_the_authority_has_not_gone_back(
    project, authority, monkeypatch
):
    laptop = _interrupted_seed(project, authority, monkeypatch)
    total = laptop.sync_repo.entity_count()
    assert _seed_again(laptop, monkeypatch) <= total - 15


def test_following_another_authority_forgets_seed_acks(project, authority, monkeypatch):
    laptop = _interrupted_seed(project, authority, monkeypatch)
    laptop.sync_repo.forget_numbers()
    assert laptop.sync_repo.seed_acked() == set()


def test_a_401_during_parallel_uploads_signs_in_once_more_and_confirms_all(
    monkeypatch,
):
    import io

    from civex.services.sync_transport import HttpSyncTransport

    t = HttpSyncTransport.__new__(HttpSyncTransport)
    t._session_lock = threading.RLock()
    t._session = object()
    t._base = "http://x"
    t._capabilities = frozenset()
    signins = {"n": 0}
    rejected: set[int] = set()
    barrier = threading.Barrier(4)

    def token():
        with t._session_lock:
            if t._session is None:
                signins["n"] += 1
                t._session = object()
            return "tok"

    t._token = token
    t._offers = lambda _c: False
    t._signed_in = lambda m, path, data=None: urllib.request.Request(
        "http://x" + path, data=data, method=m
    )
    sent: list[str] = []
    lock = threading.Lock()

    class _Open:
        def close(self):
            pass

    def opened(request):
        sha = request.full_url.rsplit("/", 1)[1]
        token()
        with lock:
            first = sha not in rejected
            rejected.add(sha)
        if first:
            try:
                barrier.wait(2)
            except threading.BrokenBarrierError:
                pass
            raise SyncError("expired", retryable=False, status=401)
        with lock:
            sent.append(sha)
        return _Open()

    t._open = opened
    shas = [f"{i:064x}" for i in range(4)]
    threads = [
        threading.Thread(target=t.upload_file, args=(sha, io.BytesIO(b"x"), 1))
        for sha in shas
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert sorted(sent) == sorted(shas)  # every file went in the end
    assert signins["n"] == 1  # one sign-in again, shared by all four


def test_a_seed_reads_the_newest_stamp_once_not_per_entry(
    project, authority, monkeypatch
):
    monkeypatch.setattr(sync_service, "PUSH_BATCH", 5)
    laptop = _laptop_with_records(project, authority, 30)
    repo = type(laptop.sync_repo)
    real = repo.latest_hlc
    calls = {"n": 0}

    def counting(self_):
        calls["n"] += 1
        return real(self_)

    monkeypatch.setattr(repo, "latest_hlc", counting)
    connect(laptop)
    assert laptop.sync_repo.entity_count() > 30
    assert calls["n"] <= 5  # not one per entry
