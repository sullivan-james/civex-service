"""Files come down the way they go up: small ones many to a request (a pack),
a big one in ranges several at a time, each checked against its hash. The real
client against the real server over a socket."""

from __future__ import annotations

import asyncio
import dataclasses
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from civex.config import load_config, save_config
from civex.context import build_context
from civex.domain import permissions as p
from civex.domain.permissions import Permissions
from civex.domain.sync import FILE_PACK_DOWNLOADS, SyncError
from civex.server.routers import sync_peer
from civex.services import sync_transport
from civex.services.sync_transport import HttpSyncTransport
from civex.testing import serve
from civex.testing.peers import build_study


@pytest.fixture()
def server(project, tmp_path: Path) -> Iterator[tuple[str, list[str], object]]:
    authority = project("authority")
    root = tmp_path / "authority"
    previous = os.getcwd()
    os.chdir(root)
    config = load_config()
    config.sync.serve = True
    save_config(config)
    invites = [authority.device_keys.invite(n)[1] for n in ("laptop", "phone")]
    authority.commit()

    from civex.server.app import create_app

    try:
        with serve(create_app()) as url:
            yield url, invites, authority
    finally:
        os.chdir(previous)


def _content(i: int, size: int) -> bytes:
    return (f"{i}:".encode() * (size // 2 + 1))[:size]


def _phone(project, server, sizes: list[int]):
    """A laptop that has sent files of these sizes, and a phone that has the
    records and none of the files."""
    url, (laptop_invite, phone_invite), _ = server
    laptop = project("laptop")
    build_study(laptop)
    laptop.schema_svc.add_field("encounter", "scan", "file")
    files = {}
    for i, size in enumerate(sizes):
        ref = laptop.file_svc.store_bytes(_content(i, size), f"f{i}.bin")
        laptop.record_svc.add(
            "study", "encounter", {"site": f"s{i}", "scan": ref.to_dict()}
        )
        files[ref.sha256] = _content(i, size)
    laptop.commit()
    laptop.sync_svc.connect(url, laptop_invite)
    laptop.commit()
    laptop.sync_svc.sync()
    laptop.sync_svc.send_files()
    laptop.commit()
    phone = project("phone")
    phone.sync_svc.connect(url, phone_invite)
    phone.commit()
    phone.sync_svc.sync()
    phone.commit()
    phone.sync_svc.set_download_files("all")
    phone.commit()
    return phone, files


def _spy(monkeypatch):
    calls = {"pack": [], "alone": [], "ranges": []}
    real_pack = HttpSyncTransport.fetch_pack
    real_open = HttpSyncTransport._open_file

    def pack(self, shas, stop=None):
        calls["pack"].append(list(shas))
        return real_pack(self, shas, stop)

    def opened(self, sha, byte_range=None):
        calls["ranges" if byte_range else "alone"].append((sha, byte_range))
        return real_open(self, sha, byte_range)

    monkeypatch.setattr(HttpSyncTransport, "fetch_pack", pack)
    monkeypatch.setattr(HttpSyncTransport, "_open_file", opened)
    return calls


def _all_there(phone, files):
    for sha, content in files.items():
        assert phone.file_svc.retrieve(sha) == content
    assert phone.sync_svc.files_missing() == 0


def test_small_files_come_many_to_a_request(project, server, monkeypatch):
    monkeypatch.setattr(sync_peer, "PACK_DOWNLOAD_FILE_MAX", 5000)
    monkeypatch.setattr("civex.services.sync_service.PACK_DOWNLOAD_FILES", 10)
    calls = _spy(monkeypatch)
    sizes = [3000 + i for i in range(35)] + [9000]  # the last is too big for a pack
    phone, files = _phone(project, server, sizes)
    report = phone.sync_svc.fetch_files()
    phone.commit()
    assert report.fetched == 36 and not report.absent
    # Thirty-six files asked for in packs; only the one too big comes alone.
    assert sum(len(c) for c in calls["pack"]) == 36
    assert len(calls["alone"]) == 1
    _all_there(phone, files)


def test_a_big_file_comes_in_ranges_and_is_checked_whole(project, server, monkeypatch):
    monkeypatch.setattr(sync_peer, "PACK_DOWNLOAD_FILE_MAX", 5000)
    monkeypatch.setattr(sync_transport, "DOWNLOAD_PART_BYTES", 64 * 1024)
    monkeypatch.setattr(sync_transport, "DOWNLOAD_PARTS_MIN_BYTES", 128 * 1024)
    calls = _spy(monkeypatch)
    phone, files = _phone(project, server, [1000, 700_001])
    report = phone.sync_svc.fetch_files()
    phone.commit()
    assert report.fetched == 2
    assert len(calls["ranges"]) == 11  # 700001 bytes in parts of 64 KiB
    assert {r for _, r in calls["ranges"]} == {
        (i * 65536, min(700_001, (i + 1) * 65536) - 1) for i in range(11)
    }
    _all_there(phone, files)


def test_a_range_that_comes_back_wrong_is_asked_again(project, server, monkeypatch):
    monkeypatch.setattr(sync_peer, "PACK_DOWNLOAD_FILE_MAX", 5000)
    monkeypatch.setattr(sync_transport, "DOWNLOAD_PART_BYTES", 64 * 1024)
    monkeypatch.setattr(sync_transport, "DOWNLOAD_PARTS_MIN_BYTES", 128 * 1024)
    real = HttpSyncTransport._open_file
    failed = []

    def flaky(self, sha, byte_range=None):
        reply = real(self, sha, byte_range)
        if byte_range and byte_range[0] == 65536 and not failed:
            failed.append(1)
            reply.close()
            raise SyncError("the line dropped", retryable=True)
        return reply

    monkeypatch.setattr(HttpSyncTransport, "_open_file", flaky)
    phone, files = _phone(project, server, [300_000])
    phone.sync_svc.fetch_files()
    phone.commit()
    assert failed
    _all_there(phone, files)


def test_an_authority_without_packs_is_asked_one_by_one(project, server, monkeypatch):
    real = HttpSyncTransport._offers
    monkeypatch.setattr(
        HttpSyncTransport,
        "_offers",
        lambda self, c: False if c == FILE_PACK_DOWNLOADS else real(self, c),
    )
    calls = _spy(monkeypatch)
    phone, files = _phone(project, server, [2000 + i for i in range(8)])
    report = phone.sync_svc.fetch_files()
    phone.commit()
    assert report.fetched == 8 and calls["pack"] == []
    assert len(calls["alone"]) == 8
    _all_there(phone, files)


def test_a_route_the_authority_refuses_falls_back_and_is_not_asked_again(
    project, server, monkeypatch
):
    real = HttpSyncTransport._call

    def call(self, method, path, **kw):
        if path.endswith("/files/pack/download"):
            raise SyncError("no", retryable=False, status=404)
        return real(self, method, path, **kw)

    monkeypatch.setattr(HttpSyncTransport, "_call", call)
    calls = _spy(monkeypatch)
    phone, files = _phone(project, server, [2000 + i for i in range(8)])
    phone.sync_svc.fetch_files()
    phone.commit()
    assert len(calls["pack"]) == 1  # asked once, then one by one
    assert len(calls["alone"]) == 8
    _all_there(phone, files)


class _Cut:
    """A reply whose body ends after `limit` bytes, as a dropped line does."""

    def __init__(self, reply, limit, flip=None):
        self._reply, self._left, self._flip, self._at = reply, limit, flip, 0

    def read(self, n=-1):
        data = self._reply.read(n if n > 0 else 65536)[: self._left]
        self._left -= len(data)
        if self._flip is not None and self._at <= self._flip < self._at + len(data):
            i = self._flip - self._at
            data = data[:i] + bytes([data[i] ^ 0xFF]) + data[i + 1 :]
        self._at += len(data)
        return data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._reply.close()


def _damage(monkeypatch, **kw):
    real = sync_transport._FrameReader.__init__

    def init(self, reply):
        real(self, _Cut(reply, **kw))

    monkeypatch.setattr(sync_transport._FrameReader, "__init__", init)


def test_a_pack_cut_short_keeps_what_arrived_and_the_rest_comes_alone(
    project, server, monkeypatch
):
    _damage(monkeypatch, limit=3 * 2100 + 400)
    calls = _spy(monkeypatch)
    phone, files = _phone(project, server, [2000 + i for i in range(10)])
    report = phone.sync_svc.fetch_files()
    phone.commit()
    assert report.fetched == 10 and not report.absent
    assert 0 < len(calls["alone"]) < 10
    _all_there(phone, files)


def test_a_pack_with_a_corrupt_file_is_refused_by_its_hash(
    project, server, monkeypatch
):
    _damage(monkeypatch, limit=10**9, flip=200)  # a byte inside a file
    phone, files = _phone(project, server, [2000 + i for i in range(10)])
    with pytest.raises(SyncError, match="wrong content"):
        phone.sync_svc.fetch_files()
    phone.commit()
    for sha, content in files.items():  # nothing half-written is kept
        if phone.file_svc.exists(sha):
            assert phone.file_svc.retrieve(sha) == content
    assert not all(phone.file_svc.exists(s) for s in files)


def test_stopping_mid_download_confirms_only_whole_files(project, server, monkeypatch):
    monkeypatch.setattr(sync_peer, "PACK_DOWNLOAD_FILE_MAX", 5000)
    monkeypatch.setattr(sync_transport, "DOWNLOAD_PART_BYTES", 64 * 1024)
    monkeypatch.setattr(sync_transport, "DOWNLOAD_PARTS_MIN_BYTES", 128 * 1024)
    phone, files = _phone(project, server, [1500 + i for i in range(6)] + [600_000])

    def stop_after_two(done: int) -> None:
        if done == 2:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        phone.sync_svc.fetch_files(progress=stop_after_two)
    phone.commit()
    have = [s for s in files if phone.file_svc.exists(s)]
    assert have
    for sha in have:
        assert phone.file_svc.retrieve(sha) == files[sha]
    # And a second pass finishes the job.
    phone.sync_svc.fetch_files()
    phone.commit()
    _all_there(phone, files)


def test_a_hidden_collections_file_is_never_in_a_pack(project, authority):
    authority.schema_svc.create("encounter")
    authority.schema_svc.add_field("encounter", "scan", "file")
    shown = authority.dataset_svc.create("open")
    hidden = authority.dataset_svc.create("vault")
    refs = {}
    for name, ds in (("open", shown), ("vault", hidden)):
        ref = authority.file_svc.store_bytes(f"{name} bytes".encode(), f"{name}.bin")
        authority.record_svc.add(name, "encounter", {"scan": ref.to_dict()})
        refs[name] = ref.sha256
    authority.commit()
    perms = Permissions.of(
        p.READ,
        collections=(shown.id,),
        read_collections=(shown.id,),
    )
    ctx = build_context(dataclasses.replace(authority.project, permissions=perms))
    unknown = "e" * 64
    asked = sync_peer.SyncPackAsk(sha256=[refs["open"], refs["vault"], unknown])
    response = sync_peer.download_pack(
        asked,
        sync_peer.Peer(ctx=ctx, who=None, protocol=0),  # type: ignore[arg-type]
    )

    async def read() -> bytes:
        return b"".join([c async for c in response.body_iterator])  # type: ignore[union-attr]

    body = asyncio.run(read())
    assert b"vault bytes" not in body
    assert f"{refs['vault']} absent\n".encode() in body
    assert f"{unknown} absent\n".encode() in body  # the same answer as no file
    assert f"{refs['open']} 10\nopen bytes".encode() in body
    assert response.headers["content-length"] == str(len(body))
