from __future__ import annotations

import uuid

from civex.domain.dtos import RecordDTO, WorkflowJobDTO
from civex.repositories.protocols import WorkflowJobRepository
from civex.services.workflow_service import WorkflowService
from civex.workflows.definition import WorkflowDef


MAX_JOB_DEPTH = 10


class WorkflowJobService:
    def __init__(
        self, repo: WorkflowJobRepository, workflow_svc: WorkflowService
    ) -> None:
        self._repo = repo
        self._workflow_svc = workflow_svc

    def find_workflow(self, name: str) -> WorkflowDef | None:
        """Match by workflow name or filename stem (with or without .yaml/.yml extension)."""
        stem = name.removesuffix(".yml").removesuffix(".yaml")
        for path, wf in self._workflow_svc.list_defs():
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
        for _path, wf in self._workflow_svc.list_defs():
            if wf.triggers is None:
                continue
            trigger_def = getattr(wf.triggers, event, None)
            if trigger_def is None or trigger_def.schema_name != record.schema_name:
                continue
            if trigger_def.fields and changed_fields is not None:
                if not any(f in changed_fields for f in trigger_def.fields):
                    continue
            job = self._repo.enqueue(
                wf.name, record.id, record.schema_name, event, depth=depth
            )
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
            record.schema_name,
            "manual",
            input_data=input_data,
        )

    def claim_pending(self) -> WorkflowJobDTO | None:
        return self._repo.claim_pending()

    def mark_completed(self, job_id: uuid.UUID, log: str | None = None) -> None:
        self._repo.mark_completed(job_id, log=log)

    def mark_failed(
        self, job_id: uuid.UUID, error: str, log: str | None = None
    ) -> None:
        self._repo.mark_failed(job_id, error, log=log)

    def list_jobs(
        self,
        status: str | None = None,
        record_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[WorkflowJobDTO]:
        return self._repo.list_all(
            status=status, record_id=record_id, offset=offset, limit=limit
        )

    def count_jobs(
        self, status: str | None = None, record_id: str | None = None
    ) -> int:
        return self._repo.count(status=status, record_id=record_id)

    def get_job(self, job_id: uuid.UUID) -> WorkflowJobDTO | None:
        return self._repo.get_by_id(job_id)
