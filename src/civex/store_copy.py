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

import hashlib
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
    if have and getattr(destination, "has_inventory", False):
        # A bucket's inventory can be stale: believe only what the bucket says
        # (without one, exists_many has already asked the bucket).
        have = destination.confirm_held(have)
    if have and commit:
        commit()  # looking found (and recorded) files the inventory didn't know
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
                if how == "present":
                    result.skipped += 1
                else:
                    result.copied += 1
                    result.bytes_copied += size
                    result.methods[how] = result.methods.get(how, 0) + 1
                    if commit:
                        commit()
        done += 1
        if on_progress:
            on_progress(done, total)
    return result


def _same_account(a: Any, b: Any) -> bool:
    """Two buckets one set of credentials reaches: the very same client, or
    (for stores that build their own) the same endpoint, profile and region
    (credentials are never in the settings, only these name them). A client
    handed in is only known to be the same account as itself."""
    if a._injected or b._injected:
        return a._client is b._client
    ca, cb = a._cfg, b._cfg

    def key(c: Any) -> tuple[Any, ...]:
        return (
            c.endpoint,
            c.profile,
            c.region,
            c.access_key_env,
            c.secret_key_env,
            c.session_token_env,
        )

    return key(ca) == key(cb)


def _read_or_none(source: Any, sha: str) -> Any:
    try:
        return source.open(sha)
    except FileNotFoundError:
        return None


def _copy_one(source: Any, destination: Any, sha: str) -> tuple[str, int] | None:
    """(how, size) once stored, ("present", 0) if it appeared meanwhile, None
    when the source hasn't got it (or lost it meanwhile)."""
    from civex.domain.exceptions import VolumeUnavailableError
    from civex.repositories.local.file_store import VolumeAwareFileObjectStore
    from civex.repositories.s3.store import S3ObjectStore, _is_missing

    src_drive = isinstance(source, VolumeAwareFileObjectStore)
    dst_drive = isinstance(destination, VolumeAwareFileObjectStore)
    src_s3 = isinstance(source, S3ObjectStore)
    dst_s3 = isinstance(destination, S3ObjectStore)

    def drive_path() -> Any:
        try:
            return source.object_path(sha)
        except FileNotFoundError:
            return None

    try:
        if src_drive:
            path = drive_path()
            if path is None:
                return None
            if dst_drive:
                how, size = destination.import_object(sha, path)
                return None if how == "absent" else (how, size)
            if dst_s3:
                return "stream", destination.put_path_expecting(path, sha)
        elif src_s3:
            size = source.size_of(sha)
            if size is None:
                return None
            if dst_s3:
                if _same_account(source, destination):
                    try:
                        destination.copy_from(source, sha, size)
                        return "server_side", size
                    except VolumeUnavailableError:
                        pass  # not allowed across these buckets: stream it
                reader = _read_or_none(source, sha)
                if reader is None:
                    return None
                with reader:
                    if not destination.put_reader(reader, sha, size):
                        return "present", 0
                return "stream", size
            if dst_drive:
                reader = _read_or_none(source, sha)
                if reader is None:
                    return None
                with reader:
                    how = destination.import_chunks(
                        sha, iter(lambda: reader.read(_CHUNK), b""), size
                    )
                return ("present", 0) if how == "present" else (how, size)
    except FileNotFoundError:
        return None  # the source lost it meanwhile
    except Exception as e:
        if src_s3 and _is_missing(e):
            return None
        raise

    # Any other pair of stores that follow the protocol: hashed first, so
    # wrong bytes are never handed to the destination.
    reader = _read_or_none(source, sha)
    if reader is None:
        return None
    with reader:
        if not (hasattr(reader, "seekable") and reader.seekable()):
            raise ValidationError("A store's reader must be seekable to be copied")
        hasher = hashlib.sha256()
        size = 0
        while chunk := reader.read(_CHUNK):
            hasher.update(chunk)
            size += len(chunk)
        _same_content(hasher.hexdigest(), sha)
        reader.seek(0)
        again = hashlib.sha256()

        def chunks() -> Any:
            while chunk := reader.read(_CHUNK):
                again.update(chunk)
                yield chunk

        ref = destination.put_chunks(chunks(), sha)
    _same_content(again.hexdigest(), sha)  # it changed between the two reads
    _same_content(ref.sha256, sha)
    return "stream", size


def _same_content(found: str, wanted: str) -> None:
    if found != wanted:
        raise ValidationError(
            f"The source's bytes for {wanted} hash to {found}; it was not stored "
            "under that name"
        )
