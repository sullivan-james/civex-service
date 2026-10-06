"""The engine that moves stored files between volumes.

It has no idea about HTTP, threads or the database record of a transfer; it is
handed a store, a reference repository, a spec and a few hooks, and returns how
it ended. (The same shape as `civex.db.move`, which does this for databases.)

The promise, in the order things happen to each file:

  1. copy it to a scratch file on the destination, hashing as it goes -- the
     hash must match the file's recorded hash, which catches a corrupt source;
  2. (optionally) read the copy back and hash that too;
  3. rename it into its place on the destination -- atomic, on the same drive;
  4. commit the catalog so it says the file lives on the destination;
  5. only then remove the file from the source.

Stopping between any two of those steps loses nothing: before step 3 the source
is untouched and a stray scratch file is discarded; between 3 and 5 the file is
on both drives, and the next run sees that and finishes the job. So pausing,
cancelling, a crash and a power cut are all safe, and resuming is just running
again: the work is found by looking at what is physically on the source, so
whatever is already moved is simply not there to be found.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Iterator

from civex.domain.transfers import (
    KIND_CONSOLIDATE,
    CopyResult,
    KIND_DRAIN,
    KIND_FILES,
    MAX_RECORDED_FAILURES,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PAUSED,
    ItemFailed,
    TargetFull,
    TransferFailure,
    TransferProgress,
    TransferSpec,
    TransferStopped,
    VolumeNotResponding,
)

if TYPE_CHECKING:
    from civex.repositories.protocols import FileObjectStore, FileReferenceRepository

log = logging.getLogger(__name__)

# A batch of copied files is committed (and their originals removed) this often.
# Short, so what is counted as done is always what is safely done.
FLUSH_FILES = 50
FLUSH_SECONDS = 1.0
LARGE_FILE = 8 * 1024 * 1024  # a file this big is committed on its own
RETRIES = 2  # extra attempts at a file whose copy failed in a way that may pass
RETRY_DELAY = 0.5
RATE_WINDOW = 15.0  # seconds of history the speed is averaged over
PAGE = 1000  # references read per query when consolidating

ProgressFn = Callable[[TransferProgress], None]


class TransferControl:
    """How a caller asks a running transfer to stop. Checked between chunks, so
    a pause takes effect within a moment even in the middle of a huge file
    (whose half-made copy is simply discarded and redone on resume)."""

    def __init__(self) -> None:
        self._pause = threading.Event()
        self._cancel = threading.Event()

    def pause(self) -> None:
        self._pause.set()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def stop_requested(self) -> bool:
        return self._pause.is_set() or self._cancel.is_set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()


@dataclass
class Outcome:
    """How a run of the engine ended."""

    status: str  # completed | paused | cancelled | failed
    progress: TransferProgress
    failures: list[TransferFailure]
    failures_total: int
    pause_reason: str | None = None
    auto_resume: bool = False  # paused only because a volume went quiet
    error: str | None = None


@dataclass
class Seed:
    """Where an earlier run got to, so a resumed transfer's totals carry on
    instead of starting again from nothing."""

    progress: TransferProgress = field(default_factory=TransferProgress)
    failures: list[TransferFailure] = field(default_factory=list)
    failures_total: int = 0


@dataclass
class _Item:
    sha256: str
    source: str
    size: int | None = None  # None until it has been looked at


@dataclass
class _Moved:
    """A file copied to its destination but not yet committed."""

    sha256: str
    source: str
    target: str
    size: int
    name: str | None = None  # the file's original name, for the target's manifest
    # False for a file whose move an earlier run already committed and counted,
    # leaving only its original to be removed: cleaning that up isn't another move.
    counted: bool = True


class _Run:
    """The state of one run: counters, the pending batch, the speed window."""

    def __init__(
        self,
        store: FileObjectStore,
        spec: TransferSpec,
        control: TransferControl,
        progress_hook: ProgressFn,
        commit: Callable[[], None],
        seed: Seed,
        clock: Callable[[], float],
    ) -> None:
        self.store = store
        self.spec = spec
        self.control = control
        self.hook = progress_hook
        self.commit = commit
        self.clock = clock
        self.p = TransferProgress(**vars(seed.progress))
        self.failures = list(seed.failures)
        self.failures_total = max(seed.failures_total, len(self.failures))
        self.batch: list[_Moved] = []
        self.batch_bytes = 0
        self.pending_files = 0  # counted files in the batch, not yet in files_done
        self.last_flush = clock()
        self.last_emit = 0.0
        self.window: deque[tuple[float, int]] = deque()
        # Bytes written to targets in the current batch, per target, so room is
        # judged against what is already promised, not just what is committed.
        self.pending: dict[str, int] = {}
        # Original filenames per source volume, read from its manifest once, so
        # a moved file keeps its name in the target's manifest.
        self.names: dict[str, dict[str, str]] = {}

    def name_of(self, source: str, sha256: str) -> str | None:
        if source not in self.names:
            self.names[source] = self.store.read_manifest_names(source)
        return self.names[source].get(sha256)

    # -- progress ------------------------------------------------------------

    def emit(self, force: bool = False) -> None:
        now = self.clock()
        if not force and now - self.last_emit < 0.5:
            return
        self.last_emit = now
        self.store.touch_transfer_lock()  # proof of life, so the lock isn't taken for stale
        done = self.p.bytes_done + self.p.current_bytes
        self.window.append((now, done))
        while len(self.window) > 2 and now - self.window[0][0] > RATE_WINDOW:
            self.window.popleft()
        t0, b0 = self.window[0]
        rate = (done - b0) / (now - t0) if now - t0 > 0 else 0.0
        self.p.rate_bytes_per_second = max(rate, 0.0)
        remaining = max(self.p.bytes_total - done, 0)
        self.p.eta_seconds = remaining / rate if rate > 0 and remaining else None
        self.hook(TransferProgress(**vars(self.p)))

    def check_stop(self) -> None:
        if self.control.stop_requested:
            raise TransferStopped()

    # -- failures ------------------------------------------------------------

    def fail(self, item: _Item, reason: str) -> None:
        self.p.files_failed += 1
        self.failures_total += 1
        if len(self.failures) < MAX_RECORDED_FAILURES:
            self.failures.append(TransferFailure(item.sha256, item.source, reason))
        log.warning(
            "Transfer: could not move %s from %s: %s", item.sha256, item.source, reason
        )

    # -- committing ----------------------------------------------------------

    def flush(self) -> None:
        """Commit the files copied so far, then (and only then) remove their
        originals. Counted as done only now, so the persisted numbers never
        include a file whose move could still be undone by a crash."""
        if not self.batch:
            self.last_flush = self.clock()
            return
        moved, self.batch = self.batch, []
        self.batch_bytes = 0
        self.pending_files = 0
        self.pending.clear()
        self.store.record_moves([(m.sha256, m.target, m.size) for m in moved])
        self.commit()
        for m in moved:
            try:
                self.store.remove_from_volume(m.sha256, m.source)
            except OSError as exc:  # it is safely on the target; a stray copy remains
                log.warning(
                    "Transfer: %s is on %s but its original on %s couldn't be removed: %s",
                    m.sha256,
                    m.target,
                    m.source,
                    exc,
                )
            self.store.append_manifest(m.target, m.sha256, m.name, m.size)
            if m.counted:
                self.p.files_done += 1
                self.p.bytes_done += m.size
        self.last_flush = self.clock()
        self.emit(force=True)

    def maybe_flush(self) -> None:
        if (
            len(self.batch) >= FLUSH_FILES
            or self.clock() - self.last_flush >= FLUSH_SECONDS
        ):
            self.flush()


# -- choosing what to move ---------------------------------------------------


def _items(
    store: FileObjectStore,
    refs: FileReferenceRepository,
    spec: TransferSpec,
    placements: dict[str, str],
    run: _Run,
) -> Iterator[_Item]:
    if spec.kind == KIND_DRAIN:
        for source in spec.sources:
            for obj in store.iter_volume_objects(source):
                yield _Item(obj.sha256, source, obj.size)
            # A drive that went quiet part-way through the listing would look
            # exactly like one that has been emptied. It hasn't been.
            status = store.volume_status(source)
            if not status.reachable:
                raise VolumeNotResponding(source, status.reason)
    elif spec.kind == KIND_CONSOLIDATE:
        yield from _consolidation_items(store, refs, spec, placements, run)
    elif spec.kind == KIND_FILES:
        yield from _file_items(store, spec, run)
    else:
        raise ValueError(f"Unknown transfer kind '{spec.kind}'")


def _file_items(
    store: FileObjectStore, spec: TransferSpec, run: _Run
) -> Iterator[_Item]:
    """The named files that aren't on a target yet. Work is re-found from where
    each file is now, so a resumed transfer carries on with what is left."""
    for start in range(0, len(spec.shas), PAGE):
        shas = spec.shas[start : start + PAGE]
        where = store.locate_volumes(shas)
        for sha in shas:
            volume = where.get(sha)
            if volume is None:
                continue  # not stored on any volume we know of: nothing to move
            if volume in spec.targets:
                run.p.files_skipped += 1
                continue
            yield _Item(sha, volume)


def _consolidation_items(
    store: FileObjectStore,
    refs: FileReferenceRepository,
    spec: TransferSpec,
    placements: dict[str, str],
    run: _Run,
) -> Iterator[_Item]:
    selected = set(spec.collection_ids)
    after: str | None = None
    while True:
        shas = refs.shas_for_collections(spec.collection_ids, after, PAGE)
        if not shas:
            return
        after = shas[-1]
        where = store.locate_volumes(shas)
        users = refs.collections_using(shas) if not spec.include_shared else {}
        for sha in shas:
            volume = where.get(sha)
            if volume is None:
                continue  # not stored on any volume we know of: nothing to move
            if volume in spec.targets:
                run.p.files_skipped += 1
                continue
            # A file other collections use too stays put when one of them keeps
            # its files somewhere other than where this one is going: moving it
            # would only split that collection instead.
            others = users.get(sha, set()) - selected
            if any(placements.get(c) not in (None, *spec.targets) for c in others):
                run.p.files_skipped += 1
                continue
            yield _Item(sha, volume)


def _choose_target(store: FileObjectStore, run: _Run, size: int) -> str:
    """The first target that can take `size` more bytes, as the write queue
    would. Raises VolumeNotResponding when the only thing in the way is a volume
    that has gone quiet (which may well come back), TargetFull otherwise."""
    quiet: str | None = None
    reasons: list[str] = []
    for name in run.spec.targets:
        ok, reason = store.can_accept(name, size + run.pending.get(name, 0))
        if ok:
            return name
        reasons.append(f"{name}: {reason}")
        status = store.volume_status(name)
        if not status.reachable and quiet is None:
            quiet = name
    if quiet is not None:
        raise VolumeNotResponding(quiet, "; ".join(reasons))
    raise TargetFull("No target has room for the next file. " + "; ".join(reasons))


# -- the run -----------------------------------------------------------------


def run_transfer(
    store: FileObjectStore,
    refs: FileReferenceRepository,
    spec: TransferSpec,
    *,
    placements: dict[str, str] | None = None,
    progress: ProgressFn,
    commit: Callable[[], None],
    control: TransferControl | None = None,
    seed: Seed | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Outcome:
    """Move the files `spec` describes, as far as it can. `commit` is called
    after each batch to make the catalog changes durable (it is what makes a file
    safe to remove from its source). Never raises for anything that happens to a
    file or a volume: the way it ended is the returned Outcome."""
    control = control or TransferControl()
    run = _Run(store, spec, control, progress, commit, seed or Seed(), clock)
    status = STATUS_COMPLETED
    reason: str | None = None
    auto_resume = False
    error: str | None = None
    try:
        run.emit(force=True)
        for item in _items(store, refs, spec, placements or {}, run):
            run.check_stop()
            _move(store, run, item)
            run.maybe_flush()
            run.emit()
    except TransferStopped:
        status = STATUS_CANCELLED if control.cancelled else STATUS_PAUSED
        reason = None if control.cancelled else "Paused."
    except VolumeNotResponding as exc:
        status, reason, auto_resume = STATUS_PAUSED, str(exc), True
    except TargetFull as exc:
        status, reason = STATUS_PAUSED, str(exc)
    except Exception as exc:  # noqa: BLE001 - reported, not raised: see docstring
        log.exception("Transfer stopped by an unexpected error")
        status, error = (
            STATUS_FAILED,
            str(exc).splitlines()[0] if str(exc) else type(exc).__name__,
        )
    finally:
        try:
            run.flush()  # files already copied are made safe whatever stopped us
        except Exception as exc:  # noqa: BLE001
            log.exception("Transfer could not commit its last batch")
            if status != STATUS_FAILED:
                status, error = STATUS_FAILED, f"Could not save progress: {exc}"
        run.p.current = None
        run.p.current_bytes = run.p.current_total = 0
        run.p.rate_bytes_per_second = 0.0
        run.p.eta_seconds = None
        run.p.files_total = max(run.p.files_total, _accounted(run.p))
        run.p.bytes_total = max(run.p.bytes_total, run.p.bytes_done)
    run.p.message = {
        STATUS_COMPLETED: "Finished",
        STATUS_PAUSED: reason or "Paused",
        STATUS_CANCELLED: "Cancelled",
        STATUS_FAILED: error or "Failed",
    }[status]
    run.emit(force=True)
    return Outcome(
        status=status,
        progress=TransferProgress(**vars(run.p)),
        failures=run.failures,
        failures_total=run.failures_total,
        pause_reason=reason,
        auto_resume=auto_resume,
        error=error,
    )


def _accounted(p: TransferProgress) -> int:
    return p.files_done + p.files_skipped + p.files_failed


def _move(store: FileObjectStore, run: _Run, item: _Item) -> None:
    """Move one file, or record why it couldn't be."""
    status = store.volume_status(item.source)
    if not status.reachable:
        raise VolumeNotResponding(item.source, status.reason)
    try:
        size = (
            item.size
            if item.size is not None
            else store.object_size(item.sha256, item.source)
        )
        target = _choose_target(store, run, size)
        run.p.current = item.sha256[:12]
        run.p.current_total = size
        run.p.current_bytes = 0

        def on_chunk(n: int) -> None:
            run.check_stop()
            run.p.current_bytes += n
            run.emit()

        result = _copy_with_retries(store, run, item, target, on_chunk)
        counted = True
        if result.reused:
            # Already complete on the target. If the catalog already says so too,
            # an earlier run moved and counted it and only the original is left.
            row = store.inventory_rows([item.sha256]).get(item.sha256)
            counted = not (row is not None and row[0] == target)
        if counted:
            needed = _accounted(run.p) + run.pending_files + 1
            if run.p.files_total < needed:
                # Found more than was counted at the start (uploads, or a catalog
                # that lagged the disk): the total grows to match.
                run.p.files_total = needed
                run.p.bytes_total += size
            run.pending_files += 1
        run.batch.append(
            _Moved(
                item.sha256,
                item.source,
                target,
                size,
                run.name_of(item.source, item.sha256),
                counted,
            )
        )
        run.batch_bytes += size
        run.pending[target] = run.pending.get(target, 0) + size
        run.p.current_bytes = 0
        if size >= LARGE_FILE:
            run.flush()  # a big file is committed at once, so progress is honest
    except ItemFailed as exc:
        run.p.current_bytes = 0
        run.fail(item, str(exc))


def _copy_with_retries(
    store: FileObjectStore,
    run: _Run,
    item: _Item,
    target: str,
    on_chunk: Callable[[int], None],
) -> CopyResult:
    attempt = 0
    while True:
        try:
            return store.transfer_object(
                item.sha256,
                item.source,
                target,
                verify=run.spec.verify,
                on_chunk=on_chunk,
            )
        except ItemFailed as exc:
            attempt += 1
            if not exc.retryable or attempt > RETRIES:
                raise
            run.p.current_bytes = 0
            log.info("Transfer: retrying %s (%s)", item.sha256, exc)
            time.sleep(RETRY_DELAY)
            run.check_stop()
