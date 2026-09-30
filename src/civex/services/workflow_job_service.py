from __future__ import annotations

import logging
import uuid
from pathlib import Path

from civex.domain.dtos import ErrorEnvelope, RecordDTO, WorkflowJobDTO
from civex.repositories.protocols import WorkflowJobRepository
from civex.workflows.definition import WorkflowDef, load_workflow

log = logging.getLogger(__name__)

MAX_JOB_DEPTH = 10


class WorkflowJobService:
    def __init__(self, repo: WorkflowJobRepository, civex_dir: Path) -> None:
        self._repo = repo
        self._civex_dir = civex_dir

    def _load_workflows(self) -> list[WorkflowDef]:
        wf_dir = self._civex_dir / "workflows"
        if not wf_dir.exists():
            return []
        result: list[WorkflowDef] = []
        for path in sorted(wf_dir.glob("*.yaml")) + sorted(wf_dir.glob("*.yml")):
            try:
                result.append(load_workflow(path))
            except Exception as e:
                log.warning("Skipping unparseable workflow file %s: %s", path, e)
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

    def trigger_for_record(
        self,
        record: RecordDTO,
        event: str,
        changed_fields: set[str] | None = None,
        depth: int = 0,
    ) -> list[WorkflowJobDTO]:
        """Enqueue jobs for every workflow whose trigger matches this event + schema.

        For record_updated, if the trigger declares a fields list and changed_fields is
        provided, only enqueue if at least one watched field actually changed.

        depth tracks how many workflow-triggered-by-workflow hops deep this call is.
        Jobs at or above MAX_JOB_DEPTH are silently dropped to break runaway chains.
        """
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
            job = self._repo.enqueue(wf.name, record.id, event, depth=depth)
            jobs.append(job)
        return jobs

    def enqueue_manual(
        self,
        workflow_name: str,
        record: RecordDTO,
        input_data: dict | None = None,
    ) -> WorkflowJobDTO:
        return self._repo.enqueue(
            workflow_name,
            record.id,
            "manual",
            input_data=input_data,
        )

    def claim_pending(self) -> WorkflowJobDTO | None:
        return self._repo.claim_pending()

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
    ) -> list[WorkflowJobDTO]:
        return self._repo.list_all(
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
    ) -> int:
        return self._repo.count(
            status=status, record_id=record_id, affected_record_id=affected_record_id
        )

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
