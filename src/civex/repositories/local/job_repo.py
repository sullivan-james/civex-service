from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import String, and_, cast, func, or_, select, update
from sqlalchemy.orm import Session, joinedload, selectinload

from civex.db.models import (
    JobAffectedRecord,
    JobAffectedSchema,
    Record,
    Schema,
    StepExecution,
    WorkflowJob,
)
from civex.domain.dtos import WorkflowJobDTO
from civex.domain.exceptions import ValidationError
from civex.domain.filters import FilterCondition, FilterGroup, FilterNode
from civex.repositories.local._dates import utc
from civex.repositories.local._jobs import bulk_delete_jobs
from civex.repositories.local._bucketing import day_bucket, rebucket
from civex.repositories.protocols import JobStatusRow, PluginFailureRow

# schema_name isn't a column (CIVEX-171) -- every query needs the record's
# schema loaded so _to_dto can resolve it via the join.
_WITH_SCHEMA = joinedload(WorkflowJob.record).joinedload(Record.schema)


# Columns a run list can be ordered by.
_SORTABLE = {
    "workflow_name": WorkflowJob.workflow_name,
    "status": WorkflowJob.status,
    "trigger": WorkflowJob.trigger,
    "created_at": WorkflowJob.created_at,
    "schema_name": (
        select(Schema.name)
        .join(Record, Record.schema_id == Schema.id)
        .where(Record.id == WorkflowJob.record_id)
        .correlate(WorkflowJob)
        .scalar_subquery()
    ),
}


def _narrow(
    q,
    status: str | None,
    trigger: str | None,
    search: str | None,
    workflow: str | None = None,
    where: FilterNode | None = None,
):
    """The run filters a person picks in the UI, shared by list and count."""
    if where is not None:
        q = q.filter(_tree(where))
    if workflow:
        q = q.filter(WorkflowJob.workflow_name == workflow)
    if status:
        q = q.filter(WorkflowJob.status == status)
    if trigger:
        q = q.filter(WorkflowJob.trigger == trigger)
    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                WorkflowJob.workflow_name.ilike(like),
                cast(WorkflowJob.error, String).ilike(like),
            )
        )
    return q


def _run_column(name: str):
    """What a run-filter field is in the database."""
    return {
        "workflow": WorkflowJob.workflow_name,
        "status": WorkflowJob.status,
        "trigger": WorkflowJob.trigger,
        "schema": _SORTABLE["schema_name"],
        "created_at": WorkflowJob.created_at,
        "finished_at": WorkflowJob.finished_at,
        "error_kind": WorkflowJob.error_details["kind"].as_string(),
        "error": cast(WorkflowJob.error, String),
        "failed_step": WorkflowJob.error_details["step"].as_string(),
        "depth": WorkflowJob.depth,
        "record": cast(WorkflowJob.record_id, String),
    }[name]


def _condition(leaf: FilterCondition):
    col = _run_column(leaf.field)
    value = leaf.value
    if leaf.field in ("created_at", "finished_at") and leaf.op != "is_null":
        value = utc(value)
    if leaf.field == "record":
        value = (
            [str(v).replace("-", "") for v in value]
            if isinstance(value, list)
            else str(value).replace("-", "")
        )
        col = func.replace(col, "-", "")
    match leaf.op:
        case "eq":
            return col == value
        case "ne":
            # Not-equal keeps runs where the column is empty, as a person means it.
            return or_(col.is_(None), col != value)
        case "gt":
            return col > value
        case "gte":
            return col >= value
        case "lt":
            return col < value
        case "lte":
            return col <= value
        case "contains":
            return col.ilike(f"%{value}%")
        case "in":
            return col.in_(value)
        case "is_null":
            return col.is_(None) if value else col.is_not(None)
    raise ValidationError(f"Unsupported operator '{leaf.op}'")


def _tree(node: FilterNode):
    if isinstance(node, FilterGroup):
        parts = [_tree(c) for c in node.conditions]
        return and_(*parts) if node.op == "and" else or_(*parts)
    return _condition(node)


