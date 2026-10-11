"""An object store in an S3 bucket (or anything speaking its API: MinIO, R2).

One logical volume, `S3_VOLUME`, always online. Objects are keyed
`<prefix>/<sha[:2]>/<sha[2:]>`, the layout a drive uses, and the inventory is
the same `stored_objects` table (`repositories.local.inventory`), so where a
file is, how big it is and what a clean-up may remove are answered from the
database and never by listing the bucket, except in a reconcile.

Bytes needn't pass through civex: `upload_target` presigns a PUT (one, with the
sha256 checked by S3 itself, or a part each for a big file) and `download_url`
a GET; `complete_upload` records what went in. A file that went in by parts is
recorded unverified until `verify` reads it back, since S3 checks each part but
not the whole. What civex writes itself (`put*`) it hashed, so it is verified.

`boto3` is imported only when a client is needed, and a client can be given
(tests give a fake), so the module imports without the extra installed.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import logging
import math
import os
import re
import tempfile
import threading
import time
import uuid
from collections.abc import AsyncIterable, Iterable, Iterator
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, BinaryIO, cast

from civex.config import S3_VOLUME, S3Config
from civex.domain.dtos import (
    VOLUME_OFFLINE,
    VOLUME_ONLINE,
    DirectPart,
    DirectUpload,
    FileCopy,
    FileRef,
    StoredObjectInfo,
    UploadedPart,
    VolumeStatus,
)
from civex.domain.exceptions import (
    ConfigError,
    GCAlreadyRunningError,
    ValidationError,
    VolumeUnavailableError,
)
from civex.repositories.local import inventory
from civex.server.files import attachment

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# A presigned PUT for a whole file up to this size (S3's limit for one PUT);
# bigger files go in parts.
SINGLE_PUT_MAX = 5 * 1024**3
PART_SIZE = 64 * 1024**2
MAX_PARTS = 10_000  # S3's limit on a multipart upload
# How long a presigned URL works. Uploads get longer: a big file over a slow
# link takes a while, and an expired part means asking for a fresh target.
UPLOAD_SECONDS = 6 * 3600
DOWNLOAD_SECONDS = 3600
# How many bytes are read at once from the bucket.
_CHUNK = 1024 * 1024
_RECONCILE_BATCH = 500
# Files the inventory doesn't know are looked for in the bucket, a bounded
# number per request, like a drive's `_LOCATE_DISK_FALLBACK`.
_LOCATE_FALLBACK = 20
_KEY_RE = re.compile(r"^([0-9a-f]{2})/([0-9a-f]{62})$")


def _is_missing(error: Exception) -> bool:
    """A client error that means the object isn't there (botocore's
    ClientError carries the code in `response`)."""
    response = getattr(error, "response", None)
    code = ""
    if isinstance(response, dict):
        code = str(response.get("Error", {}).get("Code", ""))
    return code in ("404", "NoSuchKey", "NotFound")


def _b64(sha256_hex: str) -> str:
    return base64.b64encode(bytes.fromhex(sha256_hex)).decode("ascii")


def boto_client(config: S3Config) -> Any:
    """A boto3 S3 client for `config`: credentials from the environment, the
    named profile or the machine's role, never from config.toml."""
    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except ImportError as e:  # pragma: no cover - depends on the install
        raise ConfigError(
            "Files in an S3 bucket need the s3 extra: pip install 'civex[s3]'"
        ) from e
    session = boto3.session.Session(
        profile_name=config.profile, region_name=config.region
    )
    options: dict[str, Any] = {"signature_version": "s3v4"}
    if config.endpoint:
        # MinIO and friends serve one host: the bucket is in the path.
        options["s3"] = {"addressing_style": "path"}
    return session.client(
        "s3", endpoint_url=config.endpoint, config=BotoConfig(**options)
    )


