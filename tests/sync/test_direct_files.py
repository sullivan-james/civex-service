"""An authority whose files are in a bucket (`direct_files`): a device's files
go straight from it to the bucket and come straight back, with the authority
only saying where and recording what arrived. The real client, the real
server over a socket, and a bucket in memory with an HTTP front standing in
for S3 (`tests/fake_s3.py`)."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from civex.testing.fake_s3 import FakeS3

from civex.config import load_config_at
from civex.context import build_local_context
from civex.domain.sync import DIRECT_FILES
from civex.project import scaffold_project
from civex.repositories.local import inventory
from civex.repositories.s3 import store as s3_module

from civex.testing import build_study, principal, serve


def _authority(tmp_path: Path, fake: FakeS3, direct: bool = True):
    root = tmp_path / "authority"
    scaffold_project(root, db_url=f"sqlite:///{(root / 'civex.db').as_posix()}")
    toml = root / "_civex" / "config.toml"
    toml.write_text(
        toml.read_text()
        + "\n[sync]\nserve = true\n"
        + '\n[store.s3]\nbucket = "lab"\nprefix = "projects/study"\n'
        + ("" if direct else "direct = false\n")
    )
    return root, build_local_context(load_config_at(root))


@pytest.fixture()
def bucket(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeS3]:
    fake = FakeS3(serve=True)
    monkeypatch.setattr(s3_module, "boto_client", lambda cfg: fake)
    yield fake
    fake.close()


@pytest.fixture(params=[True, False], ids=["direct", "streamed"])
def server(request, bucket: FakeS3, tmp_path: Path):
    """The authority over a socket, its files in the bucket: once handing out
    URLs, once (direct = false) taking the bytes itself."""
    root, authority = _authority(tmp_path, bucket, direct=request.param)
    previous = os.getcwd()
    os.chdir(root)
    _, invite = authority.device_keys.invite("laptop")
    _, invite2 = authority.device_keys.invite("phone")
    authority.commit()

    from civex.server.app import create_app

    try:
        with serve(create_app()) as url:
            yield url, (invite, invite2), authority, request.param
    finally:
        authority.close()
        os.chdir(previous)


def _with_file(ctx, record, content: bytes):
    ctx.schema_svc.add_field("encounter", "scan", "file")
    ref = ctx.file_svc.store_bytes(content, "scan.bin")
    ctx.record_svc.update(str(record.id), {"scan": ref.to_dict()})
    ctx.commit()
    return ref


def test_files_go_between_a_device_and_the_bucket(project, server, bucket, monkeypatch):
    url, (invite, invite2), authority, direct = server
    # Small enough for one PUT; the second is sent in parts.
    monkeypatch.setattr(s3_module, "SINGLE_PUT_MAX", 64)
    monkeypatch.setattr(s3_module, "PART_SIZE", 1024)
    laptop = project("laptop")
    record = build_study(laptop)
    small = _with_file(laptop, record, b"a small scan")
    assert laptop.sync_svc.connect(url, invite) == "seeded"
    laptop.commit()
    laptop.sync_svc.sync()
    laptop.sync_svc.send_files()
    laptop.commit()

    key = f"projects/study/{small.sha256[:2]}/{small.sha256[2:]}"
    assert bucket.objects[("lab", key)][0] == b"a small scan"
    assert authority.file_svc.exists(small.sha256)
    if direct:
        # The authority only presigned and recorded: not one byte through it.
        assert "put_object" not in bucket.calls and "upload_file" not in bucket.calls
    else:
        assert "upload_file" in bucket.calls  # streamed to it, then put by it

    big = bytes(range(256)) * 12 + b"!"  # 3073 bytes: four parts of 1024
    laptop.schema_svc.add_field("encounter", "raw", "file")
    ref = laptop.file_svc.store_bytes(big, "raw.bin")
    laptop.record_svc.update(
        str(record.id), {"scan": small.to_dict(), "raw": ref.to_dict()}
    )
    laptop.commit()
    bucket.calls.clear()
    laptop.sync_svc.sync()
    laptop.sync_svc.send_files()
    laptop.commit()
    assert authority.file_svc.retrieve(ref.sha256) == big
    unverified = inventory.unverified(authority._session, "s3", "", 10)
    if direct:
        assert "complete_multipart_upload" in bucket.calls
        # In parts: each checked by storage, the whole by a read-back later.
        assert unverified == [ref.sha256]
        authority.gc_svc.run(dry_run=False, grace_days=0)
        authority.commit()
        assert inventory.unverified(authority._session, "s3", "", 10) == []
    else:
        assert unverified == []  # the authority hashed what it streamed in
    assert laptop.sync_svc.status().files_to_send == 0

    # Another device gets the files back: from the bucket itself when the
    # authority points there (a 307), else streamed by the authority.
    phone = project("phone")
    assert phone.sync_svc.connect(url, invite2) == "joined"
    phone.commit()
    assert phone.sync_svc.fetch_file(ref.sha256) is True
    assert phone.file_svc.retrieve(ref.sha256) == big
    assert phone.sync_svc.fetch_file(small.sha256) is True
    assert phone.file_svc.retrieve(small.sha256) == b"a small scan"
    assert phone.sync_svc.fetch_file(hashlib.sha256(b"never sent").hexdigest()) is False


def test_the_authority_says_whether_it_offers_direct_files(server):
    url, (invite, _), authority, direct = server
    hello = authority.authority_svc.hello(principal(authority, "laptop"), 2)
    assert (DIRECT_FILES in hello.capabilities) is direct