def _order(sort: str | None) -> list:
    """ORDER BY terms for `column[:asc|desc]`; unknown columns are ignored.
    Newest first is always the tie-break."""
    name, _, direction = (sort or "").partition(":")
    col = _SORTABLE.get(name)
    terms = []
    if col is not None:
        terms.append(col.desc() if direction == "desc" else col.asc())
    return [*terms, WorkflowJob.created_at.desc(), WorkflowJob.id.desc()]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LocalWorkflowJobRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def enqueue(
        self,
        workflow_name: str,
        record_id: uuid.UUID,
        trigger: str,
        input_data: dict | None = None,
        depth: int = 0,
        trigger_detail: dict | None = None,
    ) -> WorkflowJobDTO:
        row = WorkflowJob(
            workflow_name=workflow_name,
            record_id=record_id,
            trigger=trigger,
            status="pending",
            input_data=input_data,
            depth=depth,
            trigger_detail=trigger_detail,
        )
        self._s.add(row)
        self._s.flush()
        return _to_dto(row)

    def claim_pending(self) -> WorkflowJobDTO | None:
        """Claim the oldest pending job by marking it running. The claim is a
        conditional UPDATE, so two workers (the server starts a drain per
        request) can't take the same job, and a job cancelled a moment ago
        isn't started."""
        while True:
            row = (
                self._s.query(WorkflowJob)
                .filter_by(status="pending")
                .order_by(WorkflowJob.created_at)
                .first()
            )
            if row is None:
                return None
            taken = (
                self._s.query(WorkflowJob)
                .filter(WorkflowJob.id == row.id, WorkflowJob.status == "pending")
                .update(
                    {"status": "running", "started_at": _now()},
                    synchronize_session=False,
                )
            )
            if taken:
                self._s.refresh(row)
                self._s.flush()
                return _to_dto(row)
            self._s.refresh(row)  # someone else got it first: look again

    def status_of(self, job_id: uuid.UUID) -> str | None:
        """A job's status read straight from the database, never from this
        session's cache: a running job asks this between steps to see whether
        someone cancelled it from another request or process."""
        return self._s.execute(
            select(WorkflowJob.status).where(WorkflowJob.id == job_id)
        ).scalar_one_or_none()

    def cancel(self, job_id: uuid.UUID, reason: str) -> WorkflowJobDTO | None:
        """Cancel a waiting or running job. A waiting one never starts; a
        running one is noticed by its worker before its next step. A job that
        already finished is left as it is. None if there is no such job."""
        self._s.execute(
            update(WorkflowJob)
            .where(
                WorkflowJob.id == job_id,
                WorkflowJob.status.in_(("pending", "running")),
            )
            .values(status="cancelled", finished_at=_now(), error=reason)
        )
        self._s.flush()
        return self.get_by_id(job_id)

    def cancel_all_active(self, reason: str) -> int:
        """Cancel every waiting and running job. How many were cancelled."""
        cancelled = (
            self._s.query(WorkflowJob)
            .filter(WorkflowJob.status.in_(("pending", "running")))
            .update(
                {"status": "cancelled", "finished_at": _now(), "error": reason},
                synchronize_session=False,
            )
        )
        self._s.flush()
        return cancelled

    def mark_cancelled(
        self,
        job_id: uuid.UUID,
        log: str | None = None,
        step_executions: list[dict] | None = None,
        affected_records: list[dict] | None = None,
    ) -> None:
        """Keep what a cancelled run got done: its log, the steps that ran, and
        the records it touched. The status stays `cancelled`."""
        row = self._s.query(WorkflowJob).filter_by(id=job_id).first()
        if row:
            self._keep_cancelled(row, log, step_executions, affected_records)
            self._s.flush()

    def _keep_cancelled(
        self,
        row: WorkflowJob,
        log: str | None,
        step_executions: list[dict] | None,
        affected_records: list[dict] | None,
    ) -> None:
        row.status = "cancelled"
        row.finished_at = row.finished_at or _now()
        row.log = log
        row.affected_records = affected_records or None
        _replace_step_executions(self._s, row.id, step_executions)
        _replace_affected_schemas(self._s, row.id, affected_records)
        _replace_affected_records(self._s, row.id, affected_records)

    def mark_completed(
        self,
        job_id: uuid.UUID,
        log: str | None = None,
        step_executions: list[dict] | None = None,
        affected_records: list[dict] | None = None,
    ) -> None:
        row = self._s.query(WorkflowJob).filter_by(id=job_id).first()
        if row and row.status == "cancelled":
            # Cancelled while its last step ran: it stays cancelled.
            self._keep_cancelled(row, log, step_executions, affected_records)
            self._s.flush()
        elif row:
            row.status = "completed"
            row.finished_at = _now()
            row.log = log
            row.affected_records = affected_records or None
            _replace_step_executions(self._s, job_id, step_executions)
            _replace_affected_schemas(self._s, job_id, affected_records)
            _replace_affected_records(self._s, job_id, affected_records)
            self._s.flush()

    def mark_failed(
        self,
        job_id: uuid.UUID,
        error_details: dict,
        log: str | None = None,
        step_executions: list[dict] | None = None,
        affected_records: list[dict] | None = None,
    ) -> None:
        row = self._s.query(WorkflowJob).filter_by(id=job_id).first()
        if row and row.status == "cancelled":
            self._keep_cancelled(row, log, step_executions, affected_records)
            self._s.flush()
        elif row:
            row.status = "failed"
            row.finished_at = _now()
            # `error` and `error_details["message"]` are the same string --
            # writing both here, in the one place a job is marked failed, is
            # what keeps them from disagreeing (CIVEX-171).
            row.error = error_details["message"][:2000]
            row.error_details = error_details
            row.log = log
            # A failed run may still have created/updated records before the
            # step that failed -- same partial-progress contract as
            # step_executions, so the audit trail doesn't hide real writes.
            row.affected_records = affected_records or None
            _replace_step_executions(self._s, job_id, step_executions)
            _replace_affected_schemas(self._s, job_id, affected_records)
            _replace_affected_records(self._s, job_id, affected_records)
            self._s.flush()

    def list_all(
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
        where: FilterNode | None = None,
    ) -> list[WorkflowJobDTO]:
        q = self._s.query(WorkflowJob).options(
            selectinload(WorkflowJob.steps), _WITH_SCHEMA
        )
        q = _narrow(q, status, trigger, search, workflow, where)
        if record_id:
            try:
                q = q.filter_by(record_id=uuid.UUID(record_id))
            except ValueError:
                return []
        if affected_schema:
            q = q.filter(_touches_schema(affected_schema))
        q = q.order_by(*_order(sort))
        if affected_record_id:
            touched = _touches_record(affected_record_id)
            if touched is None:
                return []
            q = q.filter(touched)
        q = q.offset(offset)
        if limit is not None:
            q = q.limit(limit)
        return [_to_dto(r) for r in q.all()]

    def count(
        self,
        status: str | None = None,
        record_id: str | None = None,
        affected_record_id: str | None = None,
        affected_schema: str | None = None,
        trigger: str | None = None,
        search: str | None = None,
        workflow: str | None = None,
        where: FilterNode | None = None,
    ) -> int:
        q = _narrow(
            self._s.query(WorkflowJob), status, trigger, search, workflow, where
        )
        if affected_schema:
            q = q.filter(_touches_schema(affected_schema))
        if record_id:
            try:
                q = q.filter_by(record_id=uuid.UUID(record_id))
            except ValueError:
                return 0
        if affected_record_id:
            touched = _touches_record(affected_record_id)
            if touched is None:
                return 0
            q = q.filter(touched)
        return q.count()

    def _finished_before(self, before: datetime) -> list:
        """A run that is over (never one pending or running) and older than
        `before`, by when it finished, or was queued if it never says."""
        return [
            WorkflowJob.status.in_(("completed", "failed", "cancelled")),
            func.coalesce(WorkflowJob.finished_at, WorkflowJob.created_at) < before,
        ]

    def count_finished_before(self, before: datetime) -> tuple[int, int]:
        """(runs, step logs) `delete_finished_before` would remove."""
        criteria = self._finished_before(before)
        runs = self._s.query(WorkflowJob).filter(*criteria).count()
        job_ids = select(WorkflowJob.id).where(*criteria)
        steps = (
            self._s.query(StepExecution)
            .filter(StepExecution.job_id.in_(job_ids))
            .count()
        )
        return runs, steps

    def delete_finished_before(self, before: datetime) -> int:
        """Remove finished runs older than `before`, with their step logs."""
        criteria = self._finished_before(before)
        runs = self._s.query(WorkflowJob).filter(*criteria).count()
        bulk_delete_jobs(self._s, *criteria)
        self._s.expire_all()
        return runs

    def delete_jobs(self, ids: list[uuid.UUID]) -> int:
        """Remove these runs, whatever their state, with their step logs. How
        many there were."""
        if not ids:
            return 0
        runs = 0
        # In chunks: SQLite allows only so many parameters in one statement.
        for start in range(0, len(ids), 500):
            criteria = [WorkflowJob.id.in_(ids[start : start + 500])]
            runs += self._s.query(WorkflowJob).filter(*criteria).count()
            bulk_delete_jobs(self._s, *criteria)
        self._s.expire_all()
        return runs

    def ids_matching(
        self, where: FilterNode | None, limit: int | None, search: str | None = None
    ) -> list[uuid.UUID]:
        """Ids of the runs a filter (and search) matches, newest first, at
        most `limit` (None: all of them)."""
        q = _narrow(self._s.query(WorkflowJob.id), None, None, search, None, where)
        return [r[0] for r in q.order_by(*_order(None)).limit(limit).all()]

    def failure_groups(self, where: FilterNode | None) -> list[dict]:
        """The failed runs a filter matches, grouped by what went wrong: workflow,
        failure type and message, with how many and when last. Most first."""
        kind = WorkflowJob.error_details["kind"].as_string()
        step = WorkflowJob.error_details["step"].as_string()
        q = _narrow(
            self._s.query(
                WorkflowJob.workflow_name,
                kind,
                step,
                cast(WorkflowJob.error, String),
                func.count(WorkflowJob.id),
                func.max(WorkflowJob.created_at),
            ),
            "failed",
            None,
            None,
            None,
            where,
        )
        rows = (
            q.group_by(
                WorkflowJob.workflow_name, kind, step, cast(WorkflowJob.error, String)
            )
            .order_by(
                func.count(WorkflowJob.id).desc(),
                func.max(WorkflowJob.created_at).desc(),
            )
            .limit(200)
            .all()
        )
        return [
            {
                "workflow": r[0],
                "kind": r[1],
                "step": r[2],
                "message": r[3],
                "count": r[4],
                "last_at": r[5],
            }
            for r in rows
        ]

    def batch_stats(self) -> dict | None:
        """How far through the current stretch of work the queue is, or None when
        it is idle. The stretch is every run that was queued while something was
        still waiting or running -- so a bulk start of 50 is 50 from the first
        poll, and a run that ended and was followed straight by another counts
        with it -- and it ends when the queue empties. Worked out from the runs'
        own timestamps; nothing is stored."""
        active = (
            self._s.query(func.count(WorkflowJob.id), func.min(WorkflowJob.created_at))
            .filter(WorkflowJob.status.in_(("pending", "running")))
            .one()
        )
        if not active[0]:
            return None
        start = active[1]
        horizon = _now() - timedelta(days=1)
        finished = (
            self._s.query(
                WorkflowJob.created_at, WorkflowJob.finished_at, WorkflowJob.status
            )
            .filter(
                WorkflowJob.finished_at.is_not(None), WorkflowJob.finished_at >= horizon
            )
            .order_by(WorkflowJob.finished_at.desc())
            .limit(20000)
            .all()
        )
        included: set[int] = set()
        grew = True
        while grew:
            grew = False
            for i, (created, ended, _) in enumerate(finished):
                if i not in included and ended >= start:
                    included.add(i)
                    start = min(start, created)
                    grew = True
        done = {"completed": 0, "failed": 0, "cancelled": 0}
        for i in included:
            done[finished[i][2]] = done.get(finished[i][2], 0) + 1
        return {
            "active": active[0],
            "started_at": start,
            "completed": done["completed"],
            "failed": done["failed"],
            "cancelled": done["cancelled"],
            "total": active[0] + len(included),
        }

    def get_by_id(self, job_id: uuid.UUID) -> WorkflowJobDTO | None:
        row = (
            self._s.query(WorkflowJob)
            .options(selectinload(WorkflowJob.steps), _WITH_SCHEMA)
            .filter_by(id=job_id)
            .first()
        )
        return _to_dto(row) if row else None

    def count_active_for_workflow(self, workflow_name: str) -> int:
        """Pending or running jobs queued against this workflow name -- these
        would fail to find their workflow definition mid-run if the file
        were deleted out from under them."""
        return (
            self._s.query(WorkflowJob)
            .filter_by(workflow_name=workflow_name)
            .filter(WorkflowJob.status.in_(("pending", "running")))
            .count()
        )

    def failure_counts_by_plugin(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        bucket: str | None = None,
    ) -> dict[str, int] | list[PluginFailureRow]:
        """Number of failed step executions per plugin -- the aggregate query
        the JSON blob made expensive (CIVEX-170): this is a GROUP BY on a
        plain column instead of a full scan parsing every job's JSON.

        With `bucket` left as None (the original call shape, still used by
        `civex worker stats`), returns the all-time flat `plugin -> count`
        dict, optionally scoped to `[start, end)`. Pass a bucket size
        ("day"/"week"/"month") to get the same counts broken into a time
        series instead, for the analytics endpoint.
        """
        day = day_bucket(WorkflowJob.created_at)
        q = (
            self._s.query(day, StepExecution.plugin, func.count(StepExecution.id))
            .join(WorkflowJob, StepExecution.job_id == WorkflowJob.id)
            .filter(StepExecution.status == "failed")
        )
        if start is not None:
            q = q.filter(WorkflowJob.created_at >= start)
        if end is not None:
            q = q.filter(WorkflowJob.created_at < end)
        rows = q.group_by(day, StepExecution.plugin).all()
        if bucket is None:
            totals: dict[str, int] = {}
            for _, plugin, count in rows:
                totals[plugin] = totals.get(plugin, 0) + count
            return dict(sorted(totals.items(), key=lambda kv: kv[1], reverse=True))
        return rebucket([(d, plugin, count) for d, plugin, count in rows], bucket)

    def status_counts_by_period(
        self,
        start: datetime | None,
        end: datetime | None,
        workflow_name: str | None,
        trigger: str | None,
        status: str | None,
    ) -> list[JobStatusRow]:
        """Job counts per day, broken out by status -- backs the job-status
        trend widget. Filters directly on `workflow_jobs` columns, no join
        needed."""
        day = day_bucket(WorkflowJob.created_at)
        q = self._s.query(day, WorkflowJob.status, func.count(WorkflowJob.id))
        if start is not None:
            q = q.filter(WorkflowJob.created_at >= start)
        if end is not None:
            q = q.filter(WorkflowJob.created_at < end)
        if workflow_name is not None:
            q = q.filter(WorkflowJob.workflow_name == workflow_name)
        if trigger is not None:
            q = q.filter(WorkflowJob.trigger == trigger)
        if status is not None:
            q = q.filter(WorkflowJob.status == status)
        rows = q.group_by(day, WorkflowJob.status).order_by(day).all()
        return [(d, s, count) for d, s, count in rows]

    def trigger_counts(
        self,
        start: datetime | None,
        end: datetime | None,
        workflow_name: str | None,
        status: str | None,
        trigger: str | None,
    ) -> list[tuple[str, int]]:
        """Job counts grouped by trigger type -- backs the trigger-breakdown
        widget. Filters directly on `workflow_jobs` columns, no join
        needed."""
        q = self._s.query(WorkflowJob.trigger, func.count(WorkflowJob.id))
        if start is not None:
            q = q.filter(WorkflowJob.created_at >= start)
        if end is not None:
            q = q.filter(WorkflowJob.created_at < end)
        if workflow_name is not None:
            q = q.filter(WorkflowJob.workflow_name == workflow_name)
        if status is not None:
            q = q.filter(WorkflowJob.status == status)
        if trigger is not None:
            q = q.filter(WorkflowJob.trigger == trigger)
        rows = q.group_by(WorkflowJob.trigger).all()
        return [(t, count) for t, count in rows]

    def step_durations(
        self,
        start: datetime | None,
        end: datetime | None,
        plugin: str | None,
        status: str | None,
    ) -> list[float]:
        """Raw `duration_seconds` values for step executions matching the
        filters -- the analytics service turns this into avg/min/max/
        percentile stats. Reads the column directly (CIVEX-170 normalized it
        out of the old per-job JSON blob), rather than parsing JSON per row."""
        q = (
            self._s.query(StepExecution.duration_seconds)
            .join(WorkflowJob, StepExecution.job_id == WorkflowJob.id)
            .filter(StepExecution.duration_seconds.isnot(None))
        )
        if plugin is not None:
            q = q.filter(StepExecution.plugin == plugin)
        if status is not None:
            q = q.filter(StepExecution.status == status)
        if start is not None:
            q = q.filter(WorkflowJob.created_at >= start)
        if end is not None:
            q = q.filter(WorkflowJob.created_at < end)
        return [d for (d,) in q.all()]


