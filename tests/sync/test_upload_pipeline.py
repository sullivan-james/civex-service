# ruff: noqa: F811
"""Uploads keep the line full: no pause between slices of small files, big
files two at a time sharing one pool of parts, all of it inside one
process-wide memory budget."""

from __future__ import annotations

import io
import sys
import threading
import time

import pytest

from civex.domain import sync as sync_domain
from civex.domain.sync import SyncError
from civex.services import sync_service, sync_transport, transfer_budget
from civex.services.sync_transport import HttpSyncTransport

from tests.sync.test_bulk_files import _content, _laptop, server  # noqa: F401

MiB = transfer_budget.MiB


@pytest.fixture(autouse=True)
def fresh_budget():
    yield
    transfer_budget.reset()


# -- the budget ---------------------------------------------------------------


def test_the_budget_waits_when_spent_and_never_goes_over():
    budget = transfer_budget.TransferBudget(100)
    a = budget.acquire(60)
    got: list[int] = []
    t = threading.Thread(target=lambda: got.append(budget.acquire(60)))
    t.start()
    time.sleep(0.1)
    assert not got and budget.in_hand == 60  # waiting, nothing taken
    budget.release(a)
    t.join(2)
    assert got == [60] and budget.peak <= 100
    # More than the whole budget is charged the whole budget, and can go alone.
    budget.release(got[0])
    with budget.hold(10_000) as charged:
        assert charged == 100 and budget.in_hand == 100
    assert budget.in_hand == 0


