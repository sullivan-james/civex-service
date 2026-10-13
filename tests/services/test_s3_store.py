"""Files in a bucket (`[store.s3]`): the same project, records and history,
with its bytes in S3 instead of on drives. One logical volume that is always
online, the same inventory, no drive management, and files that go straight
between the browser or a device and the bucket when the store hands out URLs."""

from __future__ import annotations

import hashlib
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
from civex.testing.fake_s3 import FakeS3
from fastapi.testclient import TestClient

from civex.config import (
    S3_VOLUME,
    Config,
    DBConfig,
    S3Config,
    StoreConfig,
    load_config_at,
    parse_config,
    render_config,
)
from civex.context import build_local_context, make_store
from civex.domain import features
from civex.domain.exceptions import FeatureUnavailableError
from civex.project import local_features, scaffold_project
from civex.repositories.local.file_store import VolumeAwareFileObjectStore
from civex.repositories.protocols import ObjectStore, VolumeStore
from civex.repositories.s3 import store as s3_module
from civex.repositories.s3.store import S3ObjectStore
from civex.server.app import create_app

CFG = S3Config(bucket="b", prefix="projects/p1")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture()
def fake() -> FakeS3:
    s3 = FakeS3(serve=True)
    yield s3
    s3.close()


@pytest.fixture()
def s3_project(tmp_path: Path, fake: FakeS3, monkeypatch: pytest.MonkeyPatch):
    """A project in a folder whose files are in a (fake) bucket."""
    root = tmp_path / "bucketed"
    scaffold_project(root)
    toml = root / "_civex" / "config.toml"
    toml.write_text(
        toml.read_text() + '\n[store.s3]\nbucket = "b"\nprefix = "projects/p1"\n'
    )
    monkeypatch.setattr(s3_module, "boto_client", lambda cfg: fake)
    monkeypatch.chdir(root)
    return root


# -- the settings --------------------------------------------------------------


def test_the_s3_settings_round_trip(tmp_path: Path):
    config = Config(
        project_root=tmp_path,
        db=DBConfig(url="sqlite:///x.db"),
        store=StoreConfig(
            volumes={},
            volume_queue=[],
            s3=S3Config(
                bucket="b",
                prefix="p",
                region="eu-west-2",
                endpoint="http://127.0.0.1:9000",
                profile="lab",
                direct=False,
            ),
        ),
    )
    text = render_config(config)
    again = parse_config(tomllib.loads(text), tmp_path)
    assert again.store_config.s3 == config.store_config.s3
    # The volumes a bucketed project doesn't use are the usual default.
    assert list(again.store_config.volumes) == ["default"]


def test_a_bucketed_project_has_no_drives_and_offers_direct_files(s3_project):
    config = load_config_at(s3_project)
    offered = local_features(config)
    assert features.VOLUMES not in offered
    assert features.DIRECT_FILES in offered
    assert features.LOCAL_WORKFLOWS in offered
    config.store_config.s3.direct = False
    assert features.DIRECT_FILES not in local_features(config)
    assert local_features(Config(tmp := s3_project, DBConfig("sqlite:///x"))) == (
        features.LOCAL_FEATURES
    )
    assert tmp == s3_project


def test_the_store_follows_the_settings(s3_project, tmp_path: Path):
    assert isinstance(make_store(load_config_at(s3_project)), S3ObjectStore)
    plain = tmp_path / "plain"
    scaffold_project(plain)
    assert isinstance(make_store(load_config_at(plain)), VolumeAwareFileObjectStore)
    # Both are object stores; only drives are a volume store.
    assert isinstance(make_store(load_config_at(plain)), VolumeStore)
    assert not isinstance(make_store(load_config_at(s3_project)), VolumeStore)


# -- the store on its own ------------------------------------------------------


