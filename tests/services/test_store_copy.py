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
    fake_b = FakeS3()
    a = _bucket(fake, "a")
    b = _bucket(fake_b, "b", session, profile="other")
    data = os.urandom(size)
    a.put(data, "d")
    monkeypatch.setattr(s3_module, "MULTIPART_MIN", 1024**2)
    monkeypatch.setattr(s3_module, "PART_SIZE", 1024**2)
    monkeypatch.setattr(
        "tempfile.mkstemp", lambda *a, **k: pytest.fail("a temp file was made")
    )
    res = copy_objects(a, b, [_sha(data)])
    assert res.methods == {"stream": 1}
    assert "copy_object" not in fake.calls + fake_b.calls
    assert ("create_multipart_upload" in fake_b.calls) == (size > 1024**2)
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
    fake_b = FakeS3()
    a = _bucket(fake, "a")
    b = _bucket(fake_b, "b", session, profile="other")
    data = b"right"
    a.put(data, "d")
    fake.objects[("a", a.key_of(_sha(data)))] = (
        b"wrong",
        fake.objects[("a", a.key_of(_sha(data)))][1],
    )
    with pytest.raises(ValidationError):
        copy_objects(a, b, [_sha(data)])
    assert not fake_b.objects


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


def test_a_symlink_source_is_never_followed(tmp_path):
    a, b = _drive(tmp_path / "a"), _drive(tmp_path / "b")
    secret = tmp_path / "secret"
    secret.write_bytes(b"secret")
    sha = _sha(b"secret")
    link = a.path_on(sha, "main")
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(secret)
    res = copy_objects(a, b, [sha])
    assert res.absent == [sha] and not b.exists(sha)


def test_a_source_that_vanishes_is_absent_not_an_error(tmp_path, monkeypatch):
    a, b = _drive(tmp_path / "a"), _drive(tmp_path / "b")
    one, two = b"one", b"two"
    a.put(one, "1")
    a.put(two, "2")
    real = os.link

    def gone(src, dst, *args, **kw):
        if Path(src) == a.object_path(_sha(one)):
            Path(src).unlink()
            raise FileNotFoundError(errno.ENOENT, "gone", str(src))
        return real(src, dst, *args, **kw)

    monkeypatch.setattr(os, "link", gone)
    res = copy_objects(a, b, [_sha(one), _sha(two)])
    assert res.absent == [_sha(one)] and res.copied == 1 and b.exists(_sha(two))


def test_a_cross_device_source_that_vanishes_is_absent(tmp_path, monkeypatch):
    a, b = _drive(tmp_path / "a"), _drive(tmp_path / "b")
    a.put(b"vanish", "v")
    sha = _sha(b"vanish")

    def gone(src, dst, *args, **kw):
        Path(src).unlink()
        raise OSError(errno.EXDEV, "x")

    monkeypatch.setattr(os, "link", gone)
    assert copy_objects(a, b, [sha]).absent == [sha]


def test_wrong_bytes_leave_nothing_cross_kind(tmp_path, session):
    fake = FakeS3()
    d = _drive(tmp_path / "d")
    dest_drive = _drive(tmp_path / "e", session)
    s = _bucket(fake, "a")
    dst_bucket = _bucket(fake, "z", session)
    sha = _sha(b"right")
    # drive -> bucket
    p = d.path_on(sha, "main")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"wrong")
    with pytest.raises(ValidationError):
        copy_objects(d, dst_bucket, [sha])
    assert not any(k[0] == "z" for k in fake.objects)
    # bucket -> drive
    s.put(b"wrong", "w")
    fake.objects[("a", s.key_of(sha))] = fake.objects.pop(
        ("a", s.key_of(_sha(b"wrong")))
    )
    with pytest.raises(ValidationError):
        copy_objects(s, dest_drive, [sha])
    assert not dest_drive.exists(sha) and not _inventory(session)
    objects = tmp_path / "e" / "objects"
    assert not [f for f in objects.rglob("*") if f.is_file()]


