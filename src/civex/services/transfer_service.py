"""Moving stored files between volumes: planning a transfer, keeping its record,
and running it through the engine (civex.services.transfer_engine).

This is the layer that knows about the database record, about freezing a source
volume while it is emptied, and about telling a transfer that is running from
one whose process died. Threads and polling are the job runner's business
(civex.services.transfer_jobs); this module is the same for the CLI, which runs
a transfer in the foreground, and the server, which runs it on a thread.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable

from civex import fs_locations
from civex.config import Config
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.domain.transfers import (
    CONTROL_CANCEL,
    CONTROL_PAUSE,
    FINISHED,
    KIND_CONSOLIDATE,
    KIND_DRAIN,
    KINDS,
    RESUMABLE,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_INTERRUPTED,
    STATUS_PAUSED,
    STATUS_RUNNING,
    VERIFY_FULL,
    VERIFY_MODES,
    TargetShare,
    TransferPlan,
    TransferProgress,
    TransferRecord,
    TransferSpec,
)
from civex.services.transfer_engine import (
    PAGE,
    ProgressFn,
    Seed,
    TransferControl,
    run_transfer,
)

if TYPE_CHECKING:
    from civex.repositories.protocols import (
        DatasetRepository,
        FileObjectStore,
        FileReferenceRepository,
        TransferRepository,
    )
    from civex.services.store_service import StoreService

log = logging.getLogger(__name__)

# A running transfer saves its progress about twice a second. One that hasn't
# for this long belongs to a process that has died.
STALE_SECONDS = 90.0

INTERRUPTED_REASON = (
    "The program stopped while this was running. Nothing was lost; "
    "resume it to carry on."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class TransferService:
    def __init__(
        self,
        config: Config,
        store: FileObjectStore,
        refs: FileReferenceRepository,
        transfers: TransferRepository,
        datasets: DatasetRepository,
        store_svc: StoreService,
        commit: Callable[[], None],
    ) -> None:
        self._config = config
        self._store = store
        self._refs = refs
        self._transfers = transfers
        self._datasets = datasets
        self._store_svc = store_svc
        self._commit = commit

    # -- reading ---------------------------------------------------------------

    def get(self, transfer_id: str) -> TransferRecord:
        record = self._transfers.get(transfer_id)
        if record is None:
            raise NotFoundError(f"No transfer '{transfer_id}'.")
        return self._reap(record)

    def recent(self, limit: int = 50) -> list[TransferRecord]:
        return [self._reap(r) for r in self._transfers.recent(limit)]

    def _reap(self, record: TransferRecord) -> TransferRecord:
        """A record still marked running whose progress stopped being saved
        belongs to a process that died: say so, so it can be resumed."""
        if (
            record.status == STATUS_RUNNING
            and record.updated_at is not None
            and (_now() - record.updated_at).total_seconds() > STALE_SECONDS
        ):
            record.status = STATUS_INTERRUPTED
            record.pause_reason = INTERRUPTED_REASON
            self._transfers.save(record)
            self._commit()
        return record

    def active(self) -> TransferRecord | None:
        """The transfer that is running right now, if any."""
        for record in self._transfers.running():
            if self._reap(record).status == STATUS_RUNNING:
                return record
        return None

    # -- planning ---------------------------------------------------------------

    def _placements(self) -> dict[str, str]:
        return {
            cid: place.volume
            for cid, place in self._config.store_config.placement.items()
        }

    def _is_network(self, volume: str) -> bool:
        path = fs_locations.normalise(str(self._store.volume_path(volume)))
        return fs_locations.is_network_path(path)

    def plan(self, spec: TransferSpec) -> TransferPlan:
        """What `spec` would do: how many files and bytes would move, where they
        would go, and anything that stops it or is worth knowing. Reads only;
        the sizes are from the catalog, so they are close rather than exact."""
        plan = TransferPlan()
        volumes = self._config.store_config.volumes
        store = self._store

        if spec.kind not in KINDS:
            plan.problems.append(f"A transfer is one of: {', '.join(KINDS)}.")
        if spec.verify not in VERIFY_MODES:
            plan.problems.append(f"Verification is one of: {', '.join(VERIFY_MODES)}.")
        if not spec.targets:
            plan.problems.append("Choose at least one volume to move the files to.")
        for name in spec.targets + spec.sources:
            if name not in volumes:
                plan.problems.append(f"There is no volume called '{name}'.")
        if len(set(spec.targets)) != len(spec.targets):
            plan.problems.append("A target volume is listed twice.")
        if spec.kind == KIND_DRAIN:
            if not spec.sources:
                plan.problems.append("Choose which volume to move the files off.")
            overlap = sorted(set(spec.sources) & set(spec.targets))
            if overlap:
                plan.problems.append(
                    f"'{overlap[0]}' can't be both the volume emptied and where its files go."
                )
        if spec.kind == KIND_CONSOLIDATE:
            plan.problems += self._check_collections(spec)
        if plan.problems:
            return plan

        for name in spec.sources:
            status = store.volume_status(name)
            if not status.reachable:
                plan.problems.append(
                    f"'{name}' isn't available ({status.reason}). {status.fix}".strip()
                )
        for name in spec.targets:
            status = store.volume_status(name)
            if not status.writable:
                why = status.reason or status.state.replace("_", " ")
                plan.problems.append(f"'{name}' can't be written to: {why}.")
        running = self.active()
        if running is not None:
            plan.problems.append(
                "Another transfer is running. Wait for it to finish, or pause it."
            )
        if plan.problems:
            return plan

        if spec.kind == KIND_DRAIN:
            totals = store.inventory_totals(spec.sources)
            plan.files = sum(f for f, _ in totals.values())
            plan.bytes = sum(b for _, b in totals.values())
            if plan.files == 0:
                plan.warnings.append(
                    "No files are recorded on "
                    + ", ".join(f"'{s}'" for s in spec.sources)
                    + ", so there is nothing to move."
                )
        else:
            self._size_consolidation(spec, plan)

        self._fit(spec, plan)
        self._warn(spec, plan)
        return plan

    def _check_collections(self, spec: TransferSpec) -> list[str]:
        problems = []
        if not spec.collection_ids:
            return ["Choose which collection's files to move."]
        for cid in spec.collection_ids:
            try:
                dataset = self._datasets.get_by_id(
                    uuid.UUID(cid),
                    include_deleted=False,
                    with_count=False,
                    with_schemas=False,
                )
            except ValueError:
                problems.append(f"'{cid}' is not a collection id.")
                continue
            if dataset is None:
                problems.append("A chosen collection no longer exists.")
        return problems

    def _size_consolidation(self, spec: TransferSpec, plan: TransferPlan) -> None:
        """Count what consolidating would move, skip and leave, the way the
        engine will choose it."""
        selected = set(spec.collection_ids)
        placements = self._placements()
        after: str | None = None
        unknown_count = 0
        while True:
            shas = self._refs.shas_for_collections(spec.collection_ids, after, PAGE)
            if not shas:
                break
            after = shas[-1]
            rows = self._store.inventory_rows(shas)
            users = (
                self._refs.collections_using(shas) if not spec.include_shared else {}
            )
            for sha in shas:
                row = rows.get(sha)
                if row is None:
                    unknown_count += 1
                    continue
                volume, size = row
                if volume in spec.targets:
                    plan.already_there += 1
                    continue
                others = users.get(sha, set()) - selected
                if any(placements.get(c) not in (None, *spec.targets) for c in others):
                    plan.shared_left += 1
                    plan.shared_left_bytes += size
                    continue
                plan.files += 1
                plan.bytes += size
        if unknown_count:
            plan.warnings.append(
                f"{unknown_count} file(s) used by these collections aren't in the "
                "catalog, so they aren't counted here (running garbage collection "
                "refreshes it); the transfer moves what it finds."
            )

    def _fit(self, spec: TransferSpec, plan: TransferPlan) -> None:
        """Share the bytes out across the targets in order, as the transfer will,
        and say if they don't all fit."""
        remaining_bytes, remaining_files = plan.bytes, plan.files
        for name in spec.targets:
            room = self._store.room_on(name)
            share = min(remaining_bytes, room) if room is not None else 0
            files = (
                round(remaining_files * share / remaining_bytes)
                if remaining_bytes
                else 0
            )
            plan.targets.append(TargetShare(name, files, share, room))
            remaining_bytes -= share
            remaining_files -= files
            if room is None:
                plan.warnings.append(
                    f"Can't read how much room '{name}' has right now."
                )
        if remaining_bytes > 0:
            have = sum(t.free_bytes or 0 for t in plan.targets)
            plan.problems.append(
                f"The files need {_size(plan.bytes)} but the targets have room for "
                f"{_size(have)}. Free some space or add another target."
            )

    def _warn(self, spec: TransferSpec, plan: TransferPlan) -> None:
        if spec.kind == KIND_DRAIN and spec.freeze_sources:
            names = ", ".join(f"'{s}'" for s in spec.sources)
            plan.warnings.append(
                f"{names} will be made read-only while this runs, so nothing new "
                "is written to it, and set back afterwards."
            )
        slow = [n for n in spec.sources + spec.targets if self._is_network(n)]
        if slow:
            plan.warnings.append(
                "Network drives ("
                + ", ".join(f"'{n}'" for n in dict.fromkeys(slow))
                + ") can be slow, and if one stops answering the transfer pauses "
                "and carries on by itself when it does."
            )
        if spec.verify == VERIFY_FULL:
            plan.warnings.append(
                "Full verification reads every copy back, which roughly doubles the "
                "reading."
            )
        if spec.kind == KIND_CONSOLIDATE and plan.shared_left:
            plan.warnings.append(
                f"{plan.shared_left} file(s) ({_size(plan.shared_left_bytes)}) are also "
                "used by collections kept elsewhere and will stay where they are."
            )
        if plan.already_there:
            plan.warnings.append(
                f"{plan.already_there} file(s) are already on a target and are left alone."
            )

    # -- starting, resuming, stopping ---------------------------------------------

    def create(self, spec: TransferSpec) -> TransferRecord:
        """Check `spec` and save it as a running transfer. Raises
        ValidationError, saying why, if it can't be done."""
        spec.collection_ids = [str(uuid.UUID(c)) for c in spec.collection_ids]
        plan = self.plan(spec)
        if not plan.can_proceed:
            raise ValidationError(" ".join(plan.problems))
        now = _now()
        record = TransferRecord(
            id=str(uuid.uuid4()),
            kind=spec.kind,
            status=STATUS_RUNNING,
            spec=spec,
            plan=plan,
            progress=TransferProgress(
                files_total=plan.files,
                bytes_total=plan.bytes,
                message="Starting",
            ),
            created_at=now,
            started_at=now,
        )
        self._transfers.create(record)
        self._commit()
        return record

    def request_control(self, transfer_id: str, action: str) -> TransferRecord:
        """Ask a running transfer to pause or cancel. The request is saved, and
        the process running it acts on it within a moment, whichever process
        that is (the web server for one started in the browser, the terminal
        for one started there)."""
        if action not in (CONTROL_PAUSE, CONTROL_CANCEL):
            raise ValidationError("A transfer can be asked to pause or cancel.")
        record = self.get(transfer_id)
        if record.status != STATUS_RUNNING:
            raise ValidationError(f"It isn't running (it is {record.status}).")
        self._transfers.set_control(transfer_id, action)
        self._commit()
        record.control = action
        return record

    def pending_control(self, transfer_id: str) -> str | None:
        return self._transfers.control(transfer_id)

    def begin_resume(self, transfer_id: str) -> TransferRecord:
        """Mark a paused, failed or interrupted transfer as running again, ready
        for the job runner to pick it up."""
        record = self.get(transfer_id)
        if record.status not in RESUMABLE:
            raise ValidationError(f"A {record.status} transfer can't be resumed.")
        running = self.active()
        if running is not None and running.id != record.id:
            raise ValidationError("Another transfer is running. Wait for it to finish.")
        record.status = STATUS_RUNNING
        record.pause_reason = None
        record.error = None
        record.auto_resume = False
        record.control = None
        record.progress.message = "Resuming"
        self._transfers.save(record)
        self._transfers.set_control(record.id, None)
        self._commit()
        return record

    def hold(self, transfer_id: str, reason: str) -> None:
        """Park a transfer that couldn't start (another is running, GC is) as
        paused, with the reason, instead of leaving it looking busy."""
        record = self.get(transfer_id)
        record.status = STATUS_PAUSED
        record.pause_reason = reason
        record.auto_resume = False
        self._transfers.save(record)
        self._commit()

    def fail(self, transfer_id: str, message: str) -> None:
        """Record that a transfer was stopped by something unexpected."""
        record = self.get(transfer_id)
        record.status = STATUS_FAILED
        record.error = message
        record.auto_resume = False
        self._transfers.save(record)
        self._commit()

    def stop_waiting(self, transfer_id: str) -> None:
        """A transfer waiting for a volume to return is not going to carry on
        by itself any more (the user paused it, or gave up waiting)."""
        record = self.get(transfer_id)
        if record.status == STATUS_PAUSED and record.auto_resume:
            record.auto_resume = False
            self._transfers.save(record)
            self._commit()

    def cancel_idle(self, transfer_id: str) -> TransferRecord:
        """Cancel a transfer that isn't running (paused, failed, interrupted):
        nothing is moved, the sources it froze are restored, and it is closed."""
        record = self.get(transfer_id)
        if record.status in FINISHED:
            return record
        if record.status == STATUS_RUNNING:
            raise ValidationError("It is running; stop it first.")
        self._unfreeze(record)
        record.status = STATUS_CANCELLED
        record.pause_reason = None
        record.auto_resume = False
        record.finished_at = _now()
        record.progress.message = "Cancelled"
        self._transfers.save(record)
        self._commit()
        return record

    def volumes_ready(self, record: TransferRecord) -> bool:
        """Whether every volume the transfer touches answers (and the targets
        can be written), i.e. whether a transfer paused for one can carry on."""
        spec = record.spec
        return all(
            self._store.volume_status(v).reachable for v in spec.sources
        ) and all(self._store.volume_status(v).writable for v in spec.targets)

    # -- running ---------------------------------------------------------------

    def execute(
        self,
        transfer_id: str,
        control: TransferControl | None = None,
        on_progress: ProgressFn | None = None,
    ) -> TransferRecord:
        """Run the transfer until it finishes, pauses, is cancelled or fails, in
        the calling thread, saving its progress as it goes. The record says how
        it ended. Raises ValidationError if it can't start (another transfer, or
        a garbage-collection pass, holds the store)."""
        from civex.domain.exceptions import GCAlreadyRunningError

        record = self.get(transfer_id)
        if record.status not in (STATUS_RUNNING, *RESUMABLE):
            raise ValidationError(f"A {record.status} transfer can't be run.")
        try:
            with self._store.transfer_lock():
                return self._execute_locked(
                    record, control or TransferControl(), on_progress
                )
        except GCAlreadyRunningError as exc:
            raise ValidationError(str(exc)) from exc

    def _execute_locked(
        self,
        record: TransferRecord,
        control: TransferControl,
        on_progress: ProgressFn | None,
    ) -> TransferRecord:
        self._freeze(record)
        record.status = STATUS_RUNNING
        record.pause_reason = None
        record.error = None
        record.auto_resume = False
        record.finished_at = None
        record.started_at = record.started_at or _now()
        record.control = None
        self._transfers.set_control(record.id, None)
        self._save(record)

        def saving(progress: TransferProgress) -> None:
            record.progress = progress
            self._save(record, quiet=True)
            self._obey_requests(record.id, control)
            if on_progress is not None:
                on_progress(progress)

        outcome = run_transfer(
            self._store,
            self._refs,
            record.spec,
            placements=self._placements(),
            progress=saving,
            commit=self._commit,
            control=control,
            seed=Seed(record.progress, record.failures, record.failures_total),
        )
        record.progress = outcome.progress
        record.failures = outcome.failures
        record.failures_total = outcome.failures_total
        record.status = outcome.status
        record.pause_reason = outcome.pause_reason
        record.auto_resume = outcome.auto_resume
        record.error = outcome.error
        if outcome.status in (STATUS_COMPLETED, STATUS_CANCELLED):
            record.finished_at = _now()
            self._unfreeze(record)  # the sources go back to how they were
        self._save(record)
        return record

    def _obey_requests(self, transfer_id: str, control: TransferControl) -> None:
        """Act on a pause or cancel someone asked for from another process."""
        try:
            asked = self._transfers.control(transfer_id)
        except Exception:
            log.warning("Could not check for a pause request", exc_info=True)
            return
        if asked == CONTROL_PAUSE:
            control.pause()
        elif asked == CONTROL_CANCEL:
            control.cancel()

    def _save(self, record: TransferRecord, quiet: bool = False) -> None:
        """Save the record. A failure to save progress (the database was busy for
        a moment) must not stop the files being moved, so progress saves only log."""
        try:
            self._transfers.save(record)
            self._commit()
        except Exception:
            if not quiet:
                raise
            log.warning("Could not save transfer progress", exc_info=True)

    # -- freezing the sources ------------------------------------------------------

    def _freeze(self, record: TransferRecord) -> None:
        """Make the volumes being emptied read-only, so new uploads don't keep
        landing on them, remembering what each was to put it back. A volume that
        was already read-only or retired is left as it was."""
        spec = record.spec
        if spec.kind != KIND_DRAIN or not spec.freeze_sources:
            return
        volumes = self._config.store_config.volumes
        for name in spec.sources:
            if name in record.frozen or name not in volumes:
                continue
            before = volumes[name].state
            if before == "active":
                record.frozen[name] = before
                self._store_svc.set_volume_state(name, "readonly")

    def _unfreeze(self, record: TransferRecord) -> None:
        volumes = self._config.store_config.volumes
        for name, before in list(record.frozen.items()):
            # Only undo our own change: someone may have set it since.
            if name in volumes and volumes[name].state == "readonly":
                self._store_svc.set_volume_state(name, before)
            del record.frozen[name]