def test_parts_of_two_files_never_hold_more_than_the_budget():
    transfer_budget.reset(3000)
    budget = transfer_budget.process_budget()
    sent: list[tuple[int, int]] = []
    lock = threading.Lock()
    live = {"now": 0, "max": 0}

    def put_for(tag: int):
        def put(number: int, data: bytes) -> None:
            with lock:
                live["now"] += 1
                live["max"] = max(live["max"], live["now"])
            time.sleep(0.003)
            with lock:
                live["now"] -= 1
                sent.append((tag, number))

        return put

    def one(tag: int) -> None:
        sync_transport._in_parts(
            io.BytesIO(b"x" * 20_000), 20_000, 1000, set(), put_for(tag)
        )

    threads = [threading.Thread(target=one, args=(i,)) for i in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert budget.peak <= 3000  # never more than 3 parts of 1000 in hand
    assert live["max"] <= 3
    assert budget.in_hand == 0
    for tag in (1, 2):  # every part of both files sent once
        assert sorted(n for t, n in sent if t == tag) == list(range(1, 21))


def test_a_failed_part_is_raised_and_a_retry_sends_only_what_is_left():
    transfer_budget.reset(4000)
    budget = transfer_budget.process_budget()
    stored: dict[int, int] = {}  # part number -> times stored
    lock = threading.Lock()
    failing = {"on": True}

    def put(number: int, data: bytes) -> None:
        time.sleep(0.002)
        if failing["on"] and number == 7:
            raise SyncError("dropped", retryable=True)
        with lock:
            stored[number] = stored.get(number, 0) + 1

    source = io.BytesIO(b"y" * 12_000)
    with pytest.raises(SyncError):
        sync_transport._in_parts(source, 12_000, 1000, set(), put)
    assert budget.in_hand == 0  # everything given back on the failure
    assert 7 not in stored and stored
    held = set(stored)
    failing["on"] = False
    sync_transport._in_parts(io.BytesIO(b"y" * 12_000), 12_000, 1000, held, put)
    assert sorted(stored) == list(range(1, 13))
    assert all(times == 1 for times in stored.values())  # none sent twice
    assert budget.in_hand == 0


def test_parts_are_read_in_order():
    transfer_budget.reset(2000)
    read_at: list[int] = []

    class Source(io.BytesIO):
        def readinto(self, b):
            read_at.append(self.tell())
            return super().readinto(b)

    sync_transport._in_parts(
        Source(b"z" * 9000), 9000, 1000, set(), lambda n, d: time.sleep(0.001)
    )
    assert read_at == sorted(read_at) and len(read_at) == 9


def test_a_part_size_cuts_a_middling_file_into_several_parts():
    transfer_budget.reset(128 * MiB)
    assert sync_transport._part_size_for(16 * MiB) == 4 * MiB
    assert sync_transport._part_size_for(8 * MiB + 1) == 3 * MiB
    assert sync_transport._part_size_for(2 * 1024 * MiB) == 16 * MiB
    transfer_budget.reset(64 * MiB)  # a small machine: 8 MiB parts at most
    assert sync_transport._part_size_for(2 * 1024 * MiB) == 8 * MiB


# -- sizing -------------------------------------------------------------------


def test_a_machine_with_little_ram_gets_a_smaller_budget_and_windows(monkeypatch):
    monkeypatch.setattr(transfer_budget, "total_ram_bytes", lambda: None)
    gib = 1024 * MiB
    assert transfer_budget.budget_bytes(ram=16 * gib, environ={}) == 128 * MiB
    assert transfer_budget.budget_bytes(ram=4 * gib, environ={}) == 64 * MiB
    assert transfer_budget.budget_bytes(environ={}) == 64 * MiB  # unknown RAM
    assert (
        transfer_budget.budget_bytes(
            ram=4 * gib, environ={"CIVEX_SYNC_MEMORY_MB": "256"}
        )
        == 256 * MiB
    )
    big = transfer_budget.windows_for(128 * MiB)
    small = transfer_budget.windows_for(64 * MiB)
    assert not big.small and small.small
    assert small.part_bytes < big.part_bytes
    assert small.part_threads < big.part_threads
    assert small.packs < big.packs
    # What the windows can hold at once fits their budget.
    for w in (big, small):
        # parts and packs in flight, all full, fit the budget
        assert w.held_bytes <= w.budget_bytes
    assert big.held_bytes == 104 * MiB and small.held_bytes == 36 * MiB


def test_a_bad_size_or_a_container_limit_is_handled(monkeypatch):
    gib = 1024 * MiB
    for text in ("inf", "nan", "-5", "abc", ""):
        got = transfer_budget.budget_bytes(
            ram=16 * gib, environ={"CIVEX_SYNC_MEMORY_MB": text}
        )
        assert got == 128 * MiB
    if sys.platform.startswith("linux"):
        monkeypatch.setattr(transfer_budget, "_cgroup_limit", lambda: 2 * gib)
        ram = transfer_budget.total_ram_bytes()
        assert ram is not None and ram <= 2 * gib  # the container, not the host


def test_the_machines_ram_is_found():
    ram = transfer_budget.total_ram_bytes()
    assert ram is None or ram > 64 * MiB


def test_a_spool_stays_in_memory_when_small_and_goes_to_disk_when_large():
    with transfer_budget.spool() as f:
        f.write(b"a" * 1000)
        assert not f._rolled  # type: ignore[attr-defined]
        f.write(b"b" * (transfer_budget.SPOOL_BYTES + 1))
        assert f._rolled  # type: ignore[attr-defined]


# -- no pause between slices ---------------------------------------------------


def test_the_next_slice_is_asked_about_while_packs_are_on_their_way(
    project,
    server,
    monkeypatch,
):
    monkeypatch.setattr(sync_service, "PACKED_CHECK_PAGE", 6)
    monkeypatch.setattr(sync_service, "FILE_CHECK_PAGE", 6)
    monkeypatch.setattr(sync_service, "PACK_FILES", 3)
    in_flight = {"now": 0, "asked_during": 0}
    lock = threading.Lock()
    real_pack = HttpSyncTransport.upload_pack
    real_missing = HttpSyncTransport.missing_files
    sent: list[str] = []

    def pack(self, items):
        with lock:
            in_flight["now"] += 1
            sent.extend(sha for sha, _, _ in items)
        time.sleep(0.15)
        try:
            return real_pack(self, items)
        finally:
            with lock:
                in_flight["now"] -= 1

    def missing(self, shas):
        with lock:
            if in_flight["now"]:
                in_flight["asked_during"] += 1
        return real_missing(self, shas)

    monkeypatch.setattr(HttpSyncTransport, "upload_pack", pack)
    monkeypatch.setattr(HttpSyncTransport, "missing_files", missing)
    laptop, shas = _laptop(project, server, [2000 + i for i in range(30)])
    report = laptop.sync_svc.send_files()
    laptop.commit()
    assert report.sent == 30 and not report.owed
    assert in_flight["asked_during"] >= 1
    assert sorted(sent) == sorted(shas)  # each file sent once: none twice, none left
    assert all(server[2].file_svc.exists(s) for s in shas)
    assert laptop.sync_svc.status().files_to_send == 0
    assert transfer_budget.process_budget().in_hand == 0


# -- big files in lanes ---------------------------------------------------------


def _small_parts(monkeypatch):
    import civex.server.routers.sync_peer as peer

    monkeypatch.setattr(sync_service, "LARGE_FILE_BYTES", 5000)
    monkeypatch.setattr(sync_transport, "PARTS_MIN_BYTES", 5000)
    monkeypatch.setattr(sync_transport, "FILE_PART_BYTES", 4000)
    monkeypatch.setattr(sync_domain, "FILE_PART_BYTES", 4000)
    monkeypatch.setattr(peer, "FILE_PART_BYTES", 4000)
    monkeypatch.setattr(peer, "FILE_PART_MIN", 1000)


def test_two_big_files_go_at_once_and_share_one_pool_of_parts(
    project,
    server,
    monkeypatch,
):
    _small_parts(monkeypatch)
    transfer_budget.reset(128 * MiB)
    width = transfer_budget.windows().part_threads
    live = {"files": 0, "max_files": 0, "parts": 0, "max_parts": 0}
    lock = threading.Lock()
    real_file = HttpSyncTransport.upload_file
    real_put = HttpSyncTransport._again_if_expired

    def upload_file(self, sha, source, size):
        with lock:
            live["files"] += 1
            live["max_files"] = max(live["max_files"], live["files"])
        try:
            time.sleep(0.05)
            return real_file(self, sha, source, size)
        finally:
            with lock:
                live["files"] -= 1

    def again(self, send):
        # Every part PUT goes through here; count those that overlap.
        with lock:
            live["parts"] += 1
            live["max_parts"] = max(live["max_parts"], live["parts"])
        try:
            time.sleep(0.01)
            return real_put(self, send)
        finally:
            with lock:
                live["parts"] -= 1

    monkeypatch.setattr(HttpSyncTransport, "upload_file", upload_file)
    monkeypatch.setattr(HttpSyncTransport, "_again_if_expired", again)
    sizes = [30_001, 30_002, 30_003, 30_004, 1000]
    laptop, shas = _laptop(project, server, sizes)
    report = laptop.sync_svc.send_files()
    laptop.commit()
    assert report.sent == 5 and not report.owed
    assert live["max_files"] == 2
    assert live["max_parts"] <= width + 2  # plus the begin/complete calls
    for i, sha in enumerate(shas):
        assert server[2].file_svc.retrieve(sha) == _content(i, sizes[i])
    assert transfer_budget.process_budget().in_hand == 0


def test_a_failure_mid_file_keeps_the_others_and_the_retry_sends_the_rest(
    project,
    server,
    monkeypatch,
):
    _small_parts(monkeypatch)
    from civex.domain.exceptions import VolumeUnavailableError
    from civex.services.file_service import FileService

    sizes = [30_001, 30_002, 30_003, 1000, 1001]
    laptop, shas = _laptop(project, server, sizes)
    victim = sorted(shas[:3])[1]  # the middle big file in send order
    stored: dict[tuple[str, int], int] = {}
    failing = {"on": True}
    real = FileService.put_part

    async def put(self, sha256, number, chunks):
        if failing["on"] and sha256 == victim and number == 3:
            raise VolumeUnavailableError("connection dropped")
        stored[(sha256, number)] = stored.get((sha256, number), 0) + 1
        await real(self, sha256, number, chunks)

    monkeypatch.setattr(FileService, "put_part", put)
    with pytest.raises(sync_domain.SyncError):
        laptop.sync_svc.send_files()
    laptop.commit()
    assert not server[2].file_svc.exists(victim)
    assert transfer_budget.process_budget().in_hand == 0
    failing["on"] = False
    report = laptop.sync_svc.send_files()
    laptop.commit()
    assert not report.owed
    assert all(server[2].file_svc.exists(s) for s in shas)
    assert laptop.sync_svc.status().files_to_send == 0
    # No part went twice: the retry sent only what the authority lacked.
    assert max(stored.values()) == 1


def test_parts_are_read_into_a_fixed_set_of_buffers():
    transfer_budget.reset(10_000)
    width = transfer_budget.windows().part_threads
    seen: set[int] = set()
    lock = threading.Lock()

    def put(number: int, data) -> None:
        with lock:
            seen.add(id(data.obj))  # the bytearray the part was read into
        assert bytes(data) == b"q" * len(data)
        time.sleep(0.001)

    sync_transport._in_parts(io.BytesIO(b"q" * 60_000), 60_000, 1000, set(), put)
    assert 1 <= len(seen) <= width  # 60 parts, never more buffers than slots


def test_an_upload_stops_between_parts_and_gives_everything_back():
    transfer_budget.reset(5000)
    budget = transfer_budget.process_budget()
    sent: list[int] = []

    def put(number: int, data) -> None:
        sent.append(number)

    asked = {"n": 0}

    def stop() -> bool:
        asked["n"] += 1
        return asked["n"] > 3

    with pytest.raises(sync_transport.UploadStopped):
        sync_transport._in_parts(
            io.BytesIO(b"x" * 20_000), 20_000, 1000, set(), put, stop
        )
    assert sent and len(sent) < 20  # it ended early
    assert sorted(sent) == list(range(1, len(sent) + 1))  # the first ones, in order
    assert budget.in_hand == 0


# -- stopping and failing with files in flight ----------------------------------


def _slow_packs(monkeypatch, delay=0.1, fail=None):
    """Packs that take a while; `fail(sha_list)` says which one fails."""
    real = HttpSyncTransport.upload_pack
    order: list[list[str]] = []

    def pack(self, items):
        shas = [sha for sha, _, _ in items]
        order.append(shas)
        mine = len(order)  # which to start, counted before waiting
        time.sleep(delay)
        if fail is not None and fail(shas, mine):
            raise SyncError("the line dropped", retryable=True, status=503)
        return real(self, items)

    monkeypatch.setattr(HttpSyncTransport, "upload_pack", pack)
    return order


def _small_slices(monkeypatch):
    monkeypatch.setattr(sync_service, "PACKED_CHECK_PAGE", 4)
    monkeypatch.setattr(sync_service, "FILE_CHECK_PAGE", 4)
    monkeypatch.setattr(sync_service, "PACK_FILES", 3)


def _held(authority, shas, upto):
    return [s for s in shas if s <= upto and not authority.file_svc.exists(s)]


def test_a_stop_across_a_slice_boundary_never_passes_a_file_that_is_not_there(
    project, server, monkeypatch
):
    _small_slices(monkeypatch)
    _slow_packs(monkeypatch)
    laptop, shas = _laptop(project, server, [2000 + i for i in range(30)])
    calls = {"n": 0}

    def should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] >= 2  # after the first slice

    report = laptop.sync_svc.send_files(should_stop=should_stop)
    laptop.commit()
    assert report.stopped
    assert report.resume_after  # it got somewhere
    # Everything up to the point it says it got to is on the authority.
    assert _held(server[2], shas, report.resume_after) == []
    # And the pack that was held back when it stopped was sent, not dropped.
    assert any(server[2].file_svc.exists(s) for s in shas)
    done = laptop.sync_svc.send_files(after=report.resume_after)
    laptop.commit()
    assert not done.stopped and not done.owed
    assert all(server[2].file_svc.exists(s) for s in shas)
    assert laptop.sync_svc.status().files_to_send == 0