def test_bytes_are_kept_once_under_their_hash(fake: FakeS3):
    store = S3ObjectStore(CFG, client=fake)
    ref = store.put(b"hello", "greeting.txt")
    again = store.put(b"hello", "other.txt")
    assert ref.sha256 == again.sha256 == _sha(b"hello")
    assert ref.volume == S3_VOLUME
    assert list(fake.objects) == [
        ("b", f"projects/p1/{ref.sha256[:2]}/{ref.sha256[2:]}")
    ]
    assert store.get(ref.sha256) == b"hello"
    assert store.exists(ref.sha256) and not store.exists("0" * 64)
    assert store.size_of(ref.sha256) == 5 and store.size_of("0" * 64) is None
    with pytest.raises(FileNotFoundError):
        store.get("0" * 64)
    with store.open(ref.sha256) as f:
        assert f.read(2) == b"he"
        f.seek(0)
        assert f.read() == b"hello"
    assert store.delete(ref.sha256) is True
    assert store.delete(ref.sha256) is False
    assert not store.exists(ref.sha256)


def test_a_stream_and_a_path_are_hashed_on_the_way_in(fake: FakeS3, tmp_path: Path):
    import asyncio

    store = S3ObjectStore(CFG, client=fake)

    async def chunks():
        yield b"abc"
        yield b""
        yield b"def"

    ref = asyncio.run(store.put_stream(chunks(), "s.bin"))
    assert (ref.sha256, ref.size) == (_sha(b"abcdef"), 6)
    assert store.get(ref.sha256) == b"abcdef"
    path = tmp_path / "f.bin"
    path.write_bytes(b"from disk")
    ref2 = store.put_path(path)
    assert ref2.filename == "f.bin" and store.get(ref2.sha256) == b"from disk"
    ref3 = store.put_chunks(iter([b"ch", b"unks"]), "c.bin")
    assert store.get(ref3.sha256) == b"chunks"
    assert not list(Path(__import__("tempfile").gettempdir()).glob("civex-s3-*"))


def test_it_is_one_volume_that_is_always_online(fake: FakeS3):
    store = S3ObjectStore(CFG, client=fake)
    ref = store.put(b"x", "x")
    assert store.volume_names() == [S3_VOLUME]
    assert store.volume_status(S3_VOLUME).writable
    assert not store.volume_status("archive").reachable
    assert store.homes() == {}
    assert store.readable_first(["s3", "s3"]) == ["s3"]
    assert store.locate_volumes([ref.sha256, "0" * 64]) == {
        ref.sha256: S3_VOLUME,
        "0" * 64: None,
    }
    assert store.offline_location(ref.sha256) is None
    [copy] = store.copies_of(ref.sha256)
    assert copy.volume == S3_VOLUME and copy.present and copy.network
    assert copy.path.startswith("s3://b/projects/p1/")
    assert store.copies_of("0" * 64) == []


def test_a_clean_up_lists_the_bucket_and_frees_abandoned_uploads(fake: FakeS3):
    store = S3ObjectStore(CFG, client=fake)
    refs = [store.put(bytes([n]) * 3, f"{n}") for n in range(5)]
    fake.objects[("b", "projects/p1/not-an-object")] = (
        b"?",
        fake.objects[next(iter(fake.objects))][1],
    )
    listed = sorted(o.sha256 for o in store.iter_objects())
    assert listed == sorted(r.sha256 for r in refs)  # paged, foreign keys skipped
    fake.create_multipart_upload("b", "projects/p1/aa/" + "b" * 62)
    assert store.sweep_stale_scratch(3600, dry_run=True) == 0
    fake.age_uploads(7200)
    assert store.sweep_stale_scratch(3600, dry_run=True) == 1
    assert store.sweep_stale_scratch(3600) == 1 and fake.uploads == {}
    with store.gc_lock():
        with pytest.raises(Exception, match="already running"):
            with store.gc_lock():
                pass


