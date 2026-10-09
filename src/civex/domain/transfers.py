"""Moving stored files between volumes: what is asked for, what it would do,
how far along it is, and how it ended.

A transfer never deletes a file from its source until the copy on the
destination has been checked and the catalog says it lives there, so it can be
stopped, paused, or lose power at any moment without losing anything. The same
engine serves every kind of movement; the kinds differ only in how they choose
which files to move."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# -- what is being done ------------------------------------------------------

# Move everything off the source volume(s), e.g. before unplugging a drive.
KIND_DRAIN = "drain"
# Move the files of some collections onto a chosen volume, repairing a
# collection that has ended up split across drives.
KIND_CONSOLIDATE = "consolidate"
# Move exactly these files (by hash) onto a chosen volume, whatever collection
# they belong to: what a selection needs to be gathered onto one drive without
# moving anything else.
KIND_FILES = "files"
KINDS = (KIND_DRAIN, KIND_CONSOLIDATE, KIND_FILES)

# The most files one "files" transfer names: the list is kept on its record, so
# a selection beyond this is better narrowed (or gathered by collection).
MAX_TRANSFER_FILES = 100_000

# How a copy is checked before the original is removed.
# "copy": the file is hashed as it is copied and must match its recorded hash
#   (catches a corrupt source and any read error). Fast; the default.
# "full": the copy is then read back and hashed too (also catches a write that
#   silently went wrong on flaky media). Roughly doubles the reading.
VERIFY_COPY = "copy"
VERIFY_FULL = "full"
VERIFY_MODES = (VERIFY_COPY, VERIFY_FULL)

# -- how it is going ---------------------------------------------------------

STATUS_QUEUED = "queued"  # waiting its turn: one transfer runs at a time
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"  # stopped cleanly; resumable
STATUS_COMPLETED = "completed"  # every file handled (some may have failed)
STATUS_FAILED = "failed"  # stopped by an unexpected error; resumable
STATUS_CANCELLED = "cancelled"  # stopped for good by the user
STATUS_INTERRUPTED = "interrupted"  # the process died mid-run; resumable
STATUSES = (
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_PAUSED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_CANCELLED,
    STATUS_INTERRUPTED,
)
RESUMABLE = (STATUS_PAUSED, STATUS_FAILED, STATUS_INTERRUPTED)
# Everything a runner may be handed: a queued transfer, or one coming back.
STARTABLE = (STATUS_QUEUED, *RESUMABLE)
FINISHED = (STATUS_COMPLETED, STATUS_CANCELLED)

# What can be asked of a running transfer.
CONTROL_PAUSE = "pause"
CONTROL_CANCEL = "cancel"

# Failures kept in full on a record; further ones are only counted.
MAX_RECORDED_FAILURES = 200


@dataclass
class CopyResult:
    """What copying one file onto a target came to."""

    size: int
    # The file was already complete on the target (an earlier run copied it and
    # stopped before finishing the move), so nothing was written this time.
    reused: bool = False


@dataclass
class TransferSpec:
    """A request to move files."""

    kind: str
    # Volumes to put files on, in order of preference: a file goes to the first
    # that is usable and has room (like the write queue). One is enough.
    targets: list[str]
    # drain: the volumes to empty.
    sources: list[str] = field(default_factory=list)
    # consolidate: the collections (by id) whose files to move.
    collection_ids: list[str] = field(default_factory=list)
    # files: the content to move, by sha256. Files already on a target stay put.
    shas: list[str] = field(default_factory=list)
    # files: the records (by id) whose files these are: only they are pointed
    # at the target, and a copy other records point at stays. Empty: every
    # record that uses the files.
    record_ids: list[str] = field(default_factory=list)
    verify: str = VERIFY_COPY
    # drain: stop new files being written to the sources while it runs, and put
    # them back as they were afterwards (otherwise a busy volume never empties).
    freeze_sources: bool = True


@dataclass
class TargetShare:
    """How much of a transfer would land on one target."""

    volume: str
    files: int
    bytes: int
    free_bytes: int | None  # room the volume has, None if it can't be read now


@dataclass
class TransferPlan:
    """What a transfer would do, worked out before anything is moved. `problems`
    stop it from starting; `warnings` are worth knowing. The sizes come from the
    catalog, so they are close, not exact: the transfer counts what it finds."""

    files: int = 0  # files that would be moved
    bytes: int = 0
    already_there: int = 0  # files already on a target, left where they are
    # Of `files`, those copied rather than moved: the drive they come from is
    # the home of another collection that uses them, which keeps its copy.
    copied: int = 0
    copied_bytes: int = 0
    targets: list[TargetShare] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def can_proceed(self) -> bool:
        return not self.problems


@dataclass
class TransferProgress:
    """Where a transfer is, for a progress bar or a poll."""

    files_total: int = 0
    files_done: int = 0
    files_skipped: int = 0  # already on a target
    files_failed: int = 0
    bytes_total: int = 0
    bytes_done: int = 0
    current: str | None = None  # the file being copied
    current_bytes: int = 0
    current_total: int = 0
    rate_bytes_per_second: float = 0.0
    eta_seconds: float | None = None
    message: str = ""


@dataclass
class TransferFailure:
    """One file that couldn't be moved. It stays where it was."""

    sha256: str
    volume: str  # where it is
    reason: str


@dataclass
class TransferRecord:
    """A transfer as saved: the durable account of what was asked, how far it
    got and how it ended. A running transfer's live numbers also come from
    here, saved every moment or so."""

    id: str
    kind: str
    status: str
    spec: TransferSpec
    progress: TransferProgress
    plan: TransferPlan | None = None
    failures: list[TransferFailure] = field(default_factory=list)
    failures_total: int = 0  # may exceed len(failures), which is capped
    # Why it is paused, and whether it carries on by itself when it can.
    pause_reason: str | None = None
    auto_resume: bool = False
    error: str | None = None
    # A pause or cancel that has been asked for and not yet acted on.
    control: str | None = None
    # Sources made read-only for the duration, and what each was before.
    frozen: dict[str, str] = field(default_factory=dict)
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        data = asdict(self)
        for key in ("created_at", "started_at", "finished_at", "updated_at"):
            value = getattr(self, key)
            data[key] = value.isoformat() if value else None
        return data


# -- how a single file can go wrong ------------------------------------------


class TransferError(Exception):
    """Base for the ways moving one file can fail."""


class ItemFailed(TransferError):
    """This file can't be moved (its source is corrupt or has vanished, the copy
    didn't verify). It stays where it is and the transfer carries on.
    `retryable` is for failures that may pass on another try (a flaky read)."""

    def __init__(self, reason: str, retryable: bool = False) -> None:
        super().__init__(reason)
        self.retryable = retryable


class TargetFull(TransferError):
    """No target has room for the file. The transfer pauses."""


class VolumeNotResponding(TransferError):
    """A volume involved stopped answering. The transfer pauses, and carries on
    by itself when it answers again."""

    def __init__(self, volume: str, reason: str = "") -> None:
        super().__init__(f"Volume '{volume}' isn't responding. {reason}".strip())
        self.volume = volume
        self.reason = reason


class TransferStopped(TransferError):
    """The caller asked the transfer to pause or stop; it did, cleanly."""