def _touches_schema(schema_name: str):
    """Indexed membership test against job_affected_schemas."""
    return WorkflowJob.id.in_(
        select(JobAffectedSchema.job_id)
        .join(Schema, Schema.id == JobAffectedSchema.schema_id)
        .where(Schema.name == schema_name)
    )


def _replace_affected_schemas(
    session: Session, job_id: uuid.UUID, affected_records: list[dict] | None
) -> None:
    """Rewrites this job's schema links from the schema names recorded in
    its affected_records entries."""
    session.query(JobAffectedSchema).filter_by(job_id=job_id).delete(
        synchronize_session=False
    )
    names = {
        e["schema_name"]
        for e in affected_records or []
        if isinstance(e, dict) and e.get("schema_name")
    }
    if not names:
        return
    ids = [
        sid for (sid,) in session.query(Schema.id).filter(Schema.name.in_(names)).all()
    ]
    session.add_all(JobAffectedSchema(job_id=job_id, schema_id=sid) for sid in ids)


def _touches_record(record_id: str):
    """Indexed membership test against job_affected_records; None for a
    string that is not a record id (nothing can match it)."""
    try:
        rid = uuid.UUID(record_id)
    except ValueError:
        return None
    return WorkflowJob.id.in_(
        select(JobAffectedRecord.job_id).where(JobAffectedRecord.record_id == rid)
    )