def test_the_bucket_being_unreachable_is_said_in_civex_terms(fake: FakeS3):
    from civex.domain.exceptions import VolumeUnavailableError

    def down(*a, **k):
        raise ConnectionError("no route to host")

    fake.put_object = down  # type: ignore[method-assign]
    store = S3ObjectStore(CFG, client=fake)
    with pytest.raises(VolumeUnavailableError, match="can't be reached"):
        store.put(b"x", "x")


# -- with the inventory ---------------------------------------------------------


def test_the_inventory_answers_where_without_asking_the_bucket(s3_project):
    ctx = build_local_context(load_config_at(s3_project))
    try:
        fake = ctx.file_svc._store.client  # type: ignore[attr-defined]
        ref = ctx.file_svc.store_bytes(b"inventoried", "i.bin")
        ctx.commit()
        fake.calls.clear()
        assert ctx.file_svc.exists(ref.sha256)
        assert ctx.file_svc.size_of(ref.sha256) == len(b"inventoried")
        assert ctx.file_svc._store.copies([ref.sha256]) == {ref.sha256: [("s3", 11)]}
        assert fake.calls == []  # not one head or get
        # A record's file is stamped with the one volume, online.
        ctx.schema_svc.create("doc")
        ctx.schema_svc.add_field("doc", "scan", "file")
        ctx.dataset_svc.create("study")
        ctx.dataset_svc.update("study", schemas=["doc"])
        record = ctx.record_svc.add("study", "doc", {"scan": ref.to_dict()})
        ctx.commit()
        shown = ctx.record_svc.get(str(record.id))
        location = shown.data["scan"]["location"]
        assert (location["volume"], location["state"], location["available"]) == (
            "s3",
            "online",
            True,
        )
    finally:
        ctx.close()


def test_reconcile_and_verify_check_what_is_in_the_bucket(s3_project):
    ctx = build_local_context(load_config_at(s3_project))
    try:
        store = ctx.file_svc._store
        fake = store.client
        good = ctx.file_svc.store_bytes(b"good", "g")
        ctx.commit()
        # Two objects nothing here wrote: one whose bytes match its key, one
        # whose don't (a buggy uploader), and one gone from the bucket.
        honest = _sha(b"honest")
        fake.objects[("b", store.key_of(honest))] = (
            b"honest",
            fake.objects[("b", store.key_of(good.sha256))][1],
        )
        liar = _sha(b"what it claims")
        fake.objects[("b", store.key_of(liar))] = (
            b"something else",
            fake.objects[("b", store.key_of(good.sha256))][1],
        )
        vanished = ctx.file_svc.store_bytes(b"vanished", "v")
        ctx.commit()
        fake.objects.pop(("b", store.key_of(vanished.sha256)))

        assert store.reconcile_inventory() == {"added_or_updated": 3, "removed": 1}
        assert not store.exists(vanished.sha256)
        assert store.exists(honest) and store.exists(liar)

        assert store.verify() == [liar]
        assert not store.exists(liar) and ("b", store.key_of(liar)) not in fake.objects
        assert store.exists(honest) and store.verify() == []  # now verified, once
        # GC runs the same, through the one clean-up service.
        report = ctx.gc_svc.run(dry_run=False, grace_days=0)
        assert report.errors == []
    finally:
        ctx.close()


# -- straight to and from the bucket -----------------------------------------


def test_a_small_file_goes_in_with_one_put_checked_by_the_bucket(fake: FakeS3):
    store = S3ObjectStore(CFG, client=fake)
    data = b"straight in"
    sha = _sha(data)
    target = store.upload_target(sha, len(data))
    assert target is not None and not target.multipart
    assert set(target.headers) == {"x-amz-checksum-sha256"}
    request = urllib.request.Request(target.url, data=data, method="PUT")
    for name, value in target.headers.items():
        request.add_header(name, value)
    urllib.request.urlopen(request).close()
    # Wrong bytes under that URL are refused by storage itself.
    bad = urllib.request.Request(target.url, data=b"wrong", method="PUT")
    for name, value in target.headers.items():
        bad.add_header(name, value)
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(bad)
    assert refused.value.code == 400

    ref = store.complete_upload(sha, len(data), "s.bin")
    assert ref.sha256 == sha and store.get(sha) == data
    # Direct is a setting: off, nothing is handed out and files are streamed.
    quiet = S3ObjectStore(S3Config(bucket="b", direct=False), client=fake)
    assert quiet.upload_target(sha, 1) is None and quiet.download_url(sha) is None


