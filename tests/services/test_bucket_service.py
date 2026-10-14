"""Where a project's files are kept, changed in one place (`BucketService`):
a bucket is tried before it is used, and the place files are kept changes only
while the place being left holds none, since files are never moved between."""

from __future__ import annotations

from pathlib import Path

import pytest

from civex.config import S3_VOLUME, FileConfigStore, load_config_at
from civex.domain.exceptions import ValidationError
from civex.services.bucket_service import BucketService, settings_of
from civex.testing.fake_s3 import ClientError, FakeS3


def _service(
    root: Path, s3: object, held: dict[str, tuple[int, int]] | None = None
) -> BucketService:
    return BucketService(
        FileConfigStore(root), lambda: dict(held or {}), lambda _settings: s3
    )


def test_an_empty_project_on_drives_can_keep_its_files_in_a_bucket(project_dir: Path):
    s3 = FakeS3()
    svc = _service(project_dir, s3)
    assert svc.status().bucket is None

    status = svc.use(settings_of("lab", prefix="/humpbacks/", endpoint="http://m:9000"))

    assert status.bucket == "lab" and status.prefix == "humpbacks"
    saved = load_config_at(project_dir).store_config.s3
    assert saved is not None and saved.endpoint == "http://m:9000"
    assert s3.objects == {}  # the check tidied up after itself
    assert {"put_object", "get_object", "delete_object"} <= set(s3.calls)


def test_a_project_with_files_on_drives_is_refused_and_told_why(project_dir: Path):
    svc = _service(project_dir, FakeS3(), {"default": (3, 2048)})
    status = svc.status()
    assert not status.can_switch and "3 files (2.0 KB)" in (status.blocked or "")

    with pytest.raises(ValidationError, match="on its drives"):
        svc.use(settings_of("lab"))
    assert load_config_at(project_dir).store_config.s3 is None


def test_a_bucket_holding_files_cant_be_left_or_swapped(project_dir: Path):
    s3 = FakeS3()
    _service(project_dir, s3).use(settings_of("lab", prefix="p"))
    svc = _service(project_dir, s3, {S3_VOLUME: (2, 10)})

    with pytest.raises(ValidationError, match="in the bucket 'lab' under 'p/'"):
        svc.stop_using()
    with pytest.raises(ValidationError, match="out of reach"):
        svc.use(settings_of("other"))
    # How it is reached may change: the files stay where they are.
    status = svc.use(settings_of("lab", prefix="p", endpoint="http://new:9000"))
    assert status.endpoint == "http://new:9000"
    assert status.bucket_files == 2


def test_an_empty_bucket_can_be_left(project_dir: Path):
    s3 = FakeS3()
    svc = _service(project_dir, s3)
    svc.use(settings_of("lab"))
    assert svc.stop_using().bucket is None
    assert load_config_at(project_dir).store_config.s3 is None


def test_files_left_on_drives_while_a_bucket_is_used_are_counted(project_dir: Path):
    s3 = FakeS3()
    _service(project_dir, s3).use(settings_of("lab"))
    status = _service(project_dir, s3, {"default": (4, 40)}).status()
    assert status.left_on_drives == 4


def test_a_prefix_already_holding_files_is_refused(project_dir: Path):
    s3 = FakeS3()
    s3.put_object(Bucket="lab", Key="theirs/aa/bb", Body=b"x")
    svc = _service(project_dir, s3)

    found = svc.check(settings_of("lab", prefix="theirs"))
    assert not found.ok and "already holds files" in found.problems[0]
    # Another prefix in the same bucket is fine.
    assert svc.check(settings_of("lab", prefix="ours")).ok


class _Refusing(FakeS3):
    def __init__(self, code: str) -> None:
        super().__init__()
        self.code = code

    def list_objects_v2(self, **_kw: object) -> dict:
        raise ClientError(self.code)


@pytest.mark.parametrize(
    ("code", "said"),
    [("NoSuchBucket", "There is no bucket 'lab'"), ("AccessDenied", "credentials")],
)
def test_a_bucket_that_cant_be_used_says_why(project_dir: Path, code: str, said: str):
    found = _service(project_dir, _Refusing(code)).check(settings_of("lab"))
    assert not found.ok and said in found.problems[0]
    with pytest.raises(ValidationError, match=said):
        _service(project_dir, _Refusing(code)).use(settings_of("lab"))


def test_a_bucket_that_cant_be_written_says_so(project_dir: Path):
    class ReadOnly(FakeS3):
        def put_object(self, **_kw: object) -> dict:
            raise ClientError("AccessDenied")

    found = _service(project_dir, ReadOnly()).check(settings_of("lab"))
    assert found.problems == ["civex can't write to the bucket 'lab': AccessDenied"]


def test_plain_http_is_a_warning_not_a_problem(project_dir: Path):
    found = _service(project_dir, FakeS3()).check(
        settings_of("lab", endpoint="http://127.0.0.1:9000")
    )
    assert found.ok and "unencrypted" in found.warnings[0]


def test_a_bucket_must_be_named():
    with pytest.raises(ValidationError):
        settings_of("  ")
