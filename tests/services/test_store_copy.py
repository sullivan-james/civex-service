"""Copying files by hash between two object stores (`civex.context.copy_objects`):
drives link or copy, buckets copy server-side or stream, and the destination's
inventory is kept as a normal put keeps it."""

from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path

import pytest
from civex.testing.fake_s3 import FakeS3
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civex.config import S3Config, StoreConfig, VolumeConfig
from civex.context import copy_objects
from civex.db.models import Base, StoredObject
from civex.domain.exceptions import ValidationError
from civex.repositories.local.file_store import VolumeAwareFileObjectStore
from civex.repositories.s3 import store as s3_module
from civex.repositories.s3.store import S3ObjectStore


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _drive(root: Path, session: Session | None = None) -> VolumeAwareFileObjectStore:
    root.mkdir(parents=True, exist_ok=True)
    vol = VolumeConfig(name="main", path=str(root / "objects"))
    cfg = StoreConfig(volumes={"main": vol}, volume_queue=["main"])
    (root / "objects").mkdir(exist_ok=True)
    return VolumeAwareFileObjectStore(cfg, root, session=session)


def _inventory(session: Session) -> set[str]:
    session.flush()
    return {r.sha256 for r in session.query(StoredObject).all()}


def test_drive_to_drive_hardlinks_skips_and_records(tmp_path, session):
    a, b = _drive(tmp_path / "a"), _drive(tmp_path / "b", session)
    one, two = b"one" * 100, b"two" * 100
    a.put(one, "1.txt")
    a.put(two, "2.txt")
    b.put(two, "2.txt")  # already there
    seen: list[tuple[int, int]] = []
    res = copy_objects(
        a,
        b,
        [_sha(one), _sha(two), _sha(one)],
        on_progress=lambda d, t: seen.append((d, t)),
    )
    assert (res.copied, res.skipped, res.absent) == (1, 1, [])
    assert res.methods == {"link": 1}
    assert seen == [(1, 2), (2, 2)]
    assert b.get(_sha(one)) == one
    assert (
        os.stat(a.object_path(_sha(one))).st_ino
        == os.stat(b.object_path(_sha(one))).st_ino
    )
    assert _sha(one) in _inventory(session)
    # again: nothing to do
    assert copy_objects(a, b, [_sha(one)]).skipped == 1


def test_drive_copy_when_a_link_is_impossible(tmp_path, session, monkeypatch):
    a, b = _drive(tmp_path / "a"), _drive(tmp_path / "b", session)
    data = b"x" * 5000
    a.put(data, "x")

    def no_link(*_a, **_k):
        raise OSError(errno.EXDEV, "cross-device")

    monkeypatch.setattr(os, "link", no_link)
    res = copy_objects(a, b, [_sha(data)])
    assert res.methods == {"copy": 1} and res.bytes_copied == 5000
    assert (
        os.stat(a.object_path(_sha(data))).st_ino
        != os.stat(b.object_path(_sha(data))).st_ino
    )
    assert b.get(_sha(data)) == data
    assert _sha(data) in _inventory(session)


def test_a_bad_hash_is_refused_before_anything_is_copied(tmp_path):
    a, b = _drive(tmp_path / "a"), _drive(tmp_path / "b")
    good = b"g"
    a.put(good, "g")
    for bad in ("../etc/passwd", "A" * 64, "ab" * 31, _sha(good).upper()):
        with pytest.raises(ValidationError):
            copy_objects(a, b, [_sha(good), bad])
    assert not b.exists(_sha(good))


def test_absent_sources_are_reported(tmp_path):
    a, b = _drive(tmp_path / "a"), _drive(tmp_path / "b")
    missing = _sha(b"nothing")
    res = copy_objects(a, b, [missing])
    assert res.absent == [missing] and res.copied == 0


def test_a_corrupt_drive_source_is_not_stored_under_its_name(tmp_path, monkeypatch):
    a, b = _drive(tmp_path / "a"), _drive(tmp_path / "b")
    data = b"real"
    a.put(data, "r")
    p = a.object_path(_sha(data))
    p.chmod(0o644)
    p.write_bytes(b"corrupt")

    def no_link(*_a, **_k):
        raise OSError(errno.EXDEV, "x")

    monkeypatch.setattr(os, "link", no_link)
    with pytest.raises(ValidationError):
        copy_objects(a, b, [_sha(data)])
    assert not b.exists(_sha(data))


