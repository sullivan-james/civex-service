"""A big file received in parts, by devices that race: two `begin`s for the same
file never wipe each other's parts, a `finish` that meets another one (or an
upload) is not an error, and finishing twice stores the file once."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from pathlib import Path

import pytest

from civex.config import StoreConfig, VolumeConfig
from civex.domain.exceptions import UploadBusyError, ValidationError
from civex.repositories.local.file_store import VolumeAwareFileObjectStore

PART = 1024
BODY = bytes(range(256)) * 8  # two parts of 1024
SHA = hashlib.sha256(BODY).hexdigest()


@pytest.fixture()
def store(tmp_path: Path) -> VolumeAwareFileObjectStore:
    vol = VolumeConfig(name="default", path="objects")
    config = StoreConfig(volumes={"default": vol}, volume_queue=["default"])
    return VolumeAwareFileObjectStore(config, tmp_path)


async def _chunks(data: bytes):
    yield data


def _put(store, number: int) -> None:
    part = BODY[(number - 1) * PART : number * PART]
    asyncio.run(store.put_part(SHA, number, _chunks(part)))


def test_two_begins_for_one_file_do_not_wipe_each_others_parts(store, monkeypatch):
    """The second `begin` looked, found nothing, and (while the first began and
    received its parts) went on to make the upload again: truncating the data."""
    original = store._upload_dir
    first_looked = threading.Event()
    first_may_go = threading.Event()
    calls = {"n": 0}
    lock = threading.Lock()

    def slow_look(sha256):
        found = original(sha256)
        with lock:
            calls["n"] += 1
            mine = calls["n"] == 1
        if mine:
            first_looked.set()
            first_may_go.wait(timeout=1.0)  # the other begins meanwhile
        return found

    monkeypatch.setattr(store, "_upload_dir", slow_look)
    errors: list[BaseException] = []

    def late_begin():
        try:
            store.begin_parts(SHA, len(BODY), PART)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    t = threading.Thread(target=late_begin)
    t.start()
    assert first_looked.wait(timeout=2)
    # Meanwhile another device begins, sends both parts.
    store.begin_parts(SHA, len(BODY), PART)
    _put(store, 1)
    _put(store, 2)
    first_may_go.set()
    t.join(timeout=5)
    assert not errors, errors

    ref = store.finish_parts(SHA, len(BODY), SHA)
    assert ref.sha256 == SHA and store.get(SHA) == BODY


def test_finish_is_idempotent_and_never_an_error_for_a_stored_file(store):
    store.begin_parts(SHA, len(BODY), PART)
    _put(store, 1)
    _put(store, 2)
    first = store.finish_parts(SHA, len(BODY), SHA)
    again = store.finish_parts(SHA, len(BODY), SHA)  # the answer was lost: asked again
    assert again.sha256 == first.sha256
    assert store.get(SHA) == BODY


def test_finish_that_never_began_is_still_refused(store):
    with pytest.raises(ValidationError):
        store.finish_parts("ab" * 32, 10, "x")


def test_concurrent_finishes_both_succeed(store):
    store.begin_parts(SHA, len(BODY), PART)
    _put(store, 1)
    _put(store, 2)
    results: list[object] = []

    def finish():
        try:
            results.append(store.finish_parts(SHA, len(BODY), SHA))
        except BaseException as e:  # noqa: BLE001
            results.append(e)

    threads = [threading.Thread(target=finish) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert len(results) == 4
    assert all(not isinstance(r, BaseException) for r in results), results
    assert store.get(SHA) == BODY


def test_a_part_that_lands_after_the_file_was_stored_is_not_an_error(store):
    store.begin_parts(SHA, len(BODY), PART)
    _put(store, 1)
    _put(store, 2)
    store.finish_parts(SHA, len(BODY), SHA)
    _put(store, 2)  # a retry that arrives late
    assert store.get(SHA) == BODY


def test_a_stale_lock_of_a_dead_process_is_taken_over(store):
    lock = store._upload_lock_path(SHA)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("999999999")  # no such process
    store.begin_parts(SHA, len(BODY), PART)  # does not wait for it
    assert not lock.exists()


def test_a_finish_does_not_start_under_a_part_being_written(store):
    store.begin_parts(SHA, len(BODY), PART)
    _put(store, 1)
    _put(store, 2)
    started, go = threading.Event(), threading.Event()

    async def slow_part():
        yield b"X" * 10  # wrong bytes, still arriving
        started.set()
        while not go.is_set():
            await asyncio.sleep(0.01)
        yield b"X" * (PART - 10)

    thread = threading.Thread(
        target=lambda: asyncio.run(store.put_part(SHA, 2, slow_part()))
    )
    thread.start()
    assert started.wait(timeout=5)
    with pytest.raises(UploadBusyError):
        store.finish_parts(SHA, len(BODY), SHA)
    go.set()
    thread.join(timeout=5)
    # the wrong bytes were a re-send of part 2: the file is not the one asked for
    with pytest.raises(ValidationError):
        store.finish_parts(SHA, len(BODY), SHA)


def test_a_part_does_not_start_under_a_finish(store, monkeypatch):
    """The finish has hashed the file; a part that now began would change the
    bytes after they were checked."""
    from civex.repositories.local import file_store

    store.begin_parts(SHA, len(BODY), PART)
    _put(store, 1)
    _put(store, 2)
    hashed, release = threading.Event(), threading.Event()
    real = file_store._hash_file

    def slow_hash(path, job=None):
        digest = real(path, job)
        hashed.set()
        release.wait(timeout=5)
        return digest

    monkeypatch.setattr(file_store, "_hash_file", slow_hash)
    thread = threading.Thread(target=lambda: store.finish_parts(SHA, len(BODY), SHA))
    thread.start()
    assert hashed.wait(timeout=5)
    with pytest.raises(UploadBusyError):
        asyncio.run(store.put_part(SHA, 2, _chunks(b"X" * PART)))
    release.set()
    thread.join(timeout=5)
    assert store.get(SHA) == BODY


def test_the_lock_is_shared_by_stores_that_only_share_a_volume(tmp_path, monkeypatch):
    """A host may give each process its own project root: what they share is
    the volume, so that is where the lock is."""
    from civex.repositories.local import file_store

    shared = tmp_path / "shared"
    shared.mkdir()
    config = StoreConfig(
        volumes={"v": VolumeConfig(name="v", path=str(shared))}, volume_queue=["v"]
    )
    (tmp_path / "root-one").mkdir()
    (tmp_path / "root-two").mkdir()
    one = VolumeAwareFileObjectStore(config, tmp_path / "root-one")
    two = VolumeAwareFileObjectStore(config, tmp_path / "root-two")
    monkeypatch.setattr(file_store, "_UPLOAD_LOCK_WAIT_SECONDS", 0.3)
    with one._upload_lock(SHA):
        with pytest.raises(UploadBusyError):
            two.begin_parts(SHA, len(BODY), PART)
    two.begin_parts(SHA, len(BODY), PART)  # released: no wait


def _begin_in_a_process(root: str, shared: str):
    Path(root).mkdir(parents=True, exist_ok=True)
    config = StoreConfig(
        volumes={"v": VolumeConfig(name="v", path=shared)}, volume_queue=["v"]
    )
    return VolumeAwareFileObjectStore(config, Path(root)).begin_parts(
        SHA, len(BODY), PART
    )


def test_begins_from_several_processes_make_one_upload(tmp_path):
    import multiprocessing as mp

    shared = tmp_path / "shared"
    shared.mkdir()
    with mp.get_context("spawn").Pool(4) as pool:
        answers = pool.starmap(
            _begin_in_a_process,
            [(str(tmp_path / f"root-{i}"), str(shared)) for i in range(4)],
        )
    assert answers == [(PART, [])] * 4
    uploads = list((shared / ".tmp").glob("*.upload"))
    assert len(uploads) == 1 and (uploads[0] / "data").stat().st_size == len(BODY)