def test_running_out_of_seconds_with_packs_in_flight_keeps_the_mark_honest(
    project, server, monkeypatch
):
    _small_slices(monkeypatch)
    _slow_packs(monkeypatch, delay=0.2)
    laptop, shas = _laptop(project, server, [2000 + i for i in range(30)])
    report = laptop.sync_svc.send_files(seconds=0.1)
    laptop.commit()
    assert report.stopped
    assert _held(server[2], shas, report.resume_after) == []
    rest = laptop.sync_svc.send_files()
    laptop.commit()
    assert not rest.owed
    assert all(server[2].file_svc.exists(s) for s in shas)


def test_a_pack_that_fails_raises_even_when_a_later_pack_arrives(
    project, server, monkeypatch
):
    _small_slices(monkeypatch)
    # The second pack to start fails (after a while); later ones go through.
    order = _slow_packs(monkeypatch, delay=0.15, fail=lambda shas, n: n == 2)
    laptop, shas = _laptop(project, server, [2000 + i for i in range(30)])
    with pytest.raises(SyncError):
        laptop.sync_svc.send_files()
    laptop.commit()
    failed = set(order[1])
    # Whatever is confirmed is really there, and the failed pack's files are
    # still to send (the mark never passes them).
    still = {s for s in shas if not server[2].file_svc.exists(s)}
    assert failed & still == failed  # none of the failed pack arrived
    assert len(still) < len(shas)  # but others did
    again = laptop.sync_svc.send_files()
    laptop.commit()
    assert not again.owed
    assert all(server[2].file_svc.exists(s) for s in shas)


