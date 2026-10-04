"""Running the transfer queue.

Transfers wait in the database (status `queued`) and run one at a time, oldest
first. This is the one place that decides what runs next, so the terminal and
the server behave the same: both are just hosts that call `drain`. The CLI runs
it in the foreground and draws a progress bar; the server runs it on a thread
(civex.services.transfer_jobs) and reports the live progress.

Only one process can be moving files at once (the store's transfer lock). If
another process holds it, `drain` stops and says so; that process finishes the
queue, so nothing is lost and nothing runs twice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from civex.domain.exceptions import CivexError
from civex.domain.transfers import TransferProgress, TransferRecord
from civex.services.transfer_engine import TransferControl
from civex.services.transfer_service import TransferBusy

if TYPE_CHECKING:
    from civex.context import AppContext

log = logging.getLogger(__name__)


@dataclass
class DrainResult:
    ran: list[TransferRecord] = field(default_factory=list)
    # Stopped because another process holds the transfer lock. It is running the
    # queue, so what is left is not stranded.
    busy: bool = False


class TransferWorker:
    def __init__(self, context_factory: Callable[[], "AppContext"]) -> None:
        # A fresh context for each step: a transfer runs for hours, and volumes
        # and settings may be edited meanwhile.
        self._context = context_factory

    def drain(
        self,
        *,
        on_job_start: Callable[[str, TransferControl], None] | None = None,
        on_job_end: Callable[[str], None] | None = None,
        on_progress: Callable[[str, TransferProgress], None] | None = None,
        should_stop: Callable[[], bool] = lambda: False,
    ) -> DrainResult:
        """Run queued transfers one after another until none is ready, `should_stop`
        says so, or another process holds the lock. Each transfer gets its own
        `TransferControl`, so pausing one doesn't stop the rest."""
        result = DrainResult()
        skip: set[str] = set()
        while not should_stop():
            ctx = self._context()
            try:
                record = ctx.transfer_svc.next_runnable(skip)
                if record is None:
                    return result
                control = TransferControl()
                if on_job_start is not None:
                    on_job_start(record.id, control)
                try:
                    finished = self._run(ctx, record, control, on_progress, skip)
                finally:
                    if on_job_end is not None:
                        on_job_end(record.id)
                if finished is TransferBusy:
                    result.busy = True
                    return result
                if finished is not None:
                    result.ran.append(finished)  # type: ignore[arg-type]
            finally:
                ctx.close()
        return result

    @staticmethod
    def _run(
        ctx: "AppContext",
        record: TransferRecord,
        control: TransferControl,
        on_progress: Callable[[str, TransferProgress], None] | None,
        skip: set[str],
    ) -> "TransferRecord | type[TransferBusy] | None":
        svc = ctx.transfer_svc

        def report(progress: TransferProgress) -> None:
            if on_progress is not None:
                on_progress(record.id, progress)

        try:
            done = svc.execute(record.id, control, report)
        except TransferBusy:
            return TransferBusy
        except CivexError as exc:
            # It can't be run (it changed state under us). Not this pass again.
            log.warning("Transfer %s skipped: %s", record.id, exc)
            skip.add(record.id)
            return None
        except Exception as exc:  # noqa: BLE001 - recorded, so it shows in the UI
            log.exception("Transfer %s stopped unexpectedly", record.id)
            skip.add(record.id)
            try:
                svc.fail(record.id, str(exc) or type(exc).__name__)
            except Exception:  # noqa: BLE001
                log.exception("Could not record the failure of transfer %s", record.id)
            return None
        if done.auto_resume:
            skip.add(done.id)
        return done