def test_a_stale_bucket_inventory_is_not_trusted(session):
    fake = FakeS3()
    a, b = _bucket(fake, "a"), _bucket(fake, "b", session)
    data = b"stale" * 10
    a.put(data, "s")
    b.put(data, "s")
    session.flush()
    fake.objects.pop(("b", b.key_of(_sha(data))))  # lost behind the inventory's back
    res = copy_objects(a, b, [_sha(data)])
    assert res.copied == 1 and res.skipped == 0
    assert ("b", b.key_of(_sha(data))) in fake.objects
    # and when the source has lost it too, it is absent
    fake.objects.pop(("b", b.key_of(_sha(data))))
    fake.objects.pop(("a", a.key_of(_sha(data))))
    res = copy_objects(a, b, [_sha(data)])
    assert res.absent == [_sha(data)]


def test_an_injected_client_is_a_different_account_unless_the_same_object(session):
    fake1, fake2 = FakeS3(), FakeS3()
    a, b = _bucket(fake1, "a"), _bucket(fake2, "b", session)
    data = b"two accounts"
    a.put(data, "d")
    res = copy_objects(a, b, [_sha(data)])
    assert (
        res.methods == {"stream": 1} and "copy_object" not in fake1.calls + fake2.calls
    )


def test_failed_multipart_uploads_are_aborted(monkeypatch, session):
    fake = FakeS3()
    fake_b = FakeS3()
    a = _bucket(fake, "a")
    b = _bucket(fake_b, "b", session, profile="other")
    data = os.urandom(3 * 1024**2)
    a.put(data, "d")
    fake.objects[("a", a.key_of(_sha(data)))] = (
        b"x" * len(data),
        fake.objects[("a", a.key_of(_sha(data)))][1],
    )
    monkeypatch.setattr(s3_module, "MULTIPART_MIN", 1024**2)
    monkeypatch.setattr(s3_module, "PART_SIZE", 1024**2)
    with pytest.raises(ValidationError):
        copy_objects(a, b, [_sha(data)])
    assert "abort_multipart_upload" in fake_b.calls and not fake_b.uploads


def test_commit_runs_per_stored_file_and_progress_counts_distinct_shas(tmp_path):
    a, b = _drive(tmp_path / "a"), _drive(tmp_path / "b")
    items = [b"c1", b"c2", b"c3"]
    for i in items:
        a.put(i, "f")
    b.put(items[2], "f")
    commits: list[int] = []
    seen: list[tuple[int, int]] = []
    shas = [_sha(i) for i in items]
    copy_objects(
        a,
        b,
        shas + shas,
        on_progress=lambda d, t: seen.append((d, t)),
        commit=lambda: commits.append(1),
    )
    assert seen == [(1, 3), (2, 3), (3, 3)]
    assert len(commits) == 3  # one per stored file, one after finding c3


def test_a_symlink_swapped_in_after_the_check_is_refused(tmp_path, monkeypatch):
    a, b = _drive(tmp_path / "a"), _drive(tmp_path / "b")
    data = b"swap me"
    a.put(data, "s")
    sha = _sha(data)
    src = a.object_path(sha)
    secret = tmp_path / "secret"
    secret.write_bytes(b"secret")
    real = os.link

    def swap(s, d, *args, **kw):
        if Path(s) == src:
            src.unlink()
            src.symlink_to(secret)
        return real(s, d, *args, **kw)

    monkeypatch.setattr(os, "link", swap)
    res = copy_objects(a, b, [sha])
    assert res.absent == [sha] and not b.exists(sha)
    assert not [f for f in (tmp_path / "b" / "objects").rglob("*") if f.is_file()]


def test_a_source_removed_after_the_copy_still_counts(tmp_path, monkeypatch):
    a, b = _drive(tmp_path / "a"), _drive(tmp_path / "b")
    data = b"gc'd later" * 10
    a.put(data, "g")
    sha = _sha(data)
    src = a.object_path(sha)
    real = os.link

    def link_then_gc(s, d, *args, **kw):
        real(s, d, *args, **kw)
        Path(s).unlink()

    monkeypatch.setattr(os, "link", link_then_gc)
    commits: list[int] = []
    res = copy_objects(a, b, [sha], commit=lambda: commits.append(1))
    assert (res.copied, res.bytes_copied, res.absent) == (1, len(data), [])
    assert commits == [1] and not src.exists() and b.get(sha) == data


def test_without_an_inventory_each_sha_is_asked_of_the_bucket_once():
    fake = FakeS3()
    a, b = _bucket(fake, "a"), _bucket(fake, "b")
    data = b"head once"
    a.put(data, "h")
    b.put(data, "h")
    fake.calls.clear()
    assert copy_objects(a, b, [_sha(data)]).skipped == 1
    assert fake.calls.count("head_object") == 1