def test_a_big_file_goes_in_by_parts_and_is_verified_later(
    fake: FakeS3, monkeypatch: pytest.MonkeyPatch, s3_project
):
    monkeypatch.setattr(s3_module, "SINGLE_PUT_MAX", 10)
    monkeypatch.setattr(s3_module, "PART_SIZE", 1024**2)
    ctx = build_local_context(load_config_at(s3_project))
    try:
        store = ctx.file_svc._store
        data = bytes(range(256)) * 8192 + b"tail"  # 2 MiB and a bit: three parts
        sha = _sha(data)
        target = store.upload_target(sha, len(data))
        assert target.multipart and target.part_size == 1024**2
        assert [p.number for p in target.parts] == [1, 2, 3]
        from civex.domain.dtos import UploadedPart

        parts = []
        for part in target.parts:
            piece = data[
                (part.number - 1) * target.part_size : part.number * target.part_size
            ]
            request = urllib.request.Request(part.url, data=piece, method="PUT")
            with urllib.request.urlopen(request) as answer:
                parts.append(UploadedPart(part.number, answer.headers["ETag"]))
        ref = store.complete_upload(sha, len(data), "big.bin", target.upload_id, parts)
        ctx.commit()
        assert ref.size == len(data) and store.get(sha) == data
        # Recorded, but not yet checked as a whole; the read-back does that.
        from civex.repositories.local import inventory

        assert inventory.unverified(ctx._session, "s3", "", 10) == [sha]
        assert store.verify() == []
        assert inventory.unverified(ctx._session, "s3", "", 10) == []
        # A size that doesn't match what was announced is refused and removed.
        other = _sha(b"short")
        t = store.upload_target(other, 5)
        urllib.request.urlopen(_signed(t.url, t.headers, b"short")).close()
        with pytest.raises(Exception, match="not the 99 announced"):
            store.complete_upload(other, 99, "x")
        assert ("b", store.key_of(other)) not in fake.objects
    finally:
        ctx.close()


def _signed(url: str, headers: dict[str, str], data: bytes):
    request = urllib.request.Request(url, data=data, method="PUT")
    for name, value in headers.items():
        request.add_header(name, value)
    return request


def test_a_download_url_names_the_file(fake: FakeS3):
    store = S3ObjectStore(CFG, client=fake)
    ref = store.put(b"named", "n")
    url = store.download_url(ref.sha256, "Scan 1.png")
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    assert query["response-content-disposition"].startswith(
        'attachment; filename="Scan 1.png"'
    )
    with urllib.request.urlopen(url) as answer:
        assert answer.read() == b"named"
        assert "Scan 1.png" in answer.headers["Content-Disposition"]


def test_what_a_real_presigned_put_signs_is_what_the_target_carries():
    """boto3 signs exactly the headers the uploader must send: the target's
    `headers` are those (bar `host`), or S3 would refuse the PUT."""
    import boto3
    from botocore.config import Config as BotoConfig

    client = boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        config=BotoConfig(signature_version="s3v4"),
    )
    store = S3ObjectStore(S3Config(bucket="b", prefix="p"), client=client)
    sha = _sha(b"abc")
    target = store.upload_target(sha, 3)
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(target.url).query))
    signed = set(query["X-Amz-SignedHeaders"].split(";"))
    assert signed == {"host", *target.headers}
    assert urllib.parse.urlsplit(target.url).path.endswith(f"/p/{sha[:2]}/{sha[2:]}")