def _bucket(fake: FakeS3, bucket: str, session=None, **kw) -> S3ObjectStore:
    return S3ObjectStore(
        S3Config(bucket=bucket, prefix="p", **kw), session=session, client=fake
    )


def test_bucket_to_bucket_copies_server_side(session):
    fake = FakeS3()
    a, b = _bucket(fake, "a"), _bucket(fake, "b", session)
    data = b"hello" * 50
    a.put(data, "h")
    fake.calls.clear()
    res = copy_objects(a, b, [_sha(data)])
    assert res.methods == {"server_side": 1}
    assert "copy_object" in fake.calls and "get_object" not in fake.calls
    assert b.get(_sha(data)) == data
    assert _sha(data) in _inventory(session)


def test_a_huge_object_is_copied_in_parts_server_side(session, monkeypatch):
    fake = FakeS3()
    a, b = _bucket(fake, "a"), _bucket(fake, "b", session)
    data = os.urandom(5 * 1024**2 + 123)
    a.put(data, "big")
    monkeypatch.setattr(s3_module, "SINGLE_PUT_MAX", 1024)
    monkeypatch.setattr(s3_module, "COPY_PART_SIZE", 2 * 1024**2)
    fake.calls.clear()
    res = copy_objects(a, b, [_sha(data)])
    assert res.methods == {"server_side": 1}
    assert fake.calls.count("upload_part_copy") == 3 and "copy_object" not in fake.calls
    assert b.get(_sha(data)) == data


@pytest.mark.parametrize("size", [300, 3 * 1024**2])
def test_other_credentials_stream_without_a_temp_file(session, monkeypatch, size):
    fake = FakeS3()
    a = _bucket(fake, "a")
    b = _bucket(fake, "b", session, profile="other")
    data = os.urandom(size)
    a.put(data, "d")
    monkeypatch.setattr(s3_module, "MULTIPART_MIN", 1024**2)
    monkeypatch.setattr(s3_module, "PART_SIZE", 1024**2)
    monkeypatch.setattr(
        "tempfile.mkstemp", lambda *a, **k: pytest.fail("a temp file was made")
    )
    fake.calls.clear()
    res = copy_objects(a, b, [_sha(data)])
    assert res.methods == {"stream": 1}
    assert "copy_object" not in fake.calls
    assert ("create_multipart_upload" in fake.calls) == (size > 1024**2)
    assert b.get(_sha(data)) == data
    assert _sha(data) in _inventory(session)


def test_a_failed_server_side_copy_falls_back_to_streaming(session):
    fake = FakeS3()
    a, b = _bucket(fake, "a"), _bucket(fake, "b", session)
    data = b"deny" * 10
    a.put(data, "d")

    def denied(**_k):
        raise RuntimeError("AccessDenied")

    fake.copy_object = denied  # type: ignore[method-assign]
    assert copy_objects(a, b, [_sha(data)]).methods == {"stream": 1}
    assert b.get(_sha(data)) == data


def test_streaming_refuses_wrong_bytes_and_leaves_nothing(session):
    fake = FakeS3()
    a = _bucket(fake, "a")
    b = _bucket(fake, "b", session, profile="other")
    data = b"right"
    a.put(data, "d")
    fake.objects[("a", a.key_of(_sha(data)))] = (
        b"wrong",
        fake.objects[("a", a.key_of(_sha(data)))][1],
    )
    with pytest.raises(ValidationError):
        copy_objects(a, b, [_sha(data)])
    assert not any(k[0] == "b" for k in fake.objects)


def test_across_kinds_both_ways(tmp_path, session):
    fake = FakeS3()
    d = _drive(tmp_path / "d", session)
    s = _bucket(fake, "a", session)
    one, two = b"to-bucket", b"to-drive"
    d.put(one, "1")
    s.put(two, "2")
    assert copy_objects(d, s, [_sha(one)]).methods == {"stream": 1}
    assert s.get(_sha(one)) == one
    assert copy_objects(s, d, [_sha(two)]).methods == {"stream": 1}
    assert d.get(_sha(two)) == two
    missing = copy_objects(s, d, [_sha(b"zz")])
    assert missing.absent == [_sha(b"zz")]