class _Reader:
    """An object's bytes read from the bucket as they are needed, and again
    from any point (`seek` reopens with a Range), so an upload that has to
    be repeated can start over without holding the file in memory."""

    def __init__(self, client: Any, bucket: str, key: str, size: int) -> None:
        self._client = client
        self._bucket = bucket
        self._key = key
        self._size = size
        self._pos = 0
        self._body: Any = None

    def _open(self) -> Any:
        if self._body is None:
            if self._pos >= self._size:
                return None
            answer = self._client.get_object(
                Bucket=self._bucket, Key=self._key, Range=f"bytes={self._pos}-"
            )
            self._body = answer["Body"]
        return self._body

    def read(self, size: int = -1, /) -> bytes:
        body = self._open()
        if body is None:
            return b""
        data = body.read() if size is None or size < 0 else body.read(size)
        self._pos += len(data)
        return data

    def seek(self, offset: int, whence: int = 0, /) -> int:
        base = {0: 0, 1: self._pos, 2: self._size}[whence]
        target = max(0, base + offset)
        if target != self._pos:
            self.close()
            self._pos = target
        return self._pos

    def tell(self) -> int:
        return self._pos

    def close(self) -> None:
        if self._body is not None:
            with contextlib.suppress(Exception):
                self._body.close()
            self._body = None

    def __enter__(self) -> _Reader:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def writable(self) -> bool:
        return False


