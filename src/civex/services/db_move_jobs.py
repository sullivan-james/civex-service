"""Running a database move in the background, for the HTTP API.

A move can take minutes, so the server starts it on a thread and the browser
polls for progress. The CLI doesn't use this: it runs `run_move` in the
foreground and draws its own progress bar. Both share the same engine, and
both write the same history file, so a move started from one shows up in the
other.

Jobs live in memory only. The durable record of a move is the history file
(civex.services.db_move_service); if the server restarts mid-move the thread is
gone and the history entry is reported as interrupted.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field

from civex.config import Config
from civex.db.move import Progress
from civex.domain.exceptions import ValidationError
from civex.services import db_move_service as moves
from civex.services.db_move_service import MoveRecord, TargetSpec

# Finished jobs kept so a browser that polls late still sees the outcome.
KEEP = 20


@dataclass
class MoveJob:
    id: str
    status: str = "running"  # running | done | failed | cancelled
    progress: Progress = field(
        default_factory=lambda: Progress("copy", message="Starting")
    )
    record: MoveRecord | None = None
    error: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event)


class MoveJobs:
    def __init__(self) -> None:
        self._jobs: dict[str, MoveJob] = {}
        self._lock = threading.Lock()

    def start(self, config: Config, spec: TargetSpec) -> MoveJob:
        """Check the move is possible (raising ValidationError if not, so the
        caller can say why straight away), then run it on a thread."""
        check = moves.preflight(config, spec)
        if not check.can_proceed:
            raise ValidationError(" ".join(check.problems))
        if moves.is_running():
            raise ValidationError("A database move is already running.")
        job = MoveJob(id=uuid.uuid4().hex[:12])
        with self._lock:
            self._jobs[job.id] = job
            for old in list(self._jobs)[:-KEEP]:
                del self._jobs[old]
        threading.Thread(
            target=self._run,
            args=(job, config, spec),
            daemon=True,
            name=f"db-move-{job.id}",
        ).start()
        return job

    def _run(self, job: MoveJob, config: Config, spec: TargetSpec) -> None:
        def on_progress(p: Progress) -> None:
            job.progress = Progress(**p.__dict__)  # a snapshot, not the live object

        try:
            job.record = moves.run_move(
                config, spec, progress=on_progress, cancel=job.cancel
            )
            job.status, job.error = job.record.status, job.record.error
        except Exception as exc:  # ValidationError (Docker down...) or anything else
            job.status = "failed"
            job.error = str(exc).splitlines()[0] if str(exc) else type(exc).__name__

    def get(self, job_id: str) -> MoveJob | None:
        return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.status != "running":
            return False
        job.cancel.set()
        return True


jobs = MoveJobs()
