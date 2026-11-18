"""How far each running workflow run has got, held in memory.

The executor says which step a run is on (`step_started`), and a plugin says
how far that step has got (`report`, from `WorkflowContext.progress` or a
subprocess plugin's `progress` frame). `GET /automation` reads it for the
status bar. Nothing here is saved: it describes a run while it lasts, in the
process running it, and is gone when the run ends (`finished`).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class StepProgress:
    job_id: str
    workflow: str
    step: str
    plugin: str
    done: float | None = None
    total: float | None = None
    message: str = ""
    updated: float = 0.0


class RunProgress:
    def __init__(self) -> None:
        self._runs: dict[str, StepProgress] = {}
        self._lock = threading.Lock()

    def step_started(self, job_id: str, workflow: str, step: str, plugin: str) -> None:
        with self._lock:
            self._runs[job_id] = StepProgress(
                job_id, workflow, step, plugin, updated=time.time()
            )

    def report(
        self,
        job_id: str,
        done: float | None,
        total: float | None = None,
        message: str = "",
    ) -> None:
        """How far the step `job_id` is on has got. Ignored for a run not
        started here (a step with no run, as in a test)."""
        with self._lock:
            current = self._runs.get(job_id)
            if current is None:
                return
            self._runs[job_id] = replace(
                current, done=done, total=total, message=message, updated=time.time()
            )

    def finished(self, job_id: str) -> None:
        with self._lock:
            self._runs.pop(job_id, None)

    def of(self, job_ids: list[str]) -> list[StepProgress]:
        """The progress of those of `job_ids` running here."""
        with self._lock:
            return [self._runs[j] for j in job_ids if j in self._runs]


RUNS = RunProgress()