class S3ObjectStore:
    def __init__(
        self,
        config: S3Config,
        session: Session | None = None,
        client: Any = None,
    ) -> None:
        """With a `session`, copies are recorded in `stored_objects` and asked
        of it; without one every question goes to the bucket (standalone use).
        `client` is a boto3 S3 client, or something shaped like one (a fake
        in tests); None makes one from `config` when first needed."""
        self._cfg = config
        self._session = session
        self._client = client
        self.name = S3_VOLUME
        self._gc = threading.Lock()

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = boto_client(self._cfg)
        return self._client

    # -- keys ---------------------------------------------------------------

    def key_of(self, sha256: str) -> str:
        shard = f"{sha256[:2]}/{sha256[2:]}"
        return f"{self._cfg.prefix}/{shard}" if self._cfg.prefix else shard

    def _sha_of(self, key: str) -> str | None:
        prefix = f"{self._cfg.prefix}/" if self._cfg.prefix else ""
        if not key.startswith(prefix):
            return None
        m = _KEY_RE.match(key[len(prefix) :])
        return m.group(1) + m.group(2) if m else None

    # -- storing ------------------------------------------------------------

    def put(
        self, data: bytes, original_filename: str, collection_id: str | None = None
    ) -> FileRef:
        sha256 = hashlib.sha256(data).hexdigest()
        if not self.exists(sha256):
            self._call(
                self.client.put_object,
                Bucket=self._cfg.bucket,
                Key=self.key_of(sha256),
                Body=data,
                ChecksumSHA256=_b64(sha256),
            )
            self._register(sha256, len(data), verified=True)
        return self._ref(sha256, original_filename, len(data))

    async def put_stream(
        self,
        chunks: AsyncIterable[bytes],
        original_filename: str,
        size_hint: int | None = None,
        collection_id: str | None = None,
    ) -> FileRef:
        """Hashed as it arrives into a scratch file (the key is the hash, so it
        can't be known before the end), then sent to the bucket."""
        hasher = hashlib.sha256()
        size = 0
        with self._scratch() as (path, f):
            async for chunk in chunks:
                if chunk:
                    hasher.update(chunk)
                    f.write(chunk)
                    size += len(chunk)
            f.close()
            return self._upload(path, hasher.hexdigest(), size, original_filename)

    def put_chunks(
        self,
        chunks: Iterable[bytes],
        original_filename: str,
        size_hint: int | None = None,
        collection_id: str | None = None,
        volume: str | None = None,
    ) -> FileRef:
        hasher = hashlib.sha256()
        size = 0
        with self._scratch() as (path, f):
            for chunk in chunks:
                if chunk:
                    hasher.update(chunk)
                    f.write(chunk)
                    size += len(chunk)
            f.close()
            return self._upload(path, hasher.hexdigest(), size, original_filename)

    def put_path(
        self,
        path: Path,
        original_filename: str | None = None,
        collection_id: str | None = None,
        volume: str | None = None,
    ) -> FileRef:
        hasher = hashlib.sha256()
        with path.open("rb") as f:
            while chunk := f.read(_CHUNK):
                hasher.update(chunk)
        return self._upload(
            path,
            hasher.hexdigest(),
            path.stat().st_size,
            original_filename or path.name,
        )

    @contextlib.contextmanager
    def _scratch(self) -> Iterator[tuple[Path, IO[bytes]]]:
        fd, name = tempfile.mkstemp(prefix="civex-s3-", suffix=".part")
        path = Path(name)
        f = os.fdopen(fd, "wb")
        try:
            yield path, f
        finally:
            if not f.closed:
                f.close()
            path.unlink(missing_ok=True)

    def _upload(self, path: Path, sha256: str, size: int, filename: str) -> FileRef:
        """Send a file civex has hashed itself to its key, unless the bucket
        holds it already. boto3 sends a big file in parts and retries them."""
        if not self.exists(sha256):
            self._call(
                self.client.upload_file,
                str(path),
                self._cfg.bucket,
                self.key_of(sha256),
            )
            self._register(sha256, size, verified=True)
        return self._ref(sha256, filename, size)

    def _ref(self, sha256: str, filename: str, size: int) -> FileRef:
        return FileRef(sha256=sha256, filename=filename, size=size, volume=self.name)

    def _call(self, method: Any, *args: Any, **kwargs: Any) -> Any:
        """One call to the bucket, with a failure to reach it said in civex's
        terms (the volume isn't available; trying again may work)."""
        try:
            return method(*args, **kwargs)
        except Exception as e:
            if _is_missing(e):
                raise
            raise VolumeUnavailableError(
                f"The bucket '{self._cfg.bucket}' can't be reached: {e}"
            ) from e

    # -- reading ------------------------------------------------------------

    def get(self, sha256: str) -> bytes:
        try:
            answer = self._call(
                self.client.get_object, Bucket=self._cfg.bucket, Key=self.key_of(sha256)
            )
        except Exception as e:
            if _is_missing(e):
                raise FileNotFoundError(f"Object {sha256} is not in the bucket") from e
            raise
        with answer["Body"] as body:
            return body.read()

    def open(self, sha256: str) -> BinaryIO:
        size = self.size_of(sha256)
        if size is None:
            raise FileNotFoundError(f"Object {sha256} is not in the bucket")
        reader = _Reader(self.client, self._cfg.bucket, self.key_of(sha256), size)
        return cast(BinaryIO, reader)

    def exists(self, sha256: str) -> bool:
        """From the inventory when there is one (a row is written only once
        the bucket confirmed the object), else asked of the bucket."""
        if self._session is not None:
            return sha256 in self.copies([sha256])
        return self._head(sha256) is not None

    def size_of(self, sha256: str) -> int | None:
        rows = self.copies([sha256]).get(sha256)
        if rows:
            return rows[0][1]
        return self._head(sha256)

    def _head(self, sha256: str) -> int | None:
        """The object's size, or None when the bucket hasn't got it."""
        try:
            answer = self._call(
                self.client.head_object,
                Bucket=self._cfg.bucket,
                Key=self.key_of(sha256),
            )
        except Exception as e:
            if _is_missing(e):
                return None
            raise
        return int(answer["ContentLength"])

    def delete(self, sha256: str, volume: str | None = None) -> bool:
        if volume not in (None, self.name):
            return False
        had = self.exists(sha256)
        self._call(
            self.client.delete_object, Bucket=self._cfg.bucket, Key=self.key_of(sha256)
        )
        self._unregister(sha256)
        return had

    # -- where is it? One volume, always there. -----------------------------

    def copies(self, shas: Iterable[str]) -> dict[str, list[tuple[str, int]]]:
        if self._session is None:
            out: dict[str, list[tuple[str, int]]] = {}
            for sha in dict.fromkeys(shas):
                size = self._head(sha)
                if size is not None:
                    out[sha] = [(self.name, size)]
            return out
        return inventory.copies(self._session, shas, [self.name])

    def copies_of(self, sha256: str) -> list[FileCopy]:
        size = self._head(sha256)
        if size is None and sha256 not in self.copies([sha256]):
            return []
        return [
            FileCopy(
                self.name,
                f"s3://{self._cfg.bucket}/{self.key_of(sha256)}",
                size is not None,
                VOLUME_ONLINE,
                network=True,
            )
        ]

    def copies_used(
        self, record_ids: Iterable[uuid.UUID]
    ) -> dict[tuple[uuid.UUID, str], str]:
        if self._session is None:
            return {}
        return inventory.copies_used(self._session, record_ids, [self.name])

    def locate_volumes(self, shas: Iterable[str]) -> dict[str, str | None]:
        """From the inventory; a bounded number of files it doesn't know are
        asked of the bucket and recorded when found (unverified: nothing here
        hashed them)."""
        wanted = list(dict.fromkeys(shas))
        found = {sha: self.name for sha in self.copies(wanted)}
        unknown = [s for s in wanted if s not in found]
        if self._session is not None:
            unknown = unknown[:_LOCATE_FALLBACK]
        for sha in unknown:
            size = self._head(sha)
            if size is not None:
                found[sha] = self.name
                self._register(sha, size, verified=False)
        return {sha: found.get(sha) for sha in wanted}

    def readable_first(self, volumes: Iterable[str]) -> list[str]:
        return list(dict.fromkeys(volumes))

    def homes(self) -> dict[str, str]:
        return {}

    def volume_names(self) -> list[str]:
        return [self.name]

    def volume_status(self, name: str) -> VolumeStatus:
        if name == self.name:
            return VolumeStatus(VOLUME_ONLINE)
        return VolumeStatus(
            VOLUME_OFFLINE,
            f"there is no drive '{name}': this project's files are in a bucket",
            "",
        )

    def offline_location(self, sha256: str) -> tuple[str, VolumeStatus] | None:
        return None

    # -- looking after it ---------------------------------------------------

    def iter_objects(self) -> Iterator[StoredObjectInfo]:
        """Every object in the bucket under the prefix, a page at a time: what
        is actually there, which is what a clean-up sweeps against."""
        pages = self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self._cfg.bucket,
            Prefix=f"{self._cfg.prefix}/" if self._cfg.prefix else "",
        )
        for page in pages:
            for item in page.get("Contents", []):
                sha = self._sha_of(item["Key"])
                if sha is None:
                    continue
                modified = item.get("LastModified")
                yield StoredObjectInfo(
                    sha256=sha,
                    volume=self.name,
                    size=int(item["Size"]),
                    mtime=modified.timestamp() if modified else time.time(),
                )

    def reconcile_inventory(self) -> dict[str, int]:
        """Bring `stored_objects` in line with the bucket: a row for every
        object there (an unknown one unverified, until a read-back), and no
        row for one that is gone."""
        if self._session is None:
            return {"added_or_updated": 0, "removed": 0}
        present: set[str] = set()
        batch: list[tuple[str, str, int]] = []
        for obj in self.iter_objects():
            present.add(obj.sha256)
            batch.append((obj.sha256, self.name, obj.size))
            if len(batch) >= _RECONCILE_BATCH:
                inventory.upsert_copies(self._session, batch, verified=False)
                batch = []
        if batch:
            inventory.upsert_copies(self._session, batch, verified=False)
        removed = inventory.remove_absent(
            self._session, self.name, present, _RECONCILE_BATCH
        )
        return {"added_or_updated": len(present), "removed": removed}

    def sweep_stale_scratch(
        self, older_than_seconds: float, dry_run: bool = False
    ) -> int:
        """Multipart uploads begun more than `older_than_seconds` ago and never
        completed (an uploader that went away): counted, and unless `dry_run`
        aborted, which frees the parts."""
        cutoff = time.time() - older_than_seconds
        count = 0
        pages = self.client.get_paginator("list_multipart_uploads").paginate(
            Bucket=self._cfg.bucket,
            Prefix=f"{self._cfg.prefix}/" if self._cfg.prefix else "",
        )
        for page in pages:
            for upload in page.get("Uploads", []):
                begun = upload.get("Initiated")
                if begun is not None and begun.timestamp() >= cutoff:
                    continue
                count += 1
                if not dry_run:
                    self._call(
                        self.client.abort_multipart_upload,
                        Bucket=self._cfg.bucket,
                        Key=upload["Key"],
                        UploadId=upload["UploadId"],
                    )
        return count

    @contextlib.contextmanager
    def gc_lock(self) -> Iterator[None]:
        """One clean-up at a time in this process. (A host running clean-ups
        for many projects runs each project's in turn.)"""
        if not self._gc.acquire(blocking=False):
            raise GCAlreadyRunningError(
                "A clean-up is already running against this bucket. Wait for it "
                "to finish and retry."
            )
        try:
            yield
        finally:
            self._gc.release()

    def verify(self) -> list[str]:
        """Read back every copy recorded unverified (one that went in by parts,
        or that a reconcile found) and hash it: a match is marked verified; a
        mismatch is removed from the bucket and the inventory, and returned,
        so the records citing it show the file as missing rather than serve
        the wrong bytes."""
        if self._session is None:
            return []
        bad: list[str] = []
        after = ""
        while True:
            page = inventory.unverified(self._session, self.name, after, 100)
            if not page:
                return bad
            good: list[str] = []
            for sha in page:
                hasher = hashlib.sha256()
                try:
                    with self.open(sha) as f:
                        while chunk := f.read(_CHUNK):
                            hasher.update(chunk)
                except FileNotFoundError:
                    self._unregister(sha)
                    continue
                if hasher.hexdigest() == sha:
                    good.append(sha)
                else:
                    log.warning("Object %s in the bucket does not hash to its key", sha)
                    self.delete(sha)
                    bad.append(sha)
            inventory.mark_verified(self._session, self.name, good)
            after = page[-1]

    # -- straight to the bucket (`direct_files`) -----------------------------

    def upload_target(self, sha256: str, size: int) -> DirectUpload | None:
        if not self._cfg.direct:
            return None
        bucket, key = self._cfg.bucket, self.key_of(sha256)
        expires = int(time.time()) + UPLOAD_SECONDS
        if size <= SINGLE_PUT_MAX:
            # S3 checks the whole object against this hash before keeping it.
            url = self._call(
                self.client.generate_presigned_url,
                "put_object",
                Params={"Bucket": bucket, "Key": key, "ChecksumSHA256": _b64(sha256)},
                ExpiresIn=UPLOAD_SECONDS,
                HttpMethod="PUT",
            )
            return DirectUpload(
                url=url,
                headers={"x-amz-checksum-sha256": _b64(sha256)},
                upload_id=None,
                part_size=size,
                parts=[],
                expires_at=expires,
            )
        part_size = max(PART_SIZE, math.ceil(size / MAX_PARTS))
        part_size = math.ceil(part_size / (1024**2)) * 1024**2
        begun = self._call(self.client.create_multipart_upload, Bucket=bucket, Key=key)
        upload_id = begun["UploadId"]
        parts = [
            DirectPart(
                number=n,
                url=self._call(
                    self.client.generate_presigned_url,
                    "upload_part",
                    Params={
                        "Bucket": bucket,
                        "Key": key,
                        "UploadId": upload_id,
                        "PartNumber": n,
                    },
                    ExpiresIn=UPLOAD_SECONDS,
                    HttpMethod="PUT",
                ),
            )
            for n in range(1, math.ceil(size / part_size) + 1)
        ]
        return DirectUpload(
            url=None,
            headers={},
            upload_id=upload_id,
            part_size=part_size,
            parts=parts,
            expires_at=expires,
        )

    def complete_upload(
        self,
        sha256: str,
        size: int,
        original_filename: str,
        upload_id: str | None = None,
        parts: list[UploadedPart] | None = None,
    ) -> FileRef:
        bucket, key = self._cfg.bucket, self.key_of(sha256)
        if upload_id is not None:
            self._call(
                self.client.complete_multipart_upload,
                Bucket=bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={
                    "Parts": [
                        {"ETag": p.etag, "PartNumber": p.number}
                        for p in sorted(parts or [], key=lambda p: p.number)
                    ]
                },
            )
        found = self._head(sha256)
        if found is None:
            raise ValidationError("The upload did not arrive in the bucket")
        if found != size:
            self._call(self.client.delete_object, Bucket=bucket, Key=key)
            raise ValidationError(
                f"The upload is {found} bytes, not the {size} announced; it was removed"
            )
        # One PUT was checked against the hash by S3 itself; parts were each
        # checked, but the whole waits for a read-back (`verify`).
        self._register(sha256, size, verified=upload_id is None)
        return self._ref(sha256, original_filename, size)

    def download_url(self, sha256: str, filename: str | None = None) -> str | None:
        """None unless the bucket is known to hold the file: a redirect to a
        404 would hide that the file isn't here."""
        if not self._cfg.direct or not self.exists(sha256):
            return None
        params: dict[str, Any] = {
            "Bucket": self._cfg.bucket,
            "Key": self.key_of(sha256),
        }
        if filename:
            params["ResponseContentDisposition"] = attachment(filename)
        return str(
            self._call(
                self.client.generate_presigned_url,
                "get_object",
                Params=params,
                ExpiresIn=DOWNLOAD_SECONDS,
            )
        )

    # -- inventory ----------------------------------------------------------

    def _register(self, sha256: str, size: int, *, verified: bool) -> None:
        if self._session is not None:
            inventory.upsert_copies(
                self._session, [(sha256, self.name, size)], verified=verified
            )

    def _unregister(self, sha256: str) -> None:
        if self._session is not None:
            inventory.forget_copy(self._session, sha256, self.name)
