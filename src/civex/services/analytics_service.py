from __future__ import annotations

import uuid
from dataclasses import dataclass

from civex.domain.dtos import AnalyticsFilters
from civex.repositories.local._bucketing import rebucket
from civex.repositories.protocols import (
    AuditRepository,
    RecordRepository,
    WorkflowJobRepository,
)
from civex.services.ai_usage_service import AiUsageService, TokenUsageBucket
from civex.services.dataset_service import DatasetService
from civex.services.schema_service import SchemaService


@dataclass
class RecordCount:
    dataset: str
    schema: str
    count: int


@dataclass
class RecordGrowthPoint:
    bucket: str
    dataset: str
    schema: str
    count: int


@dataclass
class JobStatusPoint:
    bucket: str
    status: str
    count: int


@dataclass
class PluginFailurePoint:
    bucket: str
    plugin: str
    count: int


@dataclass
class DurationStats:
    count: int
    avg_seconds: float | None
    min_seconds: float | None
    max_seconds: float | None
    p50_seconds: float | None
    p95_seconds: float | None


@dataclass
class AuditEventPoint:
    bucket: str
    action: str
    entity_type: str
    count: int


class AnalyticsService:
    """Aggregate, filterable, time-bucketed reads over existing data -- the
    one read path every dashboard widget calls. Each method below documents
    which `AnalyticsFilters` fields it applies; unused ones are ignored
    rather than rejected, so a caller can send the same filter set to every
    endpoint uniformly.
    """

    def __init__(
        self,
        record_repo: RecordRepository,
        job_repo: WorkflowJobRepository,
        audit_repo: AuditRepository,
        ai_usage_svc: AiUsageService,
        schema_svc: SchemaService,
        dataset_svc: DatasetService,
    ) -> None:
        self._records = record_repo
        self._jobs = job_repo
        self._audit = audit_repo
        self._ai_usage = ai_usage_svc
        self._schemas = schema_svc
        self._datasets = dataset_svc

    def _dataset_id(self, name: str | None) -> uuid.UUID | None:
        return self._datasets.get(name).id if name else None

    def _schema_id(self, name: str | None) -> uuid.UUID | None:
        return self._schemas.get(name).id if name else None

    def record_counts(self, filters: AnalyticsFilters) -> list[RecordCount]:
        """Current record totals by dataset + schema. Applies `dataset`,
        `schema`. Backed by `RecordRepository.count_by_schema()`, called
        once per matching dataset -- there's no "all datasets" primitive,
        but looping keeps each call an indexed per-dataset GROUP BY rather
        than trading it for one global unfiltered scan."""
        datasets = (
            [self._datasets.get(filters.dataset)]
            if filters.dataset
            else self._datasets.list_all()
        )
        results: list[RecordCount] = []
        for ds in datasets:
            for schema_name, count in self._records.count_by_schema(ds.id).items():
                if filters.schema and schema_name != filters.schema:
                    continue
                results.append(
                    RecordCount(dataset=ds.name, schema=schema_name, count=count)
                )
        return results

    def record_growth(self, filters: AnalyticsFilters) -> list[RecordGrowthPoint]:
        """Record creation counts over time, by dataset + schema. Applies
        `start`, `end`, `bucket`, `dataset`, `schema`. Backed by
        `RecordRepository.growth_by_period()`, which uses
        `ix_records_dataset_created` when `dataset` is set."""
        rows = self._records.growth_by_period(
            self._dataset_id(filters.dataset),
            self._schema_id(filters.schema),
            filters.start,
            filters.end,
        )
        return [
            RecordGrowthPoint(bucket=b, dataset=dataset, schema=schema, count=count)
            for b, dataset, schema, count in rebucket(rows, filters.bucket)
        ]

    def job_status_counts(self, filters: AnalyticsFilters) -> list[JobStatusPoint]:
        """Job counts over time, by status. Applies `start`, `end`,
        `bucket`, `workflow_id` (matched against `WorkflowJob.workflow_name`
        -- workflows have no separate id), `trigger`, `status`."""
        rows = self._jobs.status_counts_by_period(
            filters.start,
            filters.end,
            filters.workflow_id,
            filters.trigger,
            filters.status,
        )
        return [
            JobStatusPoint(bucket=b, status=status, count=count)
            for b, status, count in rebucket(rows, filters.bucket)
        ]

    def job_duration_stats(self, filters: AnalyticsFilters) -> DurationStats:
        """Step execution duration distribution (count/avg/min/max/p50/p95).
        Applies `start`, `end`, `plugin_id` (matched against
        `StepExecution.plugin`), `status` (matched against
        `StepExecution.status`, e.g. "success"/"failed"/"skipped")."""
        durations = self._jobs.step_durations(
            filters.start, filters.end, filters.plugin_id, filters.status
        )
        return _duration_stats(durations)

    def plugin_failure_counts(
        self, filters: AnalyticsFilters
    ) -> list[PluginFailurePoint]:
        """Failed step-execution counts over time, by plugin -- the same
        aggregate `civex worker stats` uses, generalized to accept a date
        range and bucket size instead of only returning an all-time total.
        Applies `start`, `end`, `bucket`; narrows to one plugin when
        `plugin_id` is set."""
        rows = self._jobs.failure_counts_by_plugin(
            filters.start, filters.end, bucket=filters.bucket
        )
        assert isinstance(
            rows, list
        )  # bucket is always set here, never the flat-dict shape
        if filters.plugin_id:
            rows = [r for r in rows if r[1] == filters.plugin_id]
        return [
            PluginFailurePoint(bucket=b, plugin=plugin, count=count)
            for b, plugin, count in rows
        ]

    def audit_event_counts(self, filters: AnalyticsFilters) -> list[AuditEventPoint]:
        """Audit log entries over time, by action + entity_type. Applies
        `start`, `end`, `bucket`."""
        rows = self._audit.event_counts_by_period(filters.start, filters.end)
        return [
            AuditEventPoint(
                bucket=b, action=action, entity_type=entity_type, count=count
            )
            for b, action, entity_type, count in rebucket(rows, filters.bucket)
        ]

    def ai_token_usage(
        self,
        filters: AnalyticsFilters,
        provider: str | None = None,
        model: str | None = None,
    ) -> list[TokenUsageBucket]:
        """AI token usage over time, by provider + model. Applies `start`,
        `end`, `bucket`, plus this endpoint's own `provider`/`model` scoping
        params -- those two aren't part of the shared filter contract since
        no other analytics endpoint has a use for them."""
        return self._ai_usage.usage_by_period(
            filters.start, filters.end, filters.bucket, provider=provider, model=model
        )


def _duration_stats(durations: list[float]) -> DurationStats:
    if not durations:
        return DurationStats(
            count=0,
            avg_seconds=None,
            min_seconds=None,
            max_seconds=None,
            p50_seconds=None,
            p95_seconds=None,
        )
    ordered = sorted(durations)
    return DurationStats(
        count=len(ordered),
        avg_seconds=sum(ordered) / len(ordered),
        min_seconds=ordered[0],
        max_seconds=ordered[-1],
        p50_seconds=_percentile(ordered, 0.50),
        p95_seconds=_percentile(ordered, 0.95),
    )


def _percentile(ordered: list[float], p: float) -> float:
    """Nearest-rank percentile over an already-sorted list -- avoids a
    numpy/pandas dependency for four numbers."""
    index = min(len(ordered) - 1, max(0, round(p * (len(ordered) - 1))))
    return ordered[index]
