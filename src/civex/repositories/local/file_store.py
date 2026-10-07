"""
Volume-aware content-addressed file store.

Files are stored at:
    <volume_path>/<sha256[:2]>/<sha256[2:]>

On write, the store walks the configured queue and picks the first volume that
passes both gates:
  1. Civex allocation: civex_used + incoming_size <= allocated_gb
  2. Physical disk headroom: disk_free > full_below_gb

Each volume also gets a <volume_path>/manifest.jsonl -- one JSON line per
object recording {sha256, filename, size} the first time it's written. Object
paths carry no filename or extension of their own, so this is what makes a
copy of the volume directory self-describing without the database: someone
with only the raw files (no civex install, no DB) can still tell what each
blob originally was.

On read, volumes are searched in definition order. The `volume` field in
FileRef is a fast hint but resolution always falls back to scanning.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import threading
import json
import logging
import os
import shutil
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterable, Callable, Iterable, Iterator, cast

from civex import fs_locations
from civex.processes import pid_alive
from civex.config import StoreConfig, VolumeConfig
from civex.domain.dtos import (
    VOLUME_OFFLINE,
    VOLUME_ONLINE,
    VOLUME_READONLY,
    VOLUME_RETIRED,
    VOLUME_WRONG_DRIVE,
    FileCopy,
    FileRef,
    StoredObjectInfo,
    VolumeStatus,
)
from civex.domain.placement import PLACEMENT_FAIL
from civex.domain.transfers import (
    CopyResult,
    ItemFailed,
    TargetFull,
    TransferStopped,
    VolumeNotResponding,
)
from civex.domain.exceptions import (
    AllVolumesFull,
    GCAlreadyRunningError,
    VolumeUnavailableError,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

_HEX2_RE = re.compile(r"^[0-9a-f]{2}$")
_HEX62_RE = re.compile(r"^[0-9a-f]{62}$")
_COPY_CHUNK = 1024 * 1024
_RECONCILE_BATCH = 5000
_MANIFEST_READ_LIMIT = 256 * 1024 * 1024  # larger manifests aren't read for names
_LOCATE_CHUNK = 500  # inventory lookups per query
_LOCATE_DISK_FALLBACK = 25  # blobs the inventory doesn't know, looked up on disk

_SCRATCH_DIRNAME = ".tmp"
_MARKER_FILENAME = ".civex-volume"
_GC_LOCK_FILENAME = ".gc.lock"
_TRANSFER_LOCK_FILENAME = ".transfer.lock"
# A copy that moves no bytes at all for this long is treated as its volume having
# stopped answering (a stuck network write can't be interrupted from outside).
STALL_SECONDS = 60.0
# While a finished write is being flushed to disk (one call that can't report
# progress) a copy may go quiet for size / this rate, if that is longer than
# STALL_SECONDS: a big file on a slow drive can take minutes to flush.
_MIN_SYNC_BYTES_PER_SECOND = 2 * 1024 * 1024
# Long enough that no real GC pass should ever take this long; a lock file
# older than this is assumed to be left behind by a process that crashed
# mid-run rather than one still working, and is reclaimed rather than
# deadlocking every future run.
_GC_LOCK_STALE_SECONDS = 3600


def _probe_root(root: Path) -> tuple[str | None, str | None]:
    """(why `root` can't be used, or None; the volume marker found there).

    Everything here can block on a dead network mount, so callers outside the
    project go through `fs_locations.guarded`."""
    try:
        if not root.exists():
            return f"path missing: {root}", None
        if not root.is_dir():
            return f"not a directory: {root}", None
        if not os.access(root, os.R_OK | os.X_OK):
            return f"not readable: {root}", None
    except OSError as e:  # e.g. a stale mount
        return f"cannot reach {root}: {e}", None
    return None, _read_marker(root)


class _CopyJob:
    """Shared between a copy and whoever is watching it."""

    def __init__(self) -> None:
        self.size = 0
        self.bytes = 0
        self.reused = False
        self.last_progress = time.monotonic()
        self.syncing = False
        self.abort = threading.Event()
        self.error: BaseException | None = None

    def touch(self) -> None:
        self.last_progress = time.monotonic()

    def stall_limit(self) -> float:
        """Seconds without progress before the copy counts as stalled."""
        if self.syncing:
            return max(STALL_SECONDS, self.size / _MIN_SYNC_BYTES_PER_SECOND)
        return STALL_SECONDS


def _hash_file(path: Path, job: _CopyJob | None = None) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_COPY_CHUNK):
            if job is not None:
                if job.abort.is_set():
                    raise TransferStopped()
                job.touch()
            hasher.update(chunk)
    return hasher.hexdigest()


def _read_marker(root: Path) -> str | None:
    """The volume id in `root`'s marker file, or None if there is no valid one."""
    try:
        return str(uuid.UUID((root / _MARKER_FILENAME).read_text("utf-8").strip()))
    except (OSError, ValueError):
        return None


class VolumeAwareFileObjectStore:
    def __init__(
        self,
        store_config: StoreConfig,
        project_root: Path,
        session: Session | None = None,
    ) -> None:
        """With a `session`, per-volume usage is read from the
        `stored_objects` inventory table (see db.models.StoredObject) rather
        than by walking the volume, and survives across requests. Without
        one (standalone use, tests), usage falls back to a cached directory
        walk."""
        self._cfg = store_config
        self._root = project_root
        self._session = session
        self._used_cache: dict[str, int] = {}
        self._bootstrapped: set[str] = set()

    # ------------------------------------------------------------------
    # Protocol implementation
    # ------------------------------------------------------------------

    def put(
        self, data: bytes, original_filename: str, collection_id: str | None = None
    ) -> FileRef:
        sha256 = hashlib.sha256(data).hexdigest()
        size = len(data)

        # If the content is already stored anywhere, reuse it (idempotent).
        # Placement never overrides this: a collection's home volume decides
        # where *new* content goes, not whether to copy existing content.
        existing = self._existing_copy(sha256)
        if existing is not None:
            return self._reuse(existing, sha256, original_filename, size)

        reasons: list[str] = []
        for vol_name in self._write_candidates(collection_id):
            can, reason = self._can_write(vol_name, size)
            if not can:
                reasons.append(f"{vol_name}: {reason}")
                continue

            try:
                tmp_path = self._scratch_path(vol_name)
            except VolumeUnavailableError as e:
                reasons.append(f"{vol_name}: {e}")
                continue
            dest = self._object_path(sha256, vol_name)
            try:
                # Written to a scratch file and renamed into place, same as
                # put_stream() -- a write that fails partway (e.g. ENOSPC)
                # never leaves a truncated/corrupt blob sitting at the
                # content-addressed path, since dest is only ever created by
                # an atomic same-filesystem rename.
                tmp_path.write_bytes(data)
                dest.parent.mkdir(exist_ok=True)
                os.replace(tmp_path, dest)
            except OSError as e:
                tmp_path.unlink(missing_ok=True)
                if e.errno == errno.ENOSPC:
                    reasons.append(f"{vol_name}: no space left on device")
                    continue
                raise VolumeUnavailableError(
                    f"Cannot write to volume '{vol_name}': {e}"
                ) from e

            self._register(vol_name, sha256, size)
            self._append_manifest_best_effort(vol_name, sha256, original_filename, size)
            return FileRef(
                sha256=sha256,
                filename=original_filename,
                size=size,
                volume=vol_name,
            )

        raise self._all_volumes_full(size, reasons, collection_id)

    async def put_stream(
        self,
        chunks: AsyncIterable[bytes],
        original_filename: str,
        size_hint: int | None = None,
        collection_id: str | None = None,
    ) -> FileRef:
        """Stream-write `chunks` straight to disk, hashing incrementally so
        the full content never has to fit in memory at once -- unlike put(),
        which needs the whole object in a single `bytes` up front. Chunks
        are written to a scratch file on the chosen volume and the file is
        renamed into its content-addressed path once the digest is known;
        same-filesystem rename is atomic, so a reader can never observe a
        partially-written object at its final path.

        Unlike put(), volume selection can't fall back mid-stream: once
        bytes have been consumed from `chunks` (typically a live HTTP
        request body), they can't be replayed against a different volume.
        `size_hint` (e.g. a Content-Length header), when known upfront,
        still lets the allocation/headroom gate reject an unsuitable volume
        before a single byte is written; without it, running out of space
        partway through fails the upload outright instead of retrying on
        the next volume in queue.
        """
        vol_name, tmp_path = self._open_scratch(size_hint, collection_id)
        hasher = hashlib.sha256()
        size = 0
        try:
            with tmp_path.open("wb") as f:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    hasher.update(chunk)
                    f.write(chunk)
                    size += len(chunk)
        except BaseException as e:
            tmp_path.unlink(missing_ok=True)
            if isinstance(e, OSError):
                raise self._write_error(vol_name, e, size, streamed=True) from e
            raise
        return self._finalize(
            vol_name, tmp_path, hasher.hexdigest(), size, original_filename
        )

    def put_chunks(
        self,
        chunks: Iterable[bytes],
        original_filename: str,
        size_hint: int | None = None,
        collection_id: str | None = None,
        volume: str | None = None,
    ) -> FileRef:
        """`put_stream` for chunks that arrive in this thread (a download from
        the server): written straight to a scratch file on the drive they go
        to, hashed as they come, then renamed into place, so each byte is
        written once. `volume` names the drive, else the collection's."""
        vol_name, tmp_path = self._open_scratch(size_hint, collection_id, volume)
        hasher = hashlib.sha256()
        size = 0
        try:
            with tmp_path.open("wb") as f:
                for chunk in chunks:
                    if not chunk:
                        continue
                    hasher.update(chunk)
                    f.write(chunk)
                    size += len(chunk)
        except BaseException as e:
            tmp_path.unlink(missing_ok=True)
            if isinstance(e, OSError):
                raise self._write_error(vol_name, e, size, streamed=True) from e
            raise
        return self._finalize(
            vol_name, tmp_path, hasher.hexdigest(), size, original_filename
        )

    def put_path(
        self,
        path: Path,
        original_filename: str | None = None,
        collection_id: str | None = None,
        volume: str | None = None,
    ) -> FileRef:
        """Store a file from disk by copying it in fixed-size chunks, so a
        multi-GB file never has to fit in memory (put(path.read_bytes())
        would). Unlike put_stream, the source is replayable, so a volume that
        runs out of space partway through falls through to the next one.
        `volume` names the one drive to write to (a person chose it, e.g. a
        file downloaded to be moved there), instead of the collection's."""
        name = original_filename or path.name
        size = path.stat().st_size
        reasons: list[str] = []
        candidates = [volume] if volume else self._write_candidates(collection_id)
        for vol_name in candidates:
            can, reason = self._can_write(vol_name, size)
            if not can:
                reasons.append(f"{vol_name}: {reason}")
                continue
            try:
                tmp_path = self._scratch_path(vol_name)
            except VolumeUnavailableError as e:
                reasons.append(f"{vol_name}: {e}")
                continue
            hasher = hashlib.sha256()
            written = 0
            try:
                with path.open("rb") as src, tmp_path.open("wb") as dst:
                    while chunk := src.read(_COPY_CHUNK):
                        hasher.update(chunk)
                        dst.write(chunk)
                        written += len(chunk)
            except OSError as e:
                tmp_path.unlink(missing_ok=True)
                if e.errno == errno.ENOSPC:
                    reasons.append(f"{vol_name}: no space left on device")
                    continue
                raise self._write_error(vol_name, e, written, streamed=False) from e
            return self._finalize(vol_name, tmp_path, hasher.hexdigest(), written, name)
        raise self._all_volumes_full(size, reasons, collection_id)

    # -- shared write plumbing -------------------------------------------

    # -- placement and dedup: one place each ------------------------------

    def _write_candidates(self, collection_id: str | None) -> list[str]:
        """The volumes to try for a new write, in order. A collection with a
        placement tries its home first -- which need not be in the general
        write queue -- then, unless it is set to fail, the queue. Everything
        that picks a volume for new content calls this."""
        queue = list(self._cfg.volume_queue)
        place = self._cfg.placement.get(collection_id) if collection_id else None
        if place is None or place.volume not in self._cfg.volumes:
            return queue
        if place.on_unavailable == PLACEMENT_FAIL:
            return [place.volume]
        return [place.volume, *(v for v in queue if v != place.volume)]

    def _all_volumes_full(
        self, size: int | None, reasons: list[str], collection_id: str | None
    ) -> AllVolumesFull:
        place = self._cfg.placement.get(collection_id) if collection_id else None
        fail = place is not None and place.on_unavailable == PLACEMENT_FAIL
        what = f" for {size / 1_048_576:.1f} MB" if size else ""
        head = (
            f"This collection's home volume '{place.volume}' can't take the file"
            f"{what}, and the collection is set to fail rather than use another volume."
            if fail and place is not None
            else f"No volume in queue has space{what}."
        )
        return AllVolumesFull(f"{head} " + "; ".join(reasons))

    def _existing_copy(self, sha256: str) -> tuple[str, Path | None] | None:
        """(volume, path) of content that is already stored, so it is reused
        and never written twice. `path` is None when the only copy is on a
        volume that can't be reached right now: the inventory says it is
        there, and the same content is not copied onto another volume just
        because the first one is unplugged."""
        located = self._locate(sha256)
        if located is not None:
            return located
        return self._offline_copy(sha256)

    def _offline_copy(self, sha256: str) -> tuple[str, None] | None:
        if self._session is None:
            return None
        from civex.db.models import StoredObject

        row = self._session.get(StoredObject, sha256)
        if row is None or row.volume not in self._cfg.volumes:
            return None
        if self.volume_status(row.volume).reachable:
            return None  # reachable but the file is gone: the row is stale
        return row.volume, None

    def _reuse(
        self,
        existing: tuple[str, Path | None],
        sha256: str,
        filename: str,
        size: int,
    ) -> FileRef:
        volume, path = existing
        if path is not None:
            self._touch(path)  # refreshes mtime, so GC's grace period protects it
        return FileRef(sha256=sha256, filename=filename, size=size, volume=volume)

    def _scratch_path(self, vol_name: str) -> Path:
        """A fresh scratch path on `vol_name`. Creates only the scratch
        directory itself, never the volume root: if the volume went away
        after `_can_write` checked it, this fails instead of quietly
        recreating the root on the parent filesystem."""
        scratch_dir = self._resolve_path(self._cfg.volumes[vol_name]) / _SCRATCH_DIRNAME
        try:
            scratch_dir.mkdir(exist_ok=True)
        except OSError as e:
            raise VolumeUnavailableError(
                f"Cannot write to volume '{vol_name}': {e}"
            ) from e
        return scratch_dir / f"{uuid.uuid4().hex}.part"

    def _open_scratch(
        self,
        size_hint: int | None,
        collection_id: str | None = None,
        volume: str | None = None,
    ) -> tuple[str, Path]:
        """First candidate volume passing the allocation/headroom gates (or
        the one `volume` named), plus a fresh scratch path on it."""
        reasons: list[str] = []
        candidates = [volume] if volume else self._write_candidates(collection_id)
        for vol_name in candidates:
            can, reason = self._can_write(vol_name, size_hint or 0)
            if not can:
                reasons.append(f"{vol_name}: {reason}")
                continue
            try:
                return vol_name, self._scratch_path(vol_name)
            except VolumeUnavailableError as e:
                reasons.append(f"{vol_name}: {e}")
        raise self._all_volumes_full(size_hint, reasons, collection_id)

    @staticmethod
    def _write_error(
        vol_name: str, e: OSError, written: int, *, streamed: bool
    ) -> VolumeUnavailableError:
        if e.errno == errno.ENOSPC and streamed:
            return VolumeUnavailableError(
                f"Volume '{vol_name}' ran out of space mid-upload "
                f"({written / 1_048_576:.1f} MB written); the upload "
                "can't resume on another volume once bytes have "
                "been streamed -- retry the upload from the start."
            )
        return VolumeUnavailableError(f"Cannot write to volume '{vol_name}': {e}")

    def _finalize(
        self,
        vol_name: str,
        tmp_path: Path,
        sha256: str,
        size: int,
        original_filename: str,
    ) -> FileRef:
        """Rename a fully-written scratch file into its content-addressed
        path, or discard it if the same content is already stored."""
        existing = self._existing_copy(sha256)
        if existing is not None:
            tmp_path.unlink(missing_ok=True)
            return self._reuse(existing, sha256, original_filename, size)
        dest = self._object_path(sha256, vol_name)
        try:
            dest.parent.mkdir(exist_ok=True)
            os.replace(tmp_path, dest)
        except OSError as e:
            tmp_path.unlink(missing_ok=True)
            raise VolumeUnavailableError(
                f"Cannot finalize upload on volume '{vol_name}': {e}"
            ) from e
        self._register(vol_name, sha256, size)
        self._append_manifest_best_effort(vol_name, sha256, original_filename, size)
        return FileRef(
            sha256=sha256, filename=original_filename, size=size, volume=vol_name
        )

    def get(self, sha256: str) -> bytes:
        path = self._find_object(sha256)
        if path is None:
            raise FileNotFoundError(f"Object {sha256} not found in any volume")
        return path.read_bytes()

    def exists(self, sha256: str) -> bool:
        return self._find_object(sha256) is not None

    # -- where is it? -------------------------------------------------------

    def locate_volumes(self, shas: Iterable[str]) -> dict[str, str | None]:
        """The volume each blob is on, for a whole batch at once. Reads the
        inventory in a few queries, and only looks on disk for blobs it doesn't
        know (an older blob, a request that was rolled back), and for a bounded
        number of those, so listing many records never means a stat per file."""
        wanted = list(dict.fromkeys(shas))
        found: dict[str, str | None] = {}
        if self._session is not None and wanted:
            from sqlalchemy import select

            from civex.db.models import StoredObject

            for i in range(0, len(wanted), _LOCATE_CHUNK):
                rows = self._session.execute(
                    select(StoredObject.sha256, StoredObject.volume).where(
                        StoredObject.sha256.in_(wanted[i : i + _LOCATE_CHUNK])
                    )
                )
                for sha, volume in rows:
                    if volume in self._cfg.volumes:
                        found[sha] = volume
        for sha in [s for s in wanted if s not in found][:_LOCATE_DISK_FALLBACK]:
            located = self._locate(sha)
            if located is not None:
                found[sha] = located[0]
        return {sha: found.get(sha) for sha in wanted}

    def copies_of(self, sha256: str) -> list[FileCopy]:
        """Every place this content is: each reachable volume that holds it,
        plus the volume the inventory records it on if that one can't be
        reached now (so a file on an unplugged drive is still accounted for)."""
        recorded = self._recorded_volume(sha256)
        mounts = fs_locations.all_mounts()
        copies: list[FileCopy] = []
        for name in self._cfg.volumes:
            path = self._object_path(sha256, name)
            status = self.volume_status(name)
            network = fs_locations.is_network_path(
                fs_locations.normalise(str(path)), mounts
            )
            if status.reachable:
                try:
                    present = path.exists()
                except OSError:
                    present = None
                if present is not False:
                    copies.append(
                        FileCopy(name, str(path), present, status.state, network)
                    )
            elif name == recorded:
                copies.append(FileCopy(name, str(path), None, status.state, network))
        return copies

    def size_of(self, sha256: str) -> int | None:
        """The blob's size: from the inventory, else from a copy on disk."""
        if self._session is not None:
            from civex.db.models import StoredObject

            row = self._session.get(StoredObject, sha256)
            if row is not None:
                return int(row.size)
        located = self._locate(sha256)
        if located is None:
            return None
        try:
            return located[1].stat().st_size
        except OSError:
            return None

    def offline_location(self, sha256: str) -> tuple[str, VolumeStatus] | None:
        """(volume, its status) if this content is recorded on a volume that
        can't be reached right now, so "gone" can be told from "not plugged in"."""
        copy = self._offline_copy(sha256)
        if copy is None:
            return None
        return copy[0], self.volume_status(copy[0])

    def _recorded_volume(self, sha256: str) -> str | None:
        if self._session is None:
            return None
        from civex.db.models import StoredObject

        row = self._session.get(StoredObject, sha256)
        return row.volume if row is not None else None

    def path_on(self, sha256: str, volume: str) -> Path:
        """Where this content would be on `volume`: pure path arithmetic, no
        disk access, for a caller that already knows the volume (from the
        inventory) and so needn't search every volume for it."""
        return self._object_path(sha256, volume)

    def object_path(self, sha256: str) -> Path:
        path = self._find_object(sha256)
        if path is None:
            raise FileNotFoundError(f"Object {sha256} not found in any volume")
        return path

    def iter_objects(self) -> Iterator[StoredObjectInfo]:
        """Every object actually on disk, across every configured volume --
        including volumes no longer in the write queue -- yielded one at a
        time so callers (GC) never hold the whole listing in memory. Walks
        the volume directories rather than trusting manifest.jsonl or the
        inventory table: the manifest is append-only and best-effort, and
        the inventory is a cache of this very walk, so neither is the
        authoritative existence check GC sweeps against.
        """
        for name in self._cfg.volumes:
            yield from self._walk_volume(name)

    def volume_names(self) -> list[str]:
        """Every configured volume, in the queue or not."""
        return list(self._cfg.volumes)

    def list_objects(self) -> list[StoredObjectInfo]:
        """Materialised `iter_objects()`, for callers that want a list."""
        return list(self.iter_objects())

    def _walk_volume(
        self, name: str, *, strict: bool = False
    ) -> Iterator[StoredObjectInfo]:
        """Lazily scan `<root>/<2 hex>/<62 hex>` entries of one volume. Only
        the two-level object layout is visited -- scratch files, the
        manifest and anything foreign are skipped without being stat'd. One
        bad directory or unavailable volume costs only its own objects.

        `strict` is for callers that act on "that's everything" (a transfer
        emptying a volume): a volume or folder that can't be read then raises
        VolumeNotResponding instead of quietly yielding less."""
        status = self.volume_status(name)
        if not status.reachable:
            if strict:
                raise VolumeNotResponding(name, status.reason)
            log.warning(
                "Skipping volume '%s' while listing objects: %s", name, status.reason
            )
            return
        root = self._resolve_path(self._cfg.volumes[name])
        try:
            top = list(os.scandir(root))
        except FileNotFoundError:
            if strict:
                raise VolumeNotResponding(name, f"{root} is missing") from None
            return
        except OSError as e:
            if strict:
                raise VolumeNotResponding(name, str(e)) from e
            log.warning("Skipping volume '%s' while listing objects: %s", name, e)
            return
        for shard in top:
            if not _HEX2_RE.match(shard.name):
                continue
            try:
                if not shard.is_dir(follow_symlinks=False):
                    continue
                with os.scandir(shard.path) as it:
                    for entry in it:
                        if not _HEX62_RE.match(entry.name):
                            continue
                        try:
                            if not entry.is_file(follow_symlinks=False):
                                continue
                            stat = entry.stat(follow_symlinks=False)
                        except OSError:
                            # Removed by a concurrent GC/delete between the
                            # listing and the stat -- skip, don't abort.
                            continue
                        yield StoredObjectInfo(
                            sha256=shard.name + entry.name,
                            volume=name,
                            size=stat.st_size,
                            mtime=stat.st_mtime,
                        )
            except OSError as e:
                if strict:
                    raise VolumeNotResponding(
                        name, f"can't read folder {shard.name}: {e}"
                    ) from e
                log.warning(
                    "Skipping shard '%s' of volume '%s': %s", shard.name, name, e
                )

    def sweep_stale_scratch(
        self, older_than_seconds: float, dry_run: bool = False
    ) -> int:
        """Count (and, unless dry_run, remove) put_stream() scratch files
        (`.tmp/*.part`) older than `older_than_seconds` -- left behind when
        an upload was interrupted (client disconnect, process kill) before
        the rename into place. These are invisible to list_objects(), so
        nothing else cleans them up. Age is judged conservatively: an
        in-progress upload keeps writing to its part file, which bumps its
        mtime, so anything past the threshold is one that stopped
        receiving bytes, not just a slow one."""
        cutoff = time.time() - older_than_seconds
        count = 0
        for vc in self._cfg.volumes.values():
            scratch_dir = self._resolve_path(vc) / _SCRATCH_DIRNAME
            if not scratch_dir.exists():
                continue
            for f in scratch_dir.glob("*.part"):
                try:
                    if f.stat().st_mtime < cutoff:
                        count += 1
                        if not dry_run:
                            f.unlink()
                except OSError:
                    continue
        return count

    def delete(self, sha256: str, volume: str | None = None) -> bool:
        """Remove a stored object. `volume` is an optional hint (e.g. from
        list_objects) to skip the full-volume scan; falls back to searching
        every volume if the hint misses. Returns False if not found."""
        path = None
        if volume is not None:
            vc = self._cfg.volumes.get(volume)
            if vc is not None:
                candidate = self._resolve_path(vc) / sha256[:2] / sha256[2:]
                if candidate.exists():
                    path = candidate
        if path is None:
            located = self._locate(sha256)
            if located is not None:
                volume, path = located
        if path is None:
            return False
        try:
            path.unlink()
        except FileNotFoundError:
            # Already gone -- e.g. a second GC run (or any other deleter)
            # removed the same object between our existence check above and
            # this unlink(). The end state either caller wanted is achieved
            # either way, so this is success, not a failure to propagate.
            pass
        if volume is not None:
            self._used_cache.pop(volume, None)
        self._unregister(sha256)
        return True

    @contextlib.contextmanager
    def gc_lock(self) -> Iterator[None]:
        """Advisory lock so at most one garbage-collection pass runs at a
        time. Without it, two overlapping runs race on delete()'s
        exists-then-unlink check and can independently mark-and-sweep
        against a store that's mutating out from under both of them.

        A plain marker file whose existence is the lock, rather than
        fcntl/msvcrt advisory locking, so this works the same on every
        platform civex runs on. Raises GCAlreadyRunningError if another
        (non-stale) run already holds it.
        """
        lock_path = self._root / "_civex" / _GC_LOCK_FILENAME
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        if self._transfer_lock_is_live():
            raise GCAlreadyRunningError(
                "A storage transfer is running. Garbage collection waits until "
                "it has finished, so the two never work on the same files."
            )

        def _acquire() -> None:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, str(os.getpid()).encode())
            finally:
                os.close(fd)

        try:
            _acquire()
        except FileExistsError:
            if self._gc_lock_is_live():
                raise GCAlreadyRunningError(
                    "A garbage-collection pass is already running against "
                    "this object store. Wait for it to finish and retry."
                )
            log.warning(
                "Reclaiming a GC lock whose process has gone or that is older "
                "than %ds -- assuming the process that held it crashed.",
                _GC_LOCK_STALE_SECONDS,
            )
            lock_path.unlink(missing_ok=True)
            _acquire()

        try:
            yield
        finally:
            lock_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Transfers: the primitives the transfer engine is built from
    # ------------------------------------------------------------------
    #
    # See civex.services.transfer_engine for the order they are used in, and why
    # that order loses nothing if it is interrupted anywhere.

    def iter_volume_objects(self, name: str) -> Iterator[StoredObjectInfo]:
        """Every object physically on one volume, lazily. Strict: a volume (or a
        folder in it) that can't be read raises VolumeNotResponding rather than
        looking emptier than it is."""
        return self._walk_volume(name, strict=True)

    def volume_path(self, name: str) -> Path:
        """Where a volume's folder is on disk (a relative path resolved against
        the project root)."""
        return self._resolve_path(self._cfg.volumes[name])

    def can_accept(self, volume: str, size: int) -> tuple[bool, str]:
        """Whether `volume` can take `size` more bytes right now: online and
        writable, within its allocation, with disk headroom. (The same gate a
        new upload passes.)"""
        return self._can_write(volume, size)

    def object_size(self, sha256: str, volume: str) -> int:
        """Size of the object on `volume`, from the disk."""
        path = self._object_path(sha256, volume)
        try:
            return self._stat(volume, path).st_size
        except FileNotFoundError:
            raise ItemFailed(f"it is no longer on '{volume}'") from None
        except OSError as e:
            raise ItemFailed(
                f"it can't be read on '{volume}': {e}", retryable=True
            ) from e

    def _stat(self, volume: str, path: Path) -> os.stat_result:
        vc = self._cfg.volumes[volume]
        if self._inside_project(vc):
            return os.stat(path)
        try:
            return fs_locations.guarded(f"{path}#stat", os.stat, path)
        except fs_locations.Unresponsive as e:
            raise VolumeNotResponding(volume, str(e)) from None

    def transfer_object(
        self,
        sha256: str,
        source: str,
        target: str,
        *,
        verify: str = "copy",
        on_chunk: Callable[[int], None] | None = None,
    ) -> CopyResult:
        """Copy one object from `source` to `target` and leave it in place there,
        checked. The original is NOT touched: removing it is a separate step the
        caller takes only once the catalog says the object lives on `target`.

        The copy goes to a scratch file on the target, is hashed as it is
        written (and must equal `sha256`), is read back and hashed again when
        `verify` is "full", and is then renamed into place -- atomic, since the
        scratch file is on the same drive, whatever kind of drive that is. If
        the object is already complete on the target (an earlier run got that
        far) there is nothing to copy, and the result says so (`reused`).

        `on_chunk(n)` is told of each chunk and may raise TransferStopped to
        abandon the copy (its scratch file is discarded). Raises ItemFailed,
        TargetFull or VolumeNotResponding as appropriate."""
        job = _CopyJob()
        external = not (
            self._inside_project(self._cfg.volumes[source])
            and self._inside_project(self._cfg.volumes[target])
        )
        if not external:
            self._copy_classified(sha256, source, target, verify, job, on_chunk)
            return CopyResult(job.size, job.reused)

        # A drive outside the project may be a network share that stops
        # answering in the middle of a write, and a blocked write can't be
        # interrupted from outside. So the copy runs on a helper thread and this
        # one watches it: it can stop it (the helper checks between chunks),
        # and it gives up on it if no bytes move for STALL_SECONDS.
        worker = threading.Thread(
            target=self._copy_in_thread,
            args=(sha256, source, target, verify, job),
            daemon=True,
            name="civex-transfer-copy",
        )
        worker.start()
        reported = 0
        try:
            while worker.is_alive():
                worker.join(0.2)
                if on_chunk is not None and job.bytes > reported:
                    delta, reported = job.bytes - reported, job.bytes
                    on_chunk(delta)
                if time.monotonic() - job.last_progress > job.stall_limit():
                    job.abort.set()
                    raise self._stalled(source, target)
        except TransferStopped:
            job.abort.set()
            worker.join(2.0)
            raise
        if job.error is not None:
            raise job.error
        if on_chunk is not None and job.bytes > reported:
            try:
                on_chunk(job.bytes - reported)
            except TransferStopped:
                # The copy finished before the stop was noticed. Keep it (it is
                # complete and checked); the caller sees the stop request before
                # it starts the next file.
                pass
        return CopyResult(job.size, job.reused)

    def _copy_in_thread(
        self, sha256: str, source: str, target: str, verify: str, job: _CopyJob
    ) -> None:
        try:
            self._copy_classified(sha256, source, target, verify, job, None)
        except BaseException as e:  # noqa: BLE001 - handed to the thread that waits
            job.error = e

    def _stalled(self, source: str, target: str) -> VolumeNotResponding:
        for name in (source, target):
            if not self._inside_project(self._cfg.volumes[name]):
                status = self.volume_status(name)
                if not status.reachable:
                    return VolumeNotResponding(name, status.reason)
        name = target if not self._inside_project(self._cfg.volumes[target]) else source
        return VolumeNotResponding(name, f"no data moved for {STALL_SECONDS:g} seconds")

    def _copy_classified(
        self,
        sha256: str,
        source: str,
        target: str,
        verify: str,
        job: _CopyJob,
        on_chunk: Callable[[int], None] | None,
    ) -> None:
        """`_copy_blocking`, with what goes wrong named for the engine: a full
        target pauses the transfer, a quiet volume pauses it until it answers,
        and anything else is that one file's problem."""
        try:
            self._copy_blocking(sha256, source, target, verify, job, on_chunk)
        except VolumeUnavailableError as e:
            raise VolumeNotResponding(target, str(e)) from e
        except OSError as e:
            if e.errno == errno.ENOSPC:
                raise TargetFull(f"'{target}' has no space left") from e
            for name in (source, target):
                if not self.volume_status(name).reachable:
                    raise VolumeNotResponding(name, str(e)) from e
            if (
                isinstance(e, FileNotFoundError)
                and not self._object_path(sha256, source).exists()
            ):
                raise ItemFailed(f"it is no longer on '{source}'") from e
            raise ItemFailed(f"input/output error: {e}", retryable=True) from e

    def _copy_blocking(
        self,
        sha256: str,
        source: str,
        target: str,
        verify: str,
        job: _CopyJob,
        on_chunk: Callable[[int], None] | None,
    ) -> None:
        src = self._object_path(sha256, source)
        dst = self._object_path(sha256, target)
        src_stat = src.stat()
        job.size = src_stat.st_size
        job.touch()
        if dst.exists() and dst.stat().st_size == src_stat.st_size:
            # An earlier run copied it and stopped before finishing the move.
            if verify != "full" or _hash_file(dst) == sha256:
                job.reused = True
                return
        scratch = self._scratch_path(target)
        try:
            hasher = hashlib.sha256()
            with src.open("rb") as reader, scratch.open("wb") as writer:
                while chunk := reader.read(_COPY_CHUNK):
                    if job.abort.is_set():
                        raise TransferStopped()
                    hasher.update(chunk)
                    writer.write(chunk)
                    job.bytes += len(chunk)
                    job.touch()
                    if on_chunk is not None:
                        on_chunk(len(chunk))
                writer.flush()
                job.syncing = True
                try:
                    os.fsync(writer.fileno())
                finally:
                    job.syncing = False
                    job.touch()
            if job.bytes != src_stat.st_size:
                raise ItemFailed("it changed while it was being copied", retryable=True)
            if hasher.hexdigest() != sha256:
                raise ItemFailed(
                    f"the copy on '{source}' doesn't match its hash: the file is "
                    "corrupt or has been altered",
                    retryable=True,
                )
            if verify == "full" and _hash_file(scratch, job) != sha256:
                raise ItemFailed(
                    f"the copy on '{target}' didn't read back correctly", retryable=True
                )
            if job.abort.is_set():
                raise TransferStopped()
            dst.parent.mkdir(exist_ok=True)
            try:  # keep its age, so a recent upload stays inside GC's grace period
                os.utime(scratch, ns=(src_stat.st_atime_ns, src_stat.st_mtime_ns))
            except OSError:
                pass
            os.replace(scratch, dst)
        except BaseException:
            scratch.unlink(missing_ok=True)
            raise

    def inventory_totals(self, volumes: Iterable[str]) -> dict[str, tuple[int, int]]:
        """(files, bytes) the catalog holds on each volume, for sizing a
        transfer before it starts. Close, not exact: the catalog can lag the
        disk, and a transfer counts what it actually finds."""
        wanted = list(volumes)
        totals = {v: (0, 0) for v in wanted}
        if self._session is None:
            for v in wanted:
                objs = list(self._walk_volume(v))
                totals[v] = (len(objs), sum(o.size for o in objs))
            return totals
        from sqlalchemy import func, select

        from civex.db.models import StoredObject

        rows = self._session.execute(
            select(
                StoredObject.volume,
                func.count(),
                func.coalesce(func.sum(StoredObject.size), 0),
            )
            .where(StoredObject.volume.in_(wanted))
            .group_by(StoredObject.volume)
        )
        for volume, files, size in rows:
            totals[volume] = (int(files), int(size))
        return totals

    def inventory_rows(self, shas: Iterable[str]) -> dict[str, tuple[str, int]]:
        """sha256 -> (volume, size) for the blobs the catalog knows."""
        wanted = list(dict.fromkeys(shas))
        found: dict[str, tuple[str, int]] = {}
        if self._session is None or not wanted:
            return found
        from sqlalchemy import select

        from civex.db.models import StoredObject

        for i in range(0, len(wanted), _LOCATE_CHUNK):
            rows = self._session.execute(
                select(
                    StoredObject.sha256, StoredObject.volume, StoredObject.size
                ).where(StoredObject.sha256.in_(wanted[i : i + _LOCATE_CHUNK]))
            )
            for sha, volume, size in rows:
                found[sha] = (volume, int(size))
        return found

    def room_on(self, volume: str) -> int | None:
        """How many more bytes `volume` would take: what its allocation leaves,
        or the disk's free space less the headroom Civex keeps -- whichever is
        smaller. None if that can't be read right now (the volume is offline)."""
        vc = self._cfg.volumes[volume]
        if not self.volume_status(volume).reachable:
            return None
        room: int | None = None
        if vc.allocated_gb is not None:
            room = max(0, int(vc.allocated_gb * 1024**3) - self._civex_used(volume))
        try:
            disk = self._disk_usage(vc, self._resolve_path(vc))
        except (OSError, fs_locations.Unresponsive):
            return None
        headroom = max(0, disk.free - int(self._cfg.full_below_gb * 1024**3))
        return headroom if room is None else min(room, headroom)

    def record_moves(self, moves: list[tuple[str, str, int]]) -> None:
        """Say in the catalog that each (sha256, volume, size) now lives on that
        volume. The caller commits, and only then removes the originals."""
        self._used_cache.clear()
        if self._session is not None and moves:
            self._upsert_inventory(moves)

    def remove_from_volume(self, sha256: str, volume: str) -> bool:
        """Remove the object from exactly that volume (never searching others,
        which `delete()` falls back to). False if it was already gone."""
        path = self._object_path(sha256, volume)
        self._used_cache.pop(volume, None)
        vc = self._cfg.volumes[volume]
        try:
            if self._inside_project(vc):
                path.unlink()
            else:
                fs_locations.guarded(f"{path}#unlink", path.unlink)
        except FileNotFoundError:
            return False
        except fs_locations.Unresponsive as e:
            raise OSError(f"volume '{volume}' isn't responding") from e
        return True

    def read_manifest_names(self, volume: str) -> dict[str, str]:
        """sha256 -> original filename, from the volume's manifest, so a moved
        file keeps its name in its new home's manifest. Empty if the manifest is
        missing or too large to be worth reading."""
        path = self._resolve_path(self._cfg.volumes[volume]) / "manifest.jsonl"
        names: dict[str, str] = {}
        try:
            if path.stat().st_size > _MANIFEST_READ_LIMIT:
                return names
            with path.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        names[entry["sha256"]] = entry["filename"]
                    except (ValueError, KeyError, TypeError):
                        continue
        except OSError:
            pass
        return names

    def append_manifest(
        self, volume: str, sha256: str, filename: str | None, size: int
    ) -> None:
        self._append_manifest_best_effort(volume, sha256, filename or "", size)

    # -- one transfer at a time, and never alongside GC -----------------------

    def _lock_is_live(self, filename: str) -> bool:
        path = self._root / "_civex" / filename
        try:
            return time.time() - path.stat().st_mtime < _GC_LOCK_STALE_SECONDS
        except OSError:
            return False

    def _lock_owner(self, filename: str) -> int | None:
        """The id of the process that took a lock, or None if it can't be read."""
        try:
            return int((self._root / "_civex" / filename).read_text().strip())
        except (OSError, ValueError):
            return None

    def _owner_alive(self, filename: str) -> bool:
        """A lock whose process has gone (the server restarted, the terminal was
        closed, the machine lost power) is free at once, not an hour later. One
        with no readable id falls back to how recently it was touched."""
        if not self._lock_is_live(filename):
            return False
        owner = self._lock_owner(filename)
        return True if owner is None else pid_alive(owner)

    def _transfer_lock_is_live(self) -> bool:
        """Whether a transfer is really holding its lock."""
        return self._owner_alive(_TRANSFER_LOCK_FILENAME)

    def _gc_lock_is_live(self) -> bool:
        """Whether a garbage-collection pass is really holding its lock."""
        return self._owner_alive(_GC_LOCK_FILENAME)

    @contextlib.contextmanager
    def transfer_lock(self) -> Iterator[None]:
        """Held for as long as a transfer is moving files. Refuses to start while
        another transfer or a garbage-collection pass holds its lock, and makes
        GC refuse in turn, so the two never work on the same files at once.
        `touch_transfer_lock` keeps it fresh; one not touched for an hour is
        taken to belong to a process that died."""
        if self._gc_lock_is_live():
            raise GCAlreadyRunningError(
                "A garbage-collection pass is running. Wait for it to finish, "
                "then start the transfer."
            )
        lock_path = self._root / "_civex" / _TRANSFER_LOCK_FILENAME
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        # O_EXCL, so two processes (the server's worker and a terminal) that
        # reach for the lock at the same moment can't both get it.
        for _ in range(2):
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._transfer_lock_is_live():
                    raise GCAlreadyRunningError(
                        "A storage transfer is already running."
                    ) from None
                lock_path.unlink(missing_ok=True)  # its process is gone
                continue
            try:
                os.write(fd, str(os.getpid()).encode())
            finally:
                os.close(fd)
            break
        else:
            raise GCAlreadyRunningError("A storage transfer is already running.")
        try:
            yield
        finally:
            lock_path.unlink(missing_ok=True)

    def transfer_lock_held(self) -> bool:
        """Whether a live process is holding the transfer lock right now."""
        return self._transfer_lock_is_live()

    def touch_transfer_lock(self) -> None:
        try:
            os.utime(self._root / "_civex" / _TRANSFER_LOCK_FILENAME)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Stats (for CLI / UI)
    # ------------------------------------------------------------------

    def _disk_usage(self, vc: VolumeConfig, path: Path) -> Any:
        """shutil.disk_usage, time-limited for a volume outside the project (a
        network mount can stop answering). Raises OSError, or
        fs_locations.Unresponsive on timeout."""
        if self._inside_project(vc):
            return shutil.disk_usage(path)
        return fs_locations.guarded(f"{path}#usage", shutil.disk_usage, path)

    def _stat_volume(
        self,
        name: str,
        vc: VolumeConfig,
        warn_pct: float,
        *,
        in_queue: bool,
        mounts: list[fs_locations.Mount] | None = None,
    ) -> dict:
        path = self._resolve_path(vc)
        status = self.volume_status(name)
        available = status.reachable
        disk_free = disk_total = None
        if available:
            try:
                du = self._disk_usage(vc, path)
                disk_free = du.free
                disk_total = du.total
            except (OSError, fs_locations.Unresponsive) as e:
                available = False
                status = VolumeStatus(VOLUME_OFFLINE, f"cannot read disk usage: {e}")

        civex_used = self._civex_used(name) if available else None
        allocated_bytes = (
            int(vc.allocated_gb * 1024**3) if vc.allocated_gb is not None else None
        )

        warning = False
        if available:
            if allocated_bytes and civex_used is not None and allocated_bytes > 0:
                if (allocated_bytes - civex_used) / allocated_bytes < warn_pct:
                    warning = True
            if disk_free is not None and disk_total and disk_total > 0:
                if disk_free / disk_total < warn_pct:
                    warning = True

        return {
            "name": name,
            "path": vc.path,
            "allocated_gb": vc.allocated_gb,
            "civex_used_bytes": civex_used,
            "disk_free_bytes": disk_free,
            "disk_total_bytes": disk_total,
            "available": available,
            "state": status.state,
            "reason": status.reason,
            "fix": status.fix,
            "warning": warning,
            "in_queue": in_queue,
            "network": fs_locations.is_network_path(
                fs_locations.normalise(str(path)), mounts
            ),
        }

    def volume_stats(self) -> list[dict]:
        warn_pct = self._cfg.warn_below_pct / 100.0
        mounts = fs_locations.all_mounts()  # read once for every volume
        results = []
        for name in self._cfg.volume_queue:
            vc = self._cfg.volumes.get(name)
            if vc is None:
                continue
            results.append(
                self._stat_volume(name, vc, warn_pct, in_queue=True, mounts=mounts)
            )
        # Include volumes defined but not in queue
        for name, vc in self._cfg.volumes.items():
            if name not in self._cfg.volume_queue:
                results.append(
                    self._stat_volume(name, vc, warn_pct, in_queue=False, mounts=mounts)
                )
        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_path(self, vc: VolumeConfig) -> Path:
        p = Path(vc.path)
        return p if p.is_absolute() else self._root / p

    def _object_path(self, sha256: str, volume: str) -> Path:
        vc = self._cfg.volumes[volume]
        return self._resolve_path(vc) / sha256[:2] / sha256[2:]

    def _append_manifest(
        self, volume: str, sha256: str, filename: str, size: int
    ) -> None:
        """Append one JSONL line recording this object's original filename.

        Only called on first write of a given hash (the idempotent-existing
        path in put() returns before reaching this), so each hash gets one
        line -- or, if two different uploads race to store the same content
        under different names, one line per name, which is useful rather
        than a bug.
        """
        vc = self._cfg.volumes[volume]
        manifest_path = self._resolve_path(vc) / "manifest.jsonl"
        line = json.dumps(
            {"sha256": sha256, "filename": filename, "size": size},
            ensure_ascii=False,
        )
        with manifest_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _append_manifest_best_effort(
        self, volume: str, sha256: str, filename: str, size: int
    ) -> None:
        """Same as _append_manifest(), but never raises: the manifest is
        display metadata only (see list_objects()'s docstring), so a failure
        writing it must not fail an upload whose bytes are already durably
        stored at their final, content-addressed path."""
        try:
            self._append_manifest(volume, sha256, filename, size)
        except OSError:
            log.warning(
                "Failed to append manifest entry for %s on volume '%s' -- "
                "the object is stored, but display metadata for it may be "
                "missing.",
                sha256,
                volume,
                exc_info=True,
            )

    def _locate(self, sha256: str) -> tuple[str, Path] | None:
        """(volume name, path) of the first volume holding this object --
        one pass over the volumes, rather than separate find/volume-of scans
        (each of which is a stat per volume, i.e. a network round trip on
        NFS-style mounts)."""
        for name, vc in self._cfg.volumes.items():
            # One dead network mount must not stall every read: a volume
            # outside the project that isn't answering is skipped.
            if not self._inside_project(vc) and self._probe_volume(name)[0]:
                continue
            p = self._resolve_path(vc) / sha256[:2] / sha256[2:]
            if p.exists():
                return name, p
        return None

    def _find_object(self, sha256: str) -> Path | None:
        located = self._locate(sha256)
        return located[1] if located else None

    def _volume_of(self, sha256: str) -> str | None:
        located = self._locate(sha256)
        return located[0] if located else None

    @staticmethod
    def _touch(path: Path) -> None:
        """Bump an object's mtime when a new upload dedupes onto it. GC's
        grace period is judged by mtime, so without this an old, otherwise
        unreferenced blob that a user just re-uploaded (but whose record
        isn't committed yet) could be collected out from under them."""
        try:
            os.utime(path)
        except OSError:
            pass

    # -- usage accounting -------------------------------------------------

    def _register(self, volume: str, sha256: str, size: int) -> None:
        """Record a newly stored blob in the inventory (idempotent)."""
        self._used_cache.pop(volume, None)
        if self._session is None:
            return
        self._upsert_inventory([(sha256, volume, size)])

    def _unregister(self, sha256: str) -> None:
        if self._session is None:
            return
        from sqlalchemy import delete

        from civex.db.models import StoredObject

        self._session.execute(delete(StoredObject).where(StoredObject.sha256 == sha256))

    def _upsert_inventory(self, rows: list[tuple[str, str, int]]) -> None:
        assert self._session is not None
        from civex.db.models import StoredObject

        from sqlalchemy import Table
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        insert = (
            pg_insert
            if self._session.get_bind().dialect.name == "postgresql"
            else sqlite_insert
        )
        table = cast(Table, StoredObject.__table__)
        now = datetime.now(timezone.utc)
        stmt = insert(table).values(
            [
                {"sha256": sha, "volume": vol, "size": size, "created_at": now}
                for sha, vol, size in rows
            ]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["sha256"],
            set_={"volume": stmt.excluded.volume, "size": stmt.excluded.size},
        )
        self._session.execute(stmt)

    def reconcile_inventory(self) -> dict[str, int]:
        """Bring the `stored_objects` table back in line with disk: add rows
        for blobs present but unrecorded, drop rows whose blob is gone.
        Disk is authoritative. Streams in fixed-size batches, so memory is
        O(batch), not O(store). Returns {"added_or_updated", "removed"}.
        GC runs this, so any drift (a rolled-back upload, a crash between
        the rename and the commit, a file deleted by hand) is repaired by
        the next pass instead of accumulating."""
        if self._session is None:
            return {"added_or_updated": 0, "removed": 0}
        totals = {"added_or_updated": 0, "removed": 0}
        for name in self._cfg.volumes:
            r = self._reconcile_volume(name)
            totals["added_or_updated"] += r[0]
            totals["removed"] += r[1]
        return totals

    def _reconcile_volume(self, name: str) -> tuple[int, int]:
        assert self._session is not None
        from sqlalchemy import delete, select

        from civex.db.models import StoredObject

        # An unavailable volume says nothing about what is on it: dropping
        # its rows because "no blob was found" would erase the accounting
        # for every object on a drive that is simply unplugged.
        status = self.volume_status(name)
        if not status.reachable:
            log.warning(
                "Skipping inventory reconcile of volume '%s': %s", name, status.reason
            )
            return 0, 0

        upserted = 0
        batch: list[tuple[str, str, int]] = []
        for obj in self._walk_volume(name):
            batch.append((obj.sha256, name, obj.size))
            if len(batch) >= _RECONCILE_BATCH:
                self._upsert_inventory(batch)
                upserted += len(batch)
                batch = []
        if batch:
            self._upsert_inventory(batch)
            upserted += len(batch)

        # A volume with no verified identity, no objects, and no sign this
        # store ever wrote to it is an empty directory -- most likely a mount
        # point with nothing mounted -- so it can't be taken as proof that the
        # inventory rows are stale. (A volume whose identity is verified, or
        # that was written to and then emptied, is reconciled normally.)
        if (
            upserted == 0
            and status.volume_id is None
            and not self._was_initialised(name)
            and self._session.execute(
                select(StoredObject.sha256).where(StoredObject.volume == name).limit(1)
            ).first()
        ):
            log.warning(
                "Volume '%s' is available but was never initialised and holds "
                "no objects, while the inventory lists some; leaving its rows "
                "in place.",
                name,
            )
            self._used_cache.pop(name, None)
            return upserted, 0

        removed = 0
        root = self._resolve_path(self._cfg.volumes[name])
        last = ""
        while True:
            shas = [
                sha
                for (sha,) in self._session.execute(
                    select(StoredObject.sha256)
                    .where(StoredObject.volume == name, StoredObject.sha256 > last)
                    .order_by(StoredObject.sha256)
                    .limit(_RECONCILE_BATCH)
                )
            ]
            if not shas:
                break
            last = shas[-1]
            gone = [s for s in shas if not (root / s[:2] / s[2:]).exists()]
            if gone:
                self._session.execute(
                    delete(StoredObject).where(StoredObject.sha256.in_(gone))
                )
                removed += len(gone)
        self._used_cache.pop(name, None)
        return upserted, removed

    def _civex_used(self, volume: str) -> int:
        vc = self._cfg.volumes.get(volume)
        if vc is None:
            return 0
        if self._session is not None:
            return self._inventory_used(volume)
        if volume in self._used_cache:
            return self._used_cache[volume]
        total = sum(o.size for o in self._walk_volume(volume))
        self._used_cache[volume] = total
        return total

    def _inventory_used(self, volume: str) -> int:
        """SUM(size) over the volume's inventory rows. A volume with no rows
        at all is scanned once to bootstrap the table -- covering an install
        upgraded from before the inventory existed, where the migration
        can't know the volume paths."""
        assert self._session is not None
        from sqlalchemy import func, select

        from civex.db.models import StoredObject

        if volume not in self._bootstrapped:
            has_rows = self._session.execute(
                select(StoredObject.sha256)
                .where(StoredObject.volume == volume)
                .limit(1)
            ).first()
            if has_rows is None:
                self._reconcile_volume(volume)
            self._bootstrapped.add(volume)
        total = self._session.execute(
            select(func.coalesce(func.sum(StoredObject.size), 0)).where(
                StoredObject.volume == volume
            )
        ).scalar_one()
        return int(total)

    # -- volume status: the single place that decides ------------------------
    #
    # Every code path that asks "can I use this volume?" -- writes, stats,
    # directory walks, inventory reconcile -- goes through volume_status().
    # Nothing else stats a volume root or reads its marker to decide that, so
    # changing what "usable" means is a change to this one method.
    #
    # A volume's identity is a UUID held in the `volumes` table and repeated in
    # a `.civex-volume` marker file in its root. It is *enforced* only for
    # volumes outside the project: a drive can only be unplugged, or swapped
    # for another, if it lives outside the project, and enforcing a marker on
    # the default `_civex/objects` would let a deleted dotfile lock a
    # single-volume install out of its own uploads. Without a database
    # session (standalone use) there is no identity to check at all.

    def _probe_volume(self, name: str) -> tuple[VolumeStatus | None, str | None]:
        """(an offline status if the volume's root can't be reached, else None;
        the identity marker found there). A volume outside the project may be a
        network mount that has stopped answering, so it is probed under a time
        limit and reported offline rather than freezing the caller."""
        vc = self._cfg.volumes.get(name)
        if vc is None:
            return (
                VolumeStatus(
                    VOLUME_OFFLINE,
                    "volume not configured",
                    "Add it with `civex store add`.",
                ),
                None,
            )
        root = self._resolve_path(vc)
        try:
            if self._inside_project(vc):
                problem, marker = _probe_root(root)
            else:
                problem, marker = fs_locations.guarded(str(root), _probe_root, root)
        except fs_locations.Unresponsive as e:
            return (
                VolumeStatus(
                    VOLUME_OFFLINE,
                    f"not responding: {root} ({e})",
                    "Check the network connection or the drive, then try again.",
                ),
                None,
            )
        if problem is not None:
            return (
                VolumeStatus(
                    VOLUME_OFFLINE,
                    problem,
                    "Plug the drive in, or change the volume's path.",
                ),
                None,
            )
        return None, marker

    def _path_status(self, name: str) -> VolumeStatus | None:
        """An offline status if the volume's root can't be reached, else None."""
        return self._probe_volume(name)[0]

    def volume_status(self, name: str) -> VolumeStatus:
        offline, marker = self._probe_volume(name)
        if offline is not None:
            return offline
        vc = self._cfg.volumes[name]
        root = self._resolve_path(vc)

        if not self._inside_project(vc):
            if vc.id is None:
                owner = next(
                    (
                        n
                        for n, other in self._cfg.volumes.items()
                        if n != name and other.id and other.id == marker
                    ),
                    None,
                )
                if owner is not None:
                    return VolumeStatus(
                        VOLUME_WRONG_DRIVE,
                        f"{root} is the drive of volume '{owner}', not '{name}'",
                        f"Plug in the drive for '{name}', or change the volume's path.",
                    )
            elif marker != vc.id:
                seen = (
                    f"the marker of a different volume ({marker[:8]}...)"
                    if marker
                    else "no volume marker"
                )
                return VolumeStatus(
                    VOLUME_WRONG_DRIVE,
                    f"expected volume '{name}' ({vc.id[:8]}...) at {root}, found {seen}",
                    "Plug in the right drive. If this is the right drive, adopt it "
                    "to give it this volume's identity.",
                )

        verified = vc.id if vc.id and marker == vc.id else None
        if vc.state == "readonly":
            return VolumeStatus(VOLUME_READONLY, "marked read-only", volume_id=verified)
        if vc.state == "retired":
            return VolumeStatus(VOLUME_RETIRED, "retired", volume_id=verified)
        return VolumeStatus(VOLUME_ONLINE, volume_id=verified)

    def volume_available(self, name: str) -> bool:
        return self.volume_status(name).reachable

    # -- volume identity ----------------------------------------------------
    #
    # A volume's id lives in its VolumeConfig (config.toml, next to its path)
    # and is repeated in the marker file. These methods change the in-memory
    # config and the marker; the caller (StoreService) persists the config.

    def register_volume(self, name: str) -> VolumeStatus:
        """Give `name` an identity if it has none. Leaves a drive that
        belongs to another volume alone."""
        status = self.volume_status(name)
        if self._cfg.volumes[name].id is None and status.state == VOLUME_ONLINE:
            self._assign_identity(name)
            return self.volume_status(name)
        return status

    def adopt_volume(self, name: str) -> VolumeStatus:
        """Declare that the drive at this volume's path *is* the volume,
        whatever its marker says: rewrite the marker with the volume's id (or
        give the volume one, if it has none yet)."""
        offline = self._path_status(name)
        if offline is not None:
            raise VolumeUnavailableError(
                f"Cannot adopt '{name}': {offline.reason}. {offline.fix}"
            )
        self._assign_identity(name)
        return self.volume_status(name)

    def _assign_identity(self, name: str) -> None:
        """Make the marker in `name`'s root carry the volume's id, first
        choosing one if it has none: the id already in the marker when no
        other configured volume has it (a drive from another project, a lost
        config), otherwise a new one."""
        vc = self._cfg.volumes[name]
        root = self._resolve_path(vc)
        vid = vc.id
        if vid is None:
            marker = _read_marker(root)
            taken = {v.id for n, v in self._cfg.volumes.items() if n != name and v.id}
            vid = marker if marker and marker not in taken else str(uuid.uuid4())
        if not self._write_marker(root, vid):
            raise VolumeUnavailableError(f"Cannot write a volume marker in {root}")
        vc.id = vid

    @staticmethod
    def _write_marker(root: Path, vid: str) -> bool:
        try:
            tmp = root / f"{_MARKER_FILENAME}.tmp"
            tmp.write_text(vid + "\n", encoding="utf-8")
            os.replace(tmp, root / _MARKER_FILENAME)
        except OSError:
            log.warning("Cannot write the volume marker in %s", root, exc_info=True)
            return False
        return True

    # -- on-demand creation -------------------------------------------------

    def _inside_project(self, vc: VolumeConfig) -> bool:
        """True for a volume whose path is relative and stays within the
        project root (the default `_civex/objects`). Only those may be
        created on demand: an absolute path can sit under a mount point that
        is currently empty, and creating it would silently write to the
        parent filesystem instead of the drive that belongs there."""
        if Path(vc.path).is_absolute():
            return False
        root = Path(os.path.normpath(self._root))
        return Path(os.path.normpath(root / vc.path)).is_relative_to(root)

    def _ensure_volume(self, name: str) -> VolumeStatus:
        """volume_status() for a volume about to be written: first creates
        the root if (and only if) the volume lives inside the project -- the
        one place a root is ever created implicitly. A volume's identity is
        never assigned here: that changes config.toml, which an upload must
        not do (`store add` and `store adopt` do it)."""
        status = self.volume_status(name)
        vc = self._cfg.volumes.get(name)
        if vc is None:
            return status
        if not status.reachable and self._inside_project(vc):
            try:
                self._resolve_path(vc).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return VolumeStatus(VOLUME_OFFLINE, f"cannot create {vc.path}: {e}")
            status = self.volume_status(name)
        return status

    def _was_initialised(self, name: str) -> bool:
        """Whether this volume root has ever held objects written by this
        store. Every write appends to <root>/manifest.jsonl, which nothing
        deletes, so its absence means "an empty directory", not "a volume
        someone emptied". Used for a volume with no identity yet, where
        reconcile can't otherwise tell an unmounted mount point from an
        emptied drive."""
        vc = self._cfg.volumes.get(name)
        return vc is not None and (self._resolve_path(vc) / "manifest.jsonl").is_file()

    def _can_write(self, volume: str, incoming_size: int) -> tuple[bool, str]:
        vc = self._cfg.volumes.get(volume)
        if vc is None:
            return False, "volume not configured"

        status = self._ensure_volume(volume)
        if not status.writable:
            return False, f"volume {status.state.replace('_', ' ')}: {status.reason}"
        path = self._resolve_path(vc)

        if vc.allocated_gb is not None:
            allocated = int(vc.allocated_gb * 1024**3)
            used = self._civex_used(volume)
            if used + incoming_size > allocated:
                remaining = max(0, allocated - used)
                return False, (
                    f"allocation limit reached "
                    f"({remaining / 1_048_576:.0f} MB of {vc.allocated_gb:.1f} GB remaining)"
                )

        try:
            disk = self._disk_usage(vc, path)
        except (OSError, fs_locations.Unresponsive) as e:
            return False, f"cannot check disk space: {e}"
        full_bytes = int(self._cfg.full_below_gb * 1024**3)
        if disk.free < full_bytes + incoming_size:
            return False, (
                f"disk too full ({disk.free / 1_048_576:.0f} MB free, "
                f"need {self._cfg.full_below_gb:.1f} GB headroom)"
            )

        return True, ""


# Backward-compat alias so existing imports don't break immediately.
LocalFileObjectStore = VolumeAwareFileObjectStore