def test_a_slow_big_file_does_not_hold_up_the_small_ones_behind_it(
    project, server, monkeypatch
):
    _small_parts(monkeypatch)
    monkeypatch.setattr(sync_service, "PACK_FILES", 3)
    from civex.services.file_service import FileService

    real_put = FileService.put_part

    async def slow(self, sha256, number, chunks):
        import asyncio

        await asyncio.sleep(0.15)
        await real_put(self, sha256, number, chunks)

    monkeypatch.setattr(FileService, "put_part", slow)
    sizes = [30_001] + [1000 + i for i in range(12)]
    laptop, shas = _laptop(project, server, sizes)
    big = shas[0]
    events: list[tuple[str, frozenset[str]]] = []
    repo = type(laptop.sync_repo)
    real_confirm = repo.confirm_on_server

    def confirm(self_, got):
        got = list(got)
        events.append(("confirm", frozenset(got)))
        return real_confirm(self_, got)

    monkeypatch.setattr(repo, "confirm_on_server", confirm)
    report = laptop.sync_svc.send_files()
    laptop.commit()
    assert report.sent == 13 and not report.owed
    at = next(i for i, (_, got) in enumerate(events) if big in got)
    smalls_before = {s for _, got in events[:at] for s in got if s != big}
    assert smalls_before  # some small files were kept before the big one finished


def test_a_big_file_that_cannot_be_read_is_owed_not_a_failed_pass(
    project, server, monkeypatch
):
    _small_parts(monkeypatch)
    from civex.domain.exceptions import VolumeUnavailableError

    sizes = [30_001, 30_002, 1000, 1001]
    laptop, shas = _laptop(project, server, sizes)
    victim = shas[1]
    real = HttpSyncTransport.upload_file

    def upload_file(self, sha, source, size):
        if sha == victim:
            raise VolumeUnavailableError("the drive was unplugged")
        return real(self, sha, source, size)

    monkeypatch.setattr(HttpSyncTransport, "upload_file", upload_file)
    report = laptop.sync_svc.send_files()
    laptop.commit()
    assert report.owed == [victim]
    assert report.sent == 3
    assert all(server[2].file_svc.exists(s) for s in shas if s != victim)
    assert transfer_budget.process_budget().in_hand == 0