# -- the project as a whole -------------------------------------------------------


def test_a_bucketed_project_offers_no_drive_management(s3_project):
    ctx = build_local_context(load_config_at(s3_project))
    try:
        with pytest.raises(FeatureUnavailableError):
            ctx.store_svc
        with pytest.raises(FeatureUnavailableError):
            ctx.transfer_svc
        assert ctx.file_svc.local_path("0" * 64) is None
        assert ctx.file_access_svc.list_exports() == []
        from civex.domain.file_access import FileSelection

        with pytest.raises(FeatureUnavailableError):
            ctx.file_access_svc.export_managed(FileSelection(), "x", mode="copy")
    finally:
        ctx.close()


def test_the_api_redirects_downloads_to_the_bucket_and_hides_drives(s3_project):
    client = TestClient(create_app(), raise_server_exceptions=False)
    ctx = build_local_context(load_config_at(s3_project))
    try:
        ref = ctx.file_svc.store_bytes(b"served", "s.txt")
        ctx.commit()
    finally:
        ctx.close()
    offered = client.get("/api/status/features").json()["features"]
    assert "direct_files" in offered and "volumes" not in offered
    # `civex serve` includes every router; a project with no drives answers
    # that it doesn't do that, in plain words, and the app hides the pages.
    answer = client.get("/api/store/volumes")
    assert answer.status_code == 501
    assert answer.json()["detail"] == features.unavailable_message(features.VOLUMES)

    answer = client.get(
        f"/api/files/{ref.sha256}?filename=s.txt", follow_redirects=False
    )
    assert answer.status_code == 307
    where = answer.headers["location"]
    assert "response-content-disposition" in where
    with urllib.request.urlopen(where) as storage:
        assert storage.read() == b"served"
    # The app's check before a download is a HEAD, answered here, not by storage.
    assert client.head(f"/api/files/{ref.sha256}").status_code == 200
    assert client.head(f"/api/files/{'0' * 64}").status_code == 404
    # A file the bucket hasn't got is a 404 here, not a redirect to one there.
    assert (
        client.get(f"/api/files/{'0' * 64}", follow_redirects=False).status_code == 404
    )
    # Uploads through the API still work (hashed here, then put in the bucket).
    up = client.put("/api/files/stream?filename=u.bin", content=b"uploaded")
    assert up.status_code == 201 and up.json()["volume"] == "s3"
    # A zip is made by streaming from the bucket.
    plan = client.post(
        "/api/file-access/zip",
        json={"selection": {"record_ids": []}, "allow_partial": True},
    )
    assert plan.status_code in (200, 409, 422)  # the shape is checked elsewhere


def test_without_direct_the_api_streams_the_bytes(s3_project, fake: FakeS3):
    toml = s3_project / "_civex" / "config.toml"
    toml.write_text(toml.read_text() + "direct = false\n")
    client = TestClient(create_app(), raise_server_exceptions=False)
    up = client.put("/api/files/stream?filename=u.bin", content=b"streamed back")
    sha = up.json()["sha256"]
    assert "direct_files" not in client.get("/api/status/features").json()["features"]
    answer = client.get(f"/api/files/{sha}?filename=u.bin", follow_redirects=False)
    assert answer.status_code == 200 and answer.content == b"streamed back"
    assert answer.headers["content-disposition"].startswith(
        'attachment; filename="u.bin"'
    )


def test_the_object_store_protocol_is_what_the_services_see():
    """Every service but the drive ones types against `ObjectStore`, so a
    store that isn't drives (the bucket) satisfies them; the bucket store
    has every method of the protocol."""
    missing = [
        name
        for name in dir(ObjectStore)
        if not name.startswith("_") and not hasattr(S3ObjectStore, name)
    ]
    assert missing == []
