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
class TriggerBreakdownPoint:
    trigger: str
    count: int


@dataclass
class DurationStats:
    count: int
    avg_seconds: float | None
    min_seconds: float | None
    max_seconds: float | None
    p50_seconds: float | None
    p90_seconds: float | None
    p99_seconds: float | None


@dataclass
class DurationHistogramBin:
    label: str
    count: int


@dataclass
class DurationPercentileMarker:
    label: str
    bin_label: str


@dataclass
class DurationDistribution:
    stats: DurationStats
    bins: list[DurationHistogramBin]
    percentile_markers: list[DurationPercentileMarker]


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

    def job_duration_stats(self, filters: AnalyticsFilters) -> DurationDistribution:
        """Step execution duration distribution: summary stats
        (count/avg/min/max/p50/p90/p99), a histogram of counts by duration
        bucket, and which bucket each percentile falls in (for a chart to
        draw as a reference line). Applies `start`, `end`, `plugin_id`
        (matched against `StepExecution.plugin`), `status` (matched against
        `StepExecution.status`, e.g. "success"/"failed"/"skipped")."""
        durations = self._jobs.step_durations(
            filters.start, filters.end, filters.plugin_id, filters.status
        )
        ordered = sorted(durations)
        return DurationDistribution(
            stats=_duration_stats(ordered),
            bins=_duration_histogram(ordered),
            percentile_markers=_percentile_markers(ordered),
        )

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

    def trigger_breakdown(
        self, filters: AnalyticsFilters
    ) -> list[TriggerBreakdownPoint]:
        """Job counts grouped by trigger type (record_created /
        record_updated / manual) -- a snapshot over the filtered range, not
        a time series. Applies `start`, `end`, `workflow_id`, `status`,
        `trigger` (narrows to a single trigger)."""
        rows = self._jobs.trigger_counts(
            filters.start,
            filters.end,
            filters.workflow_id,
            filters.status,
            filters.trigger,
        )
        return [TriggerBreakdownPoint(trigger=t, count=c) for t, c in rows]

    def audit_event_counts(self, filters: AnalyticsFilters) -> list[AuditEventPoint]:
        """Audit log entries over time, by action + entity_type. Applies
        `start`, `end`, `bucket`, `entity_type`, `action`. There is no actor/
        user field on `AuditLog` (see `db/models.py`), so per-user attribution
        isn't available here -- out of scope for this widget until auth/
        multi-user tracking lands."""
        rows = self._audit.event_counts_by_period(
            filters.start, filters.end, filters.entity_type, filters.action
        )
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


def _duration_stats(ordered: list[float]) -> DurationStats:
    """`ordered` must already be sorted ascending -- callers share it with
    `_duration_histogram`/`_percentile_markers` rather than each re-sorting."""
    if not ordered:
        return DurationStats(
            count=0,
            avg_seconds=None,
            min_seconds=None,
            max_seconds=None,
            p50_seconds=None,
            p90_seconds=None,
            p99_seconds=None,
        )
    return DurationStats(
        count=len(ordered),
        avg_seconds=sum(ordered) / len(ordered),
        min_seconds=ordered[0],
        max_seconds=ordered[-1],
        p50_seconds=_percentile(ordered, 0.50),
        p90_seconds=_percentile(ordered, 0.90),
        p99_seconds=_percentile(ordered, 0.99),
    )


def _percentile(ordered: list[float], p: float) -> float:
    """Nearest-rank percentile over an already-sorted list -- avoids a
    numpy/pandas dependency for four numbers."""
    index = min(len(ordered) - 1, max(0, round(p * (len(ordered) - 1))))
    return ordered[index]


# Bucket edges (in seconds) for the duration histogram -- open-ended above
# the last edge. Fixed rather than derived from the data's own min/max so a
# bucket's meaning (and its position on screen) doesn't shift from one
# filtered view to the next.
_DURATION_BIN_EDGES: list[tuple[float, float | None, str]] = [
    (0, 1, "0-1s"),
    (1, 2, "1-2s"),
    (2, 5, "2-5s"),
    (5, 10, "5-10s"),
    (10, 30, "10-30s"),
    (30, None, "30s+"),
]


def _bin_label(seconds: float) -> str:
    for _, hi, label in _DURATION_BIN_EDGES:
        if hi is None or seconds < hi:
            return label
    return _DURATION_BIN_EDGES[-1][2]  # pragma: no cover -- last edge is open-ended


def _duration_histogram(ordered: list[float]) -> list[DurationHistogramBin]:
    counts = {label: 0 for _, _, label in _DURATION_BIN_EDGES}
    for seconds in ordered:
        counts[_bin_label(seconds)] += 1
    return [
        DurationHistogramBin(label=label, count=counts[label])
        for _, _, label in _DURATION_BIN_EDGES
    ]


def _percentile_markers(ordered: list[float]) -> list[DurationPercentileMarker]:
    if not ordered:
        return []
    return [
        DurationPercentileMarker(
            label=label, bin_label=_bin_label(_percentile(ordered, p))
        )
        for label, p in (("p50", 0.50), ("p90", 0.90), ("p99", 0.99))
    ]