def _replace_affected_records(
    session: Session, job_id: uuid.UUID, affected_records: list[dict] | None
) -> None:
    """Rewrites this job's record links from its affected_records entries."""
    session.query(JobAffectedRecord).filter_by(job_id=job_id).delete(
        synchronize_session=False
    )
    ids: set[uuid.UUID] = set()
    for entry in affected_records or []:
        if not isinstance(entry, dict):
            continue
        try:
            ids.add(uuid.UUID(str(entry.get("record_id"))))
        except ValueError:
            continue
    session.add_all(JobAffectedRecord(job_id=job_id, record_id=rid) for rid in ids)


def _replace_step_executions(
    session: Session, job_id: uuid.UUID, step_executions: list[dict] | None
) -> None:
    """Overwrites this job's step_executions rows -- mirrors the old
    `row.step_executions = step_executions` assignment now that the per-step
    records live in their own table (CIVEX-170). `mark_completed`/`mark_failed`
    are each only ever called once per job, but delete-then-insert keeps this
    safe to call again."""
    session.query(StepExecution).filter_by(job_id=job_id).delete()
    if not step_executions:
        return
    for position, step in enumerate(step_executions):
        session.add(
            StepExecution(
                job_id=job_id,
                position=position,
                step_id=step["step_id"],
                plugin=step["plugin"],
                status=step["status"],
                duration_seconds=step.get("duration_seconds"),
                error=step.get("error"),
                error_details=step.get("error_details"),
                inputs=step.get("inputs"),
                outputs=step.get("outputs"),
                depends_on=step.get("depends_on"),
            )
        )


def _to_dto(row: WorkflowJob) -> WorkflowJobDTO:
    step_executions = (
        [
            {
                "step_id": s.step_id,
                "plugin": s.plugin,
                "status": s.status,
                "inputs": s.inputs,
                "outputs": s.outputs,
                "duration_seconds": s.duration_seconds,
                "error": s.error,
                "depends_on": s.depends_on,
            }
            for s in row.steps
        ]
        if row.steps
        else None
    )
    return WorkflowJobDTO(
        id=row.id,
        workflow_name=row.workflow_name,
        record_id=row.record_id,
        schema_name=row.record.schema.name,
        trigger=row.trigger,
        status=row.status,
        error=row.error,
        error_details=row.error_details,
        log=row.log,
        input_data=row.input_data,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        depth=row.depth,
        trigger_detail=row.trigger_detail,
        step_executions=step_executions,
        affected_records=row.affected_records,
    )
