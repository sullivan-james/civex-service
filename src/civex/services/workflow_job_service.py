from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from civex.config import load_config, read_automation_paused, save_config
from civex.domain.dtos import ErrorEnvelope, RecordDTO, WorkflowJobDTO
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.domain.filters import FilterNode
from civex.domain.run_filters import parse_run_filter
from civex.repositories.protocols import WorkflowJobRepository
from civex.workflows.definition import WorkflowDef, load_workflow

log = logging.getLogger(__name__)

MAX_JOB_DEPTH = 10

PAUSED_MESSAGE = (
    "Automation is paused, so nothing new will run. Resume it to run workflows."
)
STOPPED_REASON = "Stopped by the user."

# How much of a changed value a run keeps, and how many changed fields: enough
# to see what happened and to spot a value that "changed" to itself, without a
# file's contents or a long list being copied onto every run.
_VALUE_CHARS = 120
_MAX_CHANGES = 25


def _parsed(where: Any) -> FilterNode | None:
    """A run filter as given (JSON text or already decoded) checked and parsed;
    None when there is none. Anything malformed is a ValidationError."""
    if where is None or where == "":
        return None
    if isinstance(where, str):
        try:
            where = json.loads(where)
        except json.JSONDecodeError as e:
            raise ValidationError(f"Run filter isn't valid JSON: {e}")
    return parse_run_filter(where)


def _summarise(value: object) -> str | None:
    """A short, readable form of a field value for a run's record of what
    changed. None stays None, a file shows its name, a list its length."""
    if value is None:
        return None
    if isinstance(value, dict):
        name = value.get("filename")
        if isinstance(name, str):
            return name
    if isinstance(value, (list, tuple)):
        return f"{len(value)} item{'' if len(value) == 1 else 's'}"
    text = str(value)
    return text if len(text) <= _VALUE_CHARS else text[: _VALUE_CHARS - 1] + "…"


