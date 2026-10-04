"""Running transfers in the background, for the HTTP API.

A transfer can take hours, so the server starts it on a thread and the browser
polls its saved record for progress (the CLI doesn't use this: it runs the
transfer in the foreground and draws its own progress bar). Both go through the
same service and the same saved record, so a transfer started from one shows up
in the other.

The thread is the only thing that is momentary. Everything that matters is in
the record, so if the server restarts the transfer is simply reported as
interrupted, and can be resumed.

A transfer that paused only because a volume stopped answering isn't left for
someone to notice: this waits for the volume and carries on by itself, unless
the user has paused or cancelled it.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from civex.config import load_config
from civex.context import AppContext, build_local_context
from civex.domain.exceptions import ValidationError
from civex.domain.transfers import (
    CONTROL_CANCEL,
    CONTROL_PAUSE,
    STATUS_PAUSED,
    TransferRecord,
    TransferSpec,
)
from civex.services.transfer_engine import TransferControl

log = logging.getLogger(__name__)

AUTO_RESUME_POLL = 5.0  # seconds between looking to see if a volume is back
AUTO_RESUME_GIVE_UP = 24 * 60 * 60.0  # then it stays paused until someone resumes it


@dataclass
class _Live:
    control: TransferControl
    thread: threading.Thread


class TransferJobs:
    def __init__(self) -> None:
        self._live: dict[str, _Live] = {}
        self._lock = threading.Lock()

    # -- what the API asks for -----------------------------------------------------

    def start(self, spec: TransferSpec) -> TransferRecord:
        """Check the transfer is possible (raising ValidationError, saying why,
        if not) and run it on a thread."""
        ctx = self._context()
        try:
            record = ctx.transfer_svc.create(spec)
        finally:
            ctx.close()
        self._spawn(record.id)
        return record

    def resume(self, transfer_id: str) -> TransferRecord:
        if self.is_live(transfer_id):
            raise ValidationError("It is already running.")
        ctx = self._context()
        try:
            record = ctx.transfer_svc.begin_resume(transfer_id)
        finally:
            ctx.close()
        self._spawn(record.id)
        return record

    def pause(self, transfer_id: str) -> bool:
        """Ask a running transfer to pause. It does so within a moment, discarding
        any half-copied file. Works for one running in another process (a
        terminal) as well as on a thread here. False if it isn't running."""
        return self._ask(transfer_id, CONTROL_PAUSE)

    def cancel(self, transfer_id: str) -> TransferRecord | None:
        """Stop a transfer for good. A running one stops within a moment; one
        that isn't running is closed straight away. Nothing already moved is
        moved back, and no file is ever lost."""
        if self._ask(transfer_id, CONTROL_CANCEL):
            return None
        ctx = self._context()
        try:
            return ctx.transfer_svc.cancel_idle(transfer_id)
        finally:
            ctx.close()

    def _ask(self, transfer_id: str, action: str) -> bool:
        """Record the request (so a process other than this one acts on it) and,
        for a thread here, act on it at once."""
        ctx = self._context()
        try:
            ctx.transfer_svc.request_control(transfer_id, action)
        except ValidationError:
            asked = False
        else:
            asked = True
        finally:
            ctx.close()
        with self._lock:
            live = self._live.get(transfer_id)
        if live is not None:
            (live.control.pause if action == CONTROL_PAUSE else live.control.cancel)()
            return True
        return asked

    def is_live(self, transfer_id: str) -> bool:
        with self._lock:
            live = self._live.get(transfer_id)
        return live is not None and live.thread.is_alive()

    # -- the thread ------------------------------------------------------------

    def _context(self) -> AppContext:
        # Read afresh each time: a transfer runs for hours, and volumes may be
        # edited meanwhile.
        return build_local_context(load_config())

    def _spawn(self, transfer_id: str) -> None:
        control = TransferControl()
        thread = threading.Thread(
            target=self._run,
            args=(transfer_id, control),
            daemon=True,
            name=f"transfer-{transfer_id[:8]}",
        )
        with self._lock:
            self._live[transfer_id] = _Live(control, thread)
        thread.start()

    def _run(self, transfer_id: str, control: TransferControl) -> None:
        try:
            while True:
                record = self._run_once(transfer_id, control)
                if (
                    record is not None
                    and record.status == STATUS_PAUSED
                    and record.auto_resume
                    and not control.stop_requested
                    and self._wait_for_volumes(transfer_id, control)
                ):
                    continue
                break
            if control.cancelled:
                self._close_cancelled(transfer_id)
        except Exception as exc:  # noqa: BLE001 - recorded, so it shows in the UI
            log.exception("Transfer %s stopped unexpectedly", transfer_id)
            self._record_failure(transfer_id, str(exc) or type(exc).__name__)
        finally:
            with self._lock:
                self._live.pop(transfer_id, None)

    def _run_once(
        self, transfer_id: str, control: TransferControl
    ) -> TransferRecord | None:
        ctx = self._context()
        try:
            try:
                return ctx.transfer_svc.execute(transfer_id, control)
            except ValidationError as exc:
                # It couldn't start (a garbage-collection pass holds the store):
                # say so on the record rather than leaving it looking busy.
                ctx.transfer_svc.hold(transfer_id, str(exc))
                return None
        finally:
            ctx.close()

    def _close_cancelled(self, transfer_id: str) -> None:
        """A cancel that arrived while the transfer was waiting for a drive: it
        is paused, so close it."""
        ctx = self._context()
        try:
            ctx.transfer_svc.cancel_idle(transfer_id)
        finally:
            ctx.close()

    def _wait_for_volumes(self, transfer_id: str, control: TransferControl) -> bool:
        """Wait until the volumes a paused transfer needs answer again. False if
        the user stopped it meanwhile, or it has been waiting too long."""
        deadline = time.monotonic() + AUTO_RESUME_GIVE_UP
        while time.monotonic() < deadline:
            slept = 0.0
            while slept < AUTO_RESUME_POLL:
                if control.stop_requested:
                    self._stop_waiting(transfer_id)
                    return False
                time.sleep(0.2)
                slept += 0.2
            ctx = self._context()
            try:
                asked = ctx.transfer_svc.pending_control(transfer_id)
                if asked == CONTROL_PAUSE:
                    control.pause()
                elif asked == CONTROL_CANCEL:
                    control.cancel()
                if control.stop_requested:
                    pass  # handled just below
                else:
                    record = ctx.transfer_svc.get(transfer_id)
                    if ctx.transfer_svc.volumes_ready(record):
                        return True
            finally:
                ctx.close()
            if control.stop_requested:
                self._stop_waiting(transfer_id)
                return False
        self._stop_waiting(transfer_id)
        return False

    def _stop_waiting(self, transfer_id: str) -> None:
        ctx = self._context()
        try:
            ctx.transfer_svc.stop_waiting(transfer_id)
        finally:
            ctx.close()

    def _record_failure(self, transfer_id: str, message: str) -> None:
        try:
            ctx = self._context()
            try:
                ctx.transfer_svc.fail(transfer_id, message)
            finally:
                ctx.close()
        except Exception:  # noqa: BLE001
            log.exception("Could not record the failure of transfer %s", transfer_id)


jobs = TransferJobs()
