"""Copy content-addressed files from one object store to another.

`copy_objects(source, destination, shas)` is the one public way for a host to
move a set of files between two stores (a hub copying a release's files from
one repo's location to another's). It is also reached as
`civex.context.copy_objects`.

Which way the bytes travel depends on the two stores:

- drive to drive: a hard link where both are on one filesystem, else a copy
  (hashed on the way, so a bad source is never stored under the wrong name);
- bucket to bucket on the same endpoint, profile and region: the bucket copies
  it itself (`copy_object`; `upload_part_copy` in parts past 5 GiB), so the
  bytes never reach this machine;
- anything else (a bucket with other credentials, drive to bucket and back):
  streamed, never through a temporary file the size of the object. Into a
  bucket from a bucket it is a multipart upload fed from the ranged reader.

The destination's inventory is written exactly as a normal put writes it (its
own session, if it has one; the caller commits, or passes `commit`, called
after each file that was stored). A file the destination already holds is
left alone, so a run can be repeated.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from civex.domain.exceptions import ValidationError

_SHA = re.compile(r"[0-9a-f]{64}")
_CHUNK = 1024 * 1024


@dataclass
class CopyResult:
    copied: int = 0
    skipped: int = 0  # the destination already held them
    absent: list[str] = field(default_factory=list)  # the source doesn't hold them
    bytes_copied: int = 0
    # How the copied ones travelled: "link", "copy", "server_side", "stream".
    methods: dict[str, int] = field(default_factory=dict)


def copy_objects(
    source: Any,
    destination: Any,
    shas: Iterable[str],
    *,
    on_progress: Callable[[int, int], None] | None = None,
    commit: Callable[[], None] | None = None,
) -> CopyResult:
    """Copy the files `shas` (sha256 hex) from `source` to `destination`, both
    stores from `civex.context.make_store`.

    Every sha is checked (`^[0-9a-f]{64}$`) before anything is copied;
    ValidationError otherwise. A file the destination holds is skipped; one the
    source doesn't hold is listed in `absent` (the caller decides what a
    missing file means). Duplicates count once.

    `on_progress(done, total)` is called after each file is dealt with
    (copied, skipped or absent); `total` is the number of distinct shas.
    `commit` is called after each file that was stored, for a destination with
    a session the caller wants committed as it goes (a lost lease then keeps
    the work done). A file that comes out as other bytes than its name says is
    never stored under that name: ValidationError. Idempotent."""
    wanted = list(dict.fromkeys(shas))
    for sha in wanted:
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise ValidationError("Not a file hash: expected 64 lowercase hex digits")
    total = len(wanted)
    result = CopyResult()
    have = destination.exists_many(wanted)
    done = 0
    for sha in wanted:
        if sha in have:
            result.skipped += 1
        else:
            moved = _copy_one(source, destination, sha)
            if moved is None:
                result.absent.append(sha)
            else:
                how, size = moved
                if how != "present":
                    result.copied += 1
                    result.bytes_copied += size
                    result.methods[how] = result.methods.get(how, 0) + 1
                    if commit:
                        commit()
                else:
                    result.skipped += 1
        done += 1
        if on_progress:
            on_progress(done, total)
    return result


def _same_account(a: Any, b: Any) -> bool:
    """Two buckets one set of credentials reaches: same endpoint, profile and
    region (credentials are never in the settings, only these name them)."""
    ca, cb = a._cfg, b._cfg
    return (ca.endpoint, ca.profile, ca.region) == (cb.endpoint, cb.profile, cb.region)


def _copy_one(source: Any, destination: Any, sha: str) -> tuple[str, int] | None:
    """(how, size) once stored, ("present", 0) if it appeared meanwhile, None
    when the source hasn't got it."""
    from civex.domain.exceptions import VolumeUnavailableError
    from civex.repositories.local.file_store import VolumeAwareFileObjectStore
    from civex.repositories.s3.store import S3ObjectStore

    src_drive = isinstance(source, VolumeAwareFileObjectStore)
    dst_drive = isinstance(destination, VolumeAwareFileObjectStore)
    src_s3 = isinstance(source, S3ObjectStore)
    dst_s3 = isinstance(destination, S3ObjectStore)

    if src_drive and dst_drive:
        try:
            path = source.object_path(sha)
        except FileNotFoundError:
            return None
        size = path.stat().st_size
        return destination.import_object(sha, path), size

    if src_s3:
        size = source.size_of(sha)
        if size is None:
            return None
        if dst_s3:
            if _same_account(source, destination):
                try:
                    destination.copy_from(source, sha, size)
                    return "server_side", size
                except VolumeUnavailableError:
                    pass  # not allowed across these buckets: stream it instead
                except FileNotFoundError:
                    return None
            try:
                reader = source.open(sha)
            except FileNotFoundError:
                return None
            with reader:
                if not destination.put_reader(reader, sha, size):
                    return "present", 0
            return "stream", size
        try:
            reader = source.open(sha)
        except FileNotFoundError:
            return None
        with reader:
            ref = destination.put_chunks(
                iter(lambda: reader.read(_CHUNK), b""), sha, size_hint=size
            )
        _same_content(ref.sha256, sha)
        return "stream", size

    if src_drive and dst_s3:
        try:
            path = source.object_path(sha)
        except FileNotFoundError:
            return None
        ref = destination.put_path(path, sha)
        _same_content(ref.sha256, sha)
        return "stream", ref.size

    # Any other pair of stores that follow the protocol.
    try:
        reader = source.open(sha)
    except FileNotFoundError:
        return None
    with reader:
        ref = destination.put_chunks(iter(lambda: reader.read(_CHUNK), b""), sha)
    _same_content(ref.sha256, sha)
    return "stream", ref.size


def _same_content(found: str, wanted: str) -> None:
    if found != wanted:
        raise ValidationError(
            f"The source's bytes for {wanted} hash to {found}; it was not stored "
            "under that name"
        )
