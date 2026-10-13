"""Where a project's files are kept: drives on this machine, or a bucket.

A project keeps its files in one place: the drives of `[store.volumes]` or one
S3 bucket (`[store.s3]`, `S3ObjectStore`). This is the one place that changes
which, for the CLI (`civex store bucket ...`) and the app (`/store/bucket`)
alike. Files are never moved between the two, so a switch is allowed only
while the place being left holds none: otherwise they would be out of reach.
A bucket is tried before it is used (`check`): reached, written, read back and
tidied, and refused if something else already keeps files under its prefix,
since a clean-up here would take another project's files for unused ones.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from civex.config import S3_VOLUME, ConfigStore, S3Config
from civex.domain.dtos import BucketCheck, BucketStatus
from civex.domain.exceptions import ValidationError

# Files and bytes recorded on each volume (`inventory.held`).
Held = Callable[[], dict[str, tuple[int, int]]]
ClientFor = Callable[[S3Config], Any]


def _size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _files(n: int, size: int) -> str:
    return f"{n:,} file{'' if n == 1 else 's'} ({_size(size)})"


def _code(error: Exception) -> str:
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        return str(response.get("Error", {}).get("Code", ""))
    return ""


def _where(settings: S3Config) -> str:
    where = f"'{settings.bucket}'"
    if settings.prefix:
        where += f" under '{settings.prefix}/'"
    return where


def settings_of(
    bucket: str,
    prefix: str = "",
    region: str | None = None,
    endpoint: str | None = None,
    profile: str | None = None,
    direct: bool = True,
) -> S3Config:
    """Bucket settings as a person gave them, tidied as config.toml reads them."""
    bucket = bucket.strip()
    if not bucket:
        raise ValidationError("Name the bucket.")
    return S3Config(
        bucket=bucket,
        prefix=prefix.strip().strip("/"),
        region=(region or "").strip() or None,
        endpoint=(endpoint or "").strip() or None,
        profile=(profile or "").strip() or None,
        direct=direct,
    )


class BucketService:
    def __init__(
        self,
        config_store: ConfigStore,
        held: Held,
        client_for: ClientFor,
    ) -> None:
        """`held` reads the inventory; `client_for` makes an S3 client for
        settings (`s3.store.boto_client`; tests give a fake)."""
        self._config_store = config_store
        self._held = held
        self._client_for = client_for

    # -- what is ------------------------------------------------------------

    def status(self) -> BucketStatus:
        """Where files are kept now and what each place holds. Asks nothing
        of the bucket, so it is cheap and works offline."""
        current = self._config_store.load().store_config.s3
        held = self._held()
        bucket_files, bucket_bytes = held.get(S3_VOLUME, (0, 0))
        drive_files = sum(n for v, (n, _) in held.items() if v != S3_VOLUME)
        drive_bytes = sum(b for v, (_, b) in held.items() if v != S3_VOLUME)
        blocked = self._blocked(current, held)
        base = BucketStatus(
            bucket=None,
            bucket_files=bucket_files,
            bucket_bytes=bucket_bytes,
            drive_files=drive_files,
            drive_bytes=drive_bytes,
            can_switch=blocked is None,
            blocked=blocked,
        )
        if current is None:
            return base
        return replace(
            base,
            bucket=current.bucket,
            prefix=current.prefix,
            region=current.region,
            endpoint=current.endpoint,
            profile=current.profile,
            direct=current.direct,
        )

    def _blocked(
        self, current: S3Config | None, held: dict[str, tuple[int, int]]
    ) -> str | None:
        """Why the place files are kept can't change now, or None. Files are
        never moved between drives and a bucket, so the place being left must
        hold none."""
        if current is None:
            files = sum(n for v, (n, _) in held.items() if v != S3_VOLUME)
            size = sum(b for v, (_, b) in held.items() if v != S3_VOLUME)
            if files:
                return (
                    f"This project keeps {_files(files, size)} on its drives. "
                    "Files aren't moved into a bucket, so they would be out of "
                    "reach. A bucket can be used by a project with no files yet."
                )
            return None
        files, size = held.get(S3_VOLUME, (0, 0))
        if files:
            return (
                f"This project keeps {_files(files, size)} in the bucket "
                f"{_where(current)}. Files aren't moved out of a bucket, so "
                "they would be out of reach."
            )
        return None

    # -- trying a bucket ----------------------------------------------------

    def check(self, settings: S3Config) -> BucketCheck:
        """Whether civex can keep this project's files in the bucket, found by
        trying: list under the prefix, then write, read back and remove a small
        object. Nothing is left behind."""
        current = self._config_store.load().store_config.s3
        same_place = (
            current is not None
            and current.bucket == settings.bucket
            and current.prefix == settings.prefix
        )
        problems: list[str] = []
        warnings: list[str] = []
        try:
            client = self._client_for(settings)
        except Exception as e:
            return BucketCheck([f"civex can't make a connection to the bucket: {e}"])

        prefix = f"{settings.prefix}/" if settings.prefix else ""
        try:
            listed = client.list_objects_v2(
                Bucket=settings.bucket, Prefix=prefix, MaxKeys=1
            )
        except Exception as e:
            code = _code(e)
            if type(e).__name__ in ("NoCredentialsError", "PartialCredentialsError"):
                problems.append(
                    "civex found no credentials for the bucket. Set "
                    "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY where civex "
                    "runs, or name an AWS profile."
                )
            elif code == "NoSuchBucket":
                problems.append(
                    f"There is no bucket '{settings.bucket}'"
                    + (f" at {settings.endpoint}" if settings.endpoint else "")
                    + ". Make it first; civex doesn't make buckets."
                )
            elif code in ("AccessDenied", "403", "InvalidAccessKeyId"):
                problems.append(
                    f"The bucket '{settings.bucket}' refused to list its "
                    f"contents ({code}). Check the credentials and that they "
                    "may list, read, write and delete in it."
                )
            else:
                problems.append(f"The bucket '{settings.bucket}' can't be reached: {e}")
            return BucketCheck(problems)
        if listed.get("Contents") and not same_place:
            problems.append(
                f"The bucket {_where(settings)} already holds files. Another "
                "project may keep its files there, and a clean-up here would "
                "remove them as unused. Choose an empty bucket or another prefix."
            )

        key = f"{prefix}.civex-check-{uuid.uuid4().hex}"
        probe = b"civex checks it can keep files here"
        step = "write to"
        try:
            client.put_object(Bucket=settings.bucket, Key=key, Body=probe)
            step = "read from"
            body = client.get_object(Bucket=settings.bucket, Key=key)["Body"]
            try:
                read = body.read()
            finally:
                body.close()
            if read != probe:
                problems.append(
                    f"What civex wrote to the bucket '{settings.bucket}' read "
                    "back different."
                )
            step = "delete from"
            client.delete_object(Bucket=settings.bucket, Key=key)
        except Exception as e:
            problems.append(f"civex can't {step} the bucket '{settings.bucket}': {e}")

        if settings.endpoint and settings.endpoint.startswith("http://"):
            warnings.append(
                "The endpoint is plain http://: files and credentials cross the "
                "network unencrypted. Fine for a bucket on this machine."
            )
        return BucketCheck(problems, warnings)

    # -- changing it --------------------------------------------------------

    def use(self, settings: S3Config) -> BucketStatus:
        """Keep this project's files in `settings`' bucket from now on, or
        change how it is reached (endpoint, region, profile, direct). Refused
        while that would leave files out of reach, or when the bucket fails
        its check."""
        config = self._config_store.load()
        current = config.store_config.s3
        moves = (
            current is None
            or current.bucket != settings.bucket
            or current.prefix != settings.prefix
        )
        if moves:
            blocked = self._blocked(current, self._held())
            if blocked:
                raise ValidationError(blocked)
        found = self.check(settings)
        if not found.ok:
            raise ValidationError(" ".join(found.problems))
        config.store_config.s3 = settings
        self._config_store.save(config)
        return self.status()

    def stop_using(self) -> BucketStatus:
        """Keep this project's files on drives again. Refused while the bucket
        holds any of them."""
        config = self._config_store.load()
        current = config.store_config.s3
        if current is None:
            return self.status()
        blocked = self._blocked(current, self._held())
        if blocked:
            raise ValidationError(blocked)
        config.store_config.s3 = None
        self._config_store.save(config)
        return self.status()