class WorkflowJobService:
    def __init__(self, repo: WorkflowJobRepository, civex_dir: Path) -> None:
        self._repo = repo
        self._civex_dir = civex_dir
        self._loaded: tuple[tuple, list[WorkflowDef]] | None = None

    def _load_workflows(self) -> list[WorkflowDef]:
        """Every parseable workflow. Every record write asks, so the files are
        only re-read when one has changed (name, size or mtime) -- a stat per
        file, not a YAML parse per file, per record."""
        wf_dir = self._civex_dir / "workflows"
        if not wf_dir.exists():
            return []
        paths = sorted(wf_dir.glob("*.yaml")) + sorted(wf_dir.glob("*.yml"))
        stamp = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in paths)
        if self._loaded is not None and self._loaded[0] == stamp:
            return self._loaded[1]
        result: list[WorkflowDef] = []
        for path in paths:
            try:
                result.append(load_workflow(path))
            except Exception as e:
                log.warning("Skipping unparseable workflow file %s: %s", path, e)
        self._loaded = (stamp, result)
        return result

    def find_workflow(self, name: str) -> WorkflowDef | None:
        """Match by workflow name or filename stem (with or without .yaml/.yml extension)."""
        stem = name.removesuffix(".yml").removesuffix(".yaml")
        wf_dir = self._civex_dir / "workflows"
        for path in sorted(wf_dir.glob("*.yaml")) + sorted(wf_dir.glob("*.yml")):
            try:
                wf = load_workflow(path)
            except Exception as e:
                log.warning("Skipping unparseable workflow file %s: %s", path, e)
                continue
            if (
                wf.name == name
                or wf.name == stem
                or path.stem == name
                or path.stem == stem
            ):
                return wf
        return None

    # -- the kill switch ---------------------------------------------------------

    def is_paused(self) -> bool:
        """Whether automation is paused (see `AutomationConfig`). The one
        question every gate below asks, so the server, the terminal and every
        trigger agree."""
        return read_automation_paused(self._civex_dir)

    def set_paused(self, paused: bool) -> None:
        # Re-read config.toml first: it holds other settings too, and this must
        # never write back a stale copy over edits made meanwhile.
        config = load_config()
        config.automation.paused = paused
        save_config(config)

    def stop_all(self) -> int:
        """Stop automation: pause it (so nothing new is triggered or started)
        and cancel every waiting and running run. A running one stops before its
        next step. Returns how many runs were cancelled. Pausing comes first, so
        a run can't spawn more between the two."""
        self.set_paused(True)
        return self._repo.cancel_all_active(STOPPED_REASON)

    def resume(self) -> None:
        self.set_paused(False)

    def cancel_job(self, job_id: uuid.UUID) -> WorkflowJobDTO:
        """Cancel one run: a waiting one never starts, a running one stops before
        its next step. A finished run is left as it is."""
        job = self._repo.cancel(job_id, STOPPED_REASON)
        if job is None:
            raise NotFoundError(f"No job '{job_id}'")
        return job

    def delete_runs(self, ids: list[uuid.UUID]) -> int:
        """Delete runs, whatever their state, with their step logs. A waiting
        run never starts (claiming takes only a row still there); a running one
        stops before its next step (`should_stop` finds no row) and what it
        reports at the end is dropped; a finished one is just gone. The changes
        a run already made to records stay, in their history. How many were
        deleted."""
        return self._repo.delete_jobs(list(dict.fromkeys(ids)))

    def should_stop(self, job_id: uuid.UUID) -> bool:
        """Asked by a running job between steps: has it been cancelled (from
        another request or process), or has automation been paused?"""
        return self.is_paused() or self._repo.status_of(job_id) != "running"

    def automation_state(self) -> dict:
        return {
            "paused": self.is_paused(),
            "pending": self._repo.count(status="pending"),
            "running": self._repo.count(status="running"),
            "batch": None if self.is_paused() else self._repo.batch_stats(),
        }

    def trigger_for_record(
        self,
        record: RecordDTO,
        event: str,
        changed_fields: set[str] | None = None,
        depth: int = 0,
        changes: dict[str, tuple[object, object]] | None = None,
        cause: dict | None = None,
    ) -> list[WorkflowJobDTO]:
        """Enqueue jobs for every workflow whose trigger matches this event + schema.

        For record_updated, if the trigger declares a fields list and changed_fields is
        provided, only enqueue if at least one watched field actually changed.

        `changes` maps each changed field to its (before, after), and `cause`
        names the run whose own save this is ({job_id, workflow}), when there is
        one. Both are kept on the job (`trigger_detail`) so a run can say exactly
        what started it, and a chain of runs can be followed back to its start.

        depth tracks how many workflow-triggered-by-workflow hops deep this call is.
        Jobs at or above MAX_JOB_DEPTH are silently dropped to break runaway chains.
        """
        if self.is_paused():
            return []
        if depth >= MAX_JOB_DEPTH:
            import logging

            logging.getLogger(__name__).warning(
                "Workflow loop detected: refusing to enqueue jobs at depth %d "
                "(record %s, event %s). Add `fields:` filter to your trigger to prevent this.",
                depth,
                record.id,
                event,
            )
            return []
        jobs: list[WorkflowJobDTO] = []
        for wf in self._load_workflows():
            if wf.triggers is None:
                continue
            trigger_def = getattr(wf.triggers, event, None)
            if trigger_def is None or trigger_def.schema_name != record.schema_name:
                continue
            if trigger_def.fields and changed_fields is not None:
                if not any(f in changed_fields for f in trigger_def.fields):
                    continue
            watched = trigger_def.fields or []
            detail = {
                "changes": [
                    {
                        "field": name,
                        "before": _summarise(before),
                        "after": _summarise(after),
                        # With no `fields:` list, every field is watched.
                        "watched": not watched or name in watched,
                    }
                    for name, (before, after) in sorted((changes or {}).items())[
                        :_MAX_CHANGES
                    ]
                ],
                "caused_by": cause,
            }
            job = self._repo.enqueue(
                wf.name, record.id, event, depth=depth, trigger_detail=detail
            )
            jobs.append(job)
        return jobs

    def enqueue_manual(
        self,
        workflow_name: str,
        record: RecordDTO,
        input_data: dict | None = None,
    ) -> WorkflowJobDTO:
        if self.is_paused():
            raise ValidationError(PAUSED_MESSAGE)
        return self._repo.enqueue(
            workflow_name,
            record.id,
            "manual",
            input_data=input_data,
        )

    def claim_pending(self) -> WorkflowJobDTO | None:
        """The next waiting run, marked running; None when there is none or
        automation is paused. Every drain loop (server and terminal) takes its
        work from here, so pausing stops them all at once."""
        if self.is_paused():
            return None
        return self._repo.claim_pending()

    def mark_cancelled(
        self,
        job_id: uuid.UUID,
        log: str | None = None,
        step_executions: list[dict] | None = None,
        affected_records: list[dict] | None = None,
    ) -> None:
        self._repo.mark_cancelled(
            job_id,
            log=log,
            step_executions=step_executions,
            affected_records=affected_records,
        )

    def mark_completed(
        self,
        job_id: uuid.UUID,
        log: str | None = None,
        step_executions: list[dict] | None = None,
        affected_records: list[dict] | None = None,
    ) -> None:
        self._repo.mark_completed(
            job_id,
            log=log,
            step_executions=step_executions,
            affected_records=affected_records,
        )

    def mark_failed(
        self,
        job_id: uuid.UUID,
        envelope: ErrorEnvelope,
        log: str | None = None,
        step_executions: list[dict] | None = None,
        affected_records: list[dict] | None = None,
    ) -> None:
        """`envelope` (CIVEX-143) is the single source for both the flat
        `error` message and the structured `error_details` -- every caller
        already builds one (`from_exception` at worst), so there's no reason
        to also pass the message as a separate string and risk it drifting
        from `envelope.message` (CIVEX-171). `step_executions` (CIVEX-117) is
        the per-step record of however far the run got before failing --
        optional because a failure before the first step ran has none to
        report. `affected_records` is the same idea for the records the run
        touched before it failed."""
        self._repo.mark_failed(
            job_id,
            envelope.to_dict(),
            log=log,
            step_executions=step_executions,
            affected_records=affected_records,
        )

    def list_jobs(
        self,
        status: str | None = None,
        record_id: str | None = None,
        affected_record_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
        affected_schema: str | None = None,
        trigger: str | None = None,
        search: str | None = None,
        sort: str | None = None,
        workflow: str | None = None,
        where: Any = None,
    ) -> list[WorkflowJobDTO]:
        return self._repo.list_all(
            where=_parsed(where),
            workflow=workflow,
            affected_schema=affected_schema,
            trigger=trigger,
            search=search,
            sort=sort,
            status=status,
            record_id=record_id,
            affected_record_id=affected_record_id,
            offset=offset,
            limit=limit,
        )

    def count_jobs(
        self,
        status: str | None = None,
        record_id: str | None = None,
        affected_record_id: str | None = None,
        affected_schema: str | None = None,
        trigger: str | None = None,
        search: str | None = None,
        workflow: str | None = None,
        where: Any = None,
    ) -> int:
        return self._repo.count(
            where=_parsed(where),
            workflow=workflow,
            trigger=trigger,
            search=search,
            status=status,
            record_id=record_id,
            affected_record_id=affected_record_id,
            affected_schema=affected_schema,
        )

    def run_ids(self, where: Any, limit: int = 1000) -> list[uuid.UUID]:
        """Ids of every run a filter matches (newest first, at most `limit`)."""
        return self._repo.ids_matching(_parsed(where), limit)

    def failure_groups(self, where: Any = None) -> list[dict]:
        """Failed runs a filter matches, grouped by workflow and what went wrong."""
        return self._repo.failure_groups(_parsed(where))

    def get_job(self, job_id: uuid.UUID) -> WorkflowJobDTO | None:
        return self._repo.get_by_id(job_id)

    def count_active_for_workflow(self, workflow_name: str) -> int:
        """Pending/running jobs currently queued against this workflow name."""
        return self._repo.count_active_for_workflow(workflow_name)

    def failure_counts_by_plugin(self) -> dict[str, int]:
        """Failed step-execution count per plugin, most failures first."""
        counts = self._repo.failure_counts_by_plugin()
        assert isinstance(counts, dict)  # no bucket passed -> always the flat form
        return counts
