"""The server's host for the transfer queue.

The queue and the rule for what runs next live in the service layer
(civex.services.transfer_worker); the terminal is another host for the same
worker. Here the worker runs on one thread inside the server, started the first
time something is queued (and at startup, to pick up whatever a restart left
waiting), and goes back to sleep when the queue is empty.

The thread also keeps the latest progress of the transfer it is running in
memory. The API reports that rather than the last saved copy, so the status
shown is live even if saving progress is briefly delayed. Everything that
matters is still in the saved record: if the server restarts, the running
transfer is reported as interrupted and can be resumed, and anything still
queued runs when the server is back.
"""

from __future__ import annotations

import logging
import threading

from civex.config import load_config
from civex.context import AppContext, build_local_context
from civex.domain.exceptions import ValidationError
from civex.domain.transfers import (
    CONTROL_CANCEL,
    CONTROL_PAUSE,
    TransferProgress,
    TransferRecord,
    TransferSpec,
)
from civex.services.transfer_engine import TransferControl
from civex.services.transfer_worker import TransferWorker

log = logging.getLogger(__name__)

# How often an idle worker looks for work another process queued (a terminal
# adding a move, a drive coming back for one that was waiting for it).
IDLE_POLL = 3.0


class TransferJobs:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._current: str | None = None
        self._control: TransferControl | None = None
        self._progress: TransferProgress | None = None
        self._worker = TransferWorker(self._context)

    # -- the worker ------------------------------------------------------------

    def ensure_worker(self) -> None:
        """Start the worker thread if it isn't running. Safe to call any time."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopping.clear()
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name="transfer-worker"
            )
            self._thread.start()

    def shutdown(self) -> None:
        self._stopping.set()
        self._wake.set()
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(2.0)
            if not thread.is_alive():
                with self._lock:
                    if self._thread is thread:
                        self._thread = None

    def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                self._worker.drain(
                    on_job_start=self._began,
                    on_job_end=self._ended,
                    on_progress=self._progressed,
                    should_stop=self._stopping.is_set,
                )
            except Exception:  # noqa: BLE001 - keep the worker alive
                log.exception("The transfer worker hit an error")
            self._wake.wait(IDLE_POLL)
            self._wake.clear()

    def _began(self, transfer_id: str, control: TransferControl) -> None:
        with self._lock:
            self._current, self._control, self._progress = transfer_id, control, None

    def _ended(self, transfer_id: str) -> None:
        with self._lock:
            if self._current == transfer_id:
                self._current = self._control = self._progress = None

    def _progressed(self, transfer_id: str, progress: TransferProgress) -> None:
        with self._lock:
            if self._current == transfer_id:
                self._progress = progress

    # -- what the API asks for -----------------------------------------------------

    def start(self, spec: TransferSpec) -> TransferRecord:
        """Check the transfer is possible (raising ValidationError, saying why,
        if not) and put it in the queue; it runs when its turn comes."""
        ctx = self._context()
        try:
            record = ctx.transfer_svc.create(spec)
        finally:
            ctx.close()
        self._kick()
        return record

    def resume(self, transfer_id: str) -> TransferRecord:
        if self.is_live(transfer_id):
            raise ValidationError("It is already running.")
        ctx = self._context()
        try:
            record = ctx.transfer_svc.begin_resume(transfer_id)
        finally:
            ctx.close()
        self._kick()
        return record

    def pause(self, transfer_id: str) -> bool:
        """Ask a transfer to pause. A running one does so within a moment,
        discarding any half-copied file (this works for one running in another
        process, a terminal, as well as here); a queued one is taken out of the
        queue. False if it is neither."""
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
        for the transfer running here, act on it at once."""
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
            control = self._control if self._current == transfer_id else None
        if control is not None:
            (control.pause if action == CONTROL_PAUSE else control.cancel)()
            return True
        return asked

    def is_live(self, transfer_id: str) -> bool:
        """Whether this server is running the transfer right now."""
        with self._lock:
            return self._current == transfer_id

    def live_progress(self, transfer_id: str) -> TransferProgress | None:
        """The latest progress of the transfer running here, newer than what is
        saved. None for any other transfer."""
        with self._lock:
            return self._progress if self._current == transfer_id else None

    def _kick(self) -> None:
        self.ensure_worker()
        self._wake.set()

    def _context(self) -> AppContext:
        # Read afresh each time: a transfer runs for hours, and volumes may be
        # edited meanwhile.
        return build_local_context(load_config())


jobs = TransferJobs()
