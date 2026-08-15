from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from civex.context import AppContext
from civex.domain.dtos import AnalyticsFilters
from civex.domain.exceptions import NotFoundError
from civex.server.deps import get_ctx
from civex.server.models import (
    AiTokenUsageResponse,
    AuditEventCountsResponse,
    AuditEventPointResponse,
    JobDurationStatsResponse,
    JobStatusCountsResponse,
    JobStatusPointResponse,
    PluginFailureCountsResponse,
    PluginFailurePointResponse,
    RecordCountResponse,
    RecordCountsResponse,
    RecordGrowthPointResponse,
    RecordGrowthResponse,
    TokenUsageBucketResponse,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


def analytics_filters(
    start: datetime | None = Query(
        default=None,
        description="Inclusive lower bound (UTC) on the endpoint's primary timestamp column.",
    ),
    end: datetime | None = Query(
        default=None, description="Exclusive upper bound (UTC)."
    ),
    bucket: Literal["day", "week", "month"] = Query(
        default="day",
        description="Time-bucket size for time-series endpoints. Ignored by "
        "current-state endpoints (e.g. record counts).",
    ),
    dataset: str | None = Query(default=None, description="Dataset name to scope to."),
    schema: str | None = Query(default=None, description="Schema name to scope to."),
    workflow_id: str | None = Query(
        default=None,
        description="Workflow name to scope to -- workflows are identified by "
        "name, not a separate id.",
    ),
    plugin_id: str | None = Query(
        default=None,
        description="Plugin id to scope to, e.g. 'civex.load_file'.",
    ),
    status: str | None = Query(
        default=None, description="Job or step status to scope to."
    ),
    trigger: str | None = Query(
        default=None,
        description="Workflow trigger to scope to: record_created, "
        "record_updated, or manual.",
    ),
) -> AnalyticsFilters:
    """The one query-param contract shared by every endpoint below (see
    `AnalyticsFilters`). Each endpoint's docstring says which of these
    fields it actually applies -- the rest are accepted but ignored, so a
    single filter bar can drive every widget without per-widget params."""
    return AnalyticsFilters(
        start=start,
        end=end,
        bucket=bucket,
        dataset=dataset,
        schema=schema,
        workflow_id=workflow_id,
        plugin_id=plugin_id,
        status=status,
        trigger=trigger,
    )


@router.get("/records/counts", response_model=RecordCountsResponse)
def record_counts(
    filters: AnalyticsFilters = Depends(analytics_filters),
    ctx: AppContext = Depends(get_ctx),
):
    """Current record totals by dataset and schema -- a snapshot, not a time
    series. Applies the `dataset` and `schema` filters; the rest of the
    shared filter contract is ignored here."""
    try:
        items = ctx.analytics_svc.record_counts(filters)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    return RecordCountsResponse(items=[RecordCountResponse.from_dto(i) for i in items])


@router.get("/records/growth", response_model=RecordGrowthResponse)
def record_growth(
    filters: AnalyticsFilters = Depends(analytics_filters),
    ctx: AppContext = Depends(get_ctx),
):
    """Record creation counts over time, broken out by dataset and schema.
    Applies `start`, `end`, `bucket`, `dataset`, `schema`."""
    try:
        items = ctx.analytics_svc.record_growth(filters)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    return RecordGrowthResponse(
        bucket=filters.bucket,
        items=[RecordGrowthPointResponse.from_dto(i) for i in items],
    )


@router.get("/jobs/status", response_model=JobStatusCountsResponse)
def job_status_counts(
    filters: AnalyticsFilters = Depends(analytics_filters),
    ctx: AppContext = Depends(get_ctx),
):
    """Workflow job counts over time, broken out by status. Applies `start`,
    `end`, `bucket`, `workflow_id`, `trigger`, `status`."""
    items = ctx.analytics_svc.job_status_counts(filters)
    return JobStatusCountsResponse(
        bucket=filters.bucket,
        items=[JobStatusPointResponse.from_dto(i) for i in items],
    )


@router.get("/jobs/duration", response_model=JobDurationStatsResponse)
def job_duration_stats(
    filters: AnalyticsFilters = Depends(analytics_filters),
    ctx: AppContext = Depends(get_ctx),
):
    """Step execution duration distribution (count, avg, min, max, p50,
    p95), in seconds. Applies `start`, `end`, `plugin_id`, `status`
    (matched against the step's own status, not the parent job's)."""
    stats = ctx.analytics_svc.job_duration_stats(filters)
    return JobDurationStatsResponse.from_dto(stats)


@router.get("/jobs/failures-by-plugin", response_model=PluginFailureCountsResponse)
def plugin_failure_counts(
    filters: AnalyticsFilters = Depends(analytics_filters),
    ctx: AppContext = Depends(get_ctx),
):
    """Failed step-execution counts over time, broken out by plugin --
    generalizes the aggregate `civex worker stats` uses with a date range
    and bucket size. Applies `start`, `end`, `bucket`, `plugin_id`."""
    items = ctx.analytics_svc.plugin_failure_counts(filters)
    return PluginFailureCountsResponse(
        bucket=filters.bucket,
        items=[PluginFailurePointResponse.from_dto(i) for i in items],
    )


@router.get("/audit/events", response_model=AuditEventCountsResponse)
def audit_event_counts(
    filters: AnalyticsFilters = Depends(analytics_filters),
    ctx: AppContext = Depends(get_ctx),
):
    """Audit log entry counts over time, broken out by action and
    entity_type. Applies `start`, `end`, `bucket`."""
    items = ctx.analytics_svc.audit_event_counts(filters)
    return AuditEventCountsResponse(
        bucket=filters.bucket,
        items=[AuditEventPointResponse.from_dto(i) for i in items],
    )


@router.get("/ai/usage", response_model=AiTokenUsageResponse)
def ai_token_usage(
    filters: AnalyticsFilters = Depends(analytics_filters),
    provider: str | None = Query(
        default=None, description="AI provider to scope to, e.g. 'anthropic'."
    ),
    model: str | None = Query(
        default=None, description="AI model to scope to, e.g. 'claude-sonnet-5'."
    ),
    ctx: AppContext = Depends(get_ctx),
):
    """AI provider token usage over time, broken out by provider and model.
    Applies `start`, `end`, `bucket`, plus this endpoint's own `provider`
    and `model` params -- not part of the shared filter contract since no
    other endpoint has a use for them."""
    items = ctx.analytics_svc.ai_token_usage(filters, provider=provider, model=model)
    return AiTokenUsageResponse(
        bucket=filters.bucket,
        items=[TokenUsageBucketResponse.from_dto(i) for i in items],
    )
