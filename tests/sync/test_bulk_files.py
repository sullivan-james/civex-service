"""Files fill a fast line: small ones go many to a request (a pack), a big one
in numbered parts several at a time, each kept as it arrives. The real client
against the real server over a socket."""

from __future__ import annotations

import io
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from civex.config import load_config, save_config
from civex.domain import sync as sync_domain
from civex.domain.dtos import FileRef
from civex.domain.exceptions import VolumeUnavailableError
from civex.services import sync_service, sync_transport
from civex.services.file_service import FileService
from civex.services.sync_transport import HttpSyncTransport

from civex.testing import serve
from civex.testing.peers import build_study


@pytest.fixture()
def server(project, tmp_path: Path) -> Iterator[tuple[str, str, object]]:
    authority = project("authority")
    root = tmp_path / "authority"
    previous = os.getcwd()
    os.chdir(root)
    config = load_config()
    config.sync.serve = True
    save_config(config)
    _, invite = authority.device_keys.invite("laptop")
    authority.commit()

    from civex.server.app import create_app

    try:
        with serve(create_app()) as url:
            yield url, invite, authority
    finally:
        os.chdir(previous)


def _content(i: int, size: int) -> bytes:
    return (f"{i}:".encode() * (size // 2 + 1))[:size]


def _laptop(project, server, sizes: list[int]):
    url, invite, _ = server
    laptop = project("laptop")
    build_study(laptop)
    laptop.schema_svc.add_field("encounter", "scan", "file")
    shas = []
    for i, size in enumerate(sizes):
        ref = laptop.file_svc.store_bytes(_content(i, size), f"f{i}.bin")
        laptop.record_svc.add(
            "study", "encounter", {"site": f"s{i}", "scan": ref.to_dict()}
        )
        shas.append(ref.sha256)
    laptop.commit()
    laptop.sync_svc.connect(url, invite)
    laptop.commit()
    laptop.sync_svc.sync()
    return laptop, shas


def _spy(monkeypatch):
    calls = {"pack": [], "file": [], "parts": []}
    real_pack = HttpSyncTransport.upload_pack
    real_file = HttpSyncTransport.upload_file
    real_parts = HttpSyncTransport._upload_parts

    def pack(self, items):
        calls["pack"].append([(sha, size) for sha, _, size in items])
        return real_pack(self, items)

    def one(self, sha, source, size):
        calls["file"].append((sha, size))
        return real_file(self, sha, source, size)

    def parts(self, sha, source, size):
        calls["parts"].append((sha, size))
        return real_parts(self, sha, source, size)

    monkeypatch.setattr(HttpSyncTransport, "upload_pack", pack)
    monkeypatch.setattr(HttpSyncTransport, "upload_file", one)
    monkeypatch.setattr(HttpSyncTransport, "_upload_parts", parts)
    return calls


def test_small_files_go_many_to_a_request(project, server, monkeypatch):
    monkeypatch.setattr(sync_service, "PACK_FILES", 10)
    calls = _spy(monkeypatch)
    laptop, shas = _laptop(project, server, [3000 + i for i in range(35)])
    report = laptop.sync_svc.send_files()
    laptop.commit()
    assert report.sent == 35 and not report.owed
    assert calls["file"] == []  # not one request each
    assert sorted(len(p) for p in calls["pack"]) == [5, 10, 10, 10]
    authority = server[2]
    for i, sha in enumerate(shas):
        assert authority.file_svc.retrieve(sha) == _content(i, 3000 + i)
    assert laptop.sync_svc.status().files_to_send == 0


def test_a_pack_that_partly_fails_keeps_what_arrived(project, server, monkeypatch):
    laptop, shas = _laptop(project, server, [2000 + i for i in range(12)])
    bad = shas[4]
    real = FileService.store_stream

    async def store(self, chunks, filename, size_hint=None, collection_id=None):
        if filename == bad:
            async for _ in chunks:
                pass
            return FileRef(sha256="0" * 64, filename="x", size=1)  # not its hash
        return await real(self, chunks, filename, size_hint, collection_id)

    monkeypatch.setattr(FileService, "store_stream", store)
    report = laptop.sync_svc.send_files()
    laptop.commit()
    authority = server[2]
    assert report.sent == 11
    assert report.owed == [bad]
    assert not authority.file_svc.exists(bad)
    assert all(authority.file_svc.exists(s) for s in shas if s != bad)
    # Only the refused one is still to send.
    assert laptop.sync_svc.status().files_to_send == 1


def test_a_full_drive_refuses_the_pack_and_the_sender_backs_off(
    project, server, monkeypatch
):
    laptop, shas = _laptop(project, server, [2000 + i for i in range(5)])

    async def full(self, chunks, filename, size_hint=None, collection_id=None):
        raise VolumeUnavailableError("the drive is full")

    monkeypatch.setattr(FileService, "store_stream", full)
    with pytest.raises(sync_domain.SyncError) as e:
        laptop.sync_svc.send_files()
    assert e.value.retryable and e.value.status == 507


def test_a_file_whose_bytes_do_not_match_is_refused_alone(project, server):
    laptop, shas = _laptop(project, server, [100, 200, 300])
    transport = laptop.sync_svc._transport()
    items = [
        (shas[0], io.BytesIO(_content(0, 100)), 100),
        ("a" * 64, io.BytesIO(b"not that"), 8),
        (shas[2], io.BytesIO(_content(2, 300)), 300),
    ]
    answer = transport.upload_pack(items)
    assert answer[shas[0]] is None and answer[shas[2]] is None
    assert answer["a" * 64] is not None
    assert server[2].file_svc.exists(shas[2])


def test_an_authority_without_packs_is_sent_one_file_each(project, server, monkeypatch):
    monkeypatch.setattr(
        sync_domain,
        "CAPABILITIES",
        tuple(c for c in sync_domain.CAPABILITIES if c != sync_domain.FILE_PACKS),
    )
    calls = _spy(monkeypatch)
    laptop, shas = _laptop(project, server, [1000 + i for i in range(6)])
    report = laptop.sync_svc.send_files()
    assert report.sent == 6
    assert calls["pack"] == []
    assert len(calls["file"]) == 6
    assert all(server[2].file_svc.exists(s) for s in shas)


def test_a_huge_file_is_never_packed_and_goes_in_parts(project, server, monkeypatch):
    monkeypatch.setattr(sync_service, "LARGE_FILE_BYTES", 5000)
    monkeypatch.setattr(sync_transport, "PARTS_MIN_BYTES", 20_000)
    monkeypatch.setattr(sync_transport, "FILE_PART_BYTES", 10_000)
    monkeypatch.setattr(sync_domain, "FILE_PART_BYTES", 10_000)
    import civex.server.routers.sync_peer as peer

    monkeypatch.setattr(peer, "FILE_PART_BYTES", 10_000)
    monkeypatch.setattr(peer, "FILE_PART_MIN", 1000)
    calls = _spy(monkeypatch)
    authority_part_numbers: list[int] = []
    real_put = FileService.put_part

    async def counted(self, sha256, number, chunks):
        authority_part_numbers.append(number)
        await real_put(self, sha256, number, chunks)

    monkeypatch.setattr(FileService, "put_part", counted)
    sizes = [1000, 1001, 95_003, 1002, 1003]
    laptop, shas = _laptop(project, server, sizes)
    report = laptop.sync_svc.send_files()
    laptop.commit()
    assert report.sent == 5
    packed = [sha for pack in calls["pack"] for sha, _ in pack]
    assert shas[2] not in packed
    assert sorted(packed) == sorted(s for i, s in enumerate(shas) if i != 2)
    assert calls["parts"] == [(shas[2], 95_003)]
    assert sorted(authority_part_numbers) == list(range(1, 11))
    assert server[2].file_svc.retrieve(shas[2]) == _content(2, 95_003)


def test_an_interrupted_big_file_sends_only_the_missing_parts(
    project, server, monkeypatch
):
    monkeypatch.setattr(sync_service, "LARGE_FILE_BYTES", 5000)
    monkeypatch.setattr(sync_transport, "PARTS_MIN_BYTES", 20_000)
    monkeypatch.setattr(sync_transport, "FILE_PART_BYTES", 10_000)
    import civex.server.routers.sync_peer as peer

    monkeypatch.setattr(peer, "FILE_PART_BYTES", 10_000)
    monkeypatch.setattr(peer, "FILE_PART_MIN", 1000)
    laptop, shas = _laptop(project, server, [95_003])  # ten parts
    seen: list[int] = []
    failing = {"on": True}
    real = FileService.put_part

    async def put(self, sha256, number, chunks):
        if failing["on"] and number == 6:
            raise VolumeUnavailableError("connection dropped")
        seen.append(number)
        await real(self, sha256, number, chunks)

    monkeypatch.setattr(FileService, "put_part", put)
    with pytest.raises(sync_domain.SyncError):
        laptop.sync_svc.send_files()
    held = sorted(seen)
    assert 6 not in held and held  # the others went and stayed
    failing["on"] = False
    seen.clear()
    report = laptop.sync_svc.send_files()
    assert report.sent == 1
    assert sorted(seen) == [n for n in range(1, 11) if n not in held]
    assert server[2].file_svc.retrieve(shas[0]) == _content(0, 95_003)


def test_parts_in_memory_are_bounded():
    size, part = 40 * 1000, 1000
    live = {"now": 0, "max": 0}
    lock = threading.Lock()

    class Source(io.BytesIO):
        def read(self, n=-1):
            with lock:
                live["now"] += 1
                live["max"] = max(live["max"], live["now"])
            return super().read(n)

    def put(number: int, data: bytes) -> None:
        time.sleep(0.002)
        with lock:
            live["now"] -= 1

    sync_transport._in_parts(Source(b"x" * size), size, part, {3}, put)
    assert live["now"] == 0
    assert live["max"] <= sync_transport.PART_THREADS
