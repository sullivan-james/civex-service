"""The Health page: what `civex doctor` checks, and its repair.

Both come from `services.health_service`, the same code the command runs.
Like the database routes this builds no context for the checks that must work
when the database lacks something. What a host has no machine for is left out
of the answer (`domain.features`), and repair needs `DB_ADMIN`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from civex.domain import features as features_
from civex.project import Project
from civex.server.deps import current_project, reads_whole_project, requires
from civex.services import health_service

router = APIRouter(
    prefix="/health", tags=["health"], dependencies=[reads_whole_project()]
)


class CheckResponse(BaseModel):
    name: str
    status: str = Field(description="ok, warn or fail")
    detail: str
    fix: str


class ProblemResponse(BaseModel):
    kind: str
    severity: str = Field(description="warn or fail")
    message: str
    fix: str
    items: list[str]


class HealthResponse(BaseModel):
    ok: bool = Field(description="No problem needs attention.")
    problems: list[ProblemResponse]
    checks: list[CheckResponse] | None = Field(
        description="The install checks; null where this server has no install to check."
    )
    data_checked: bool = Field(
        description="False when the database lacks something, so the data was not checked."
    )
    can_repair: bool = Field(description="Repair would change something here.")
    repair_offered: bool = Field(description="This server offers repair at all.")


class RepairResponse(BaseModel):
    backup: str
    added: list[str]
    health: HealthResponse


def _to_response(
    report: health_service.HealthReport, project: Project
) -> HealthResponse:
    problems = report.problems()
    offered = features_.enabled(project.features, features_.DB_ADMIN)
    return HealthResponse(
        ok=not problems,
        problems=[
            ProblemResponse(
                kind=p.kind,
                severity=p.severity,
                message=p.message,
                fix=p.fix,
                items=list(p.items),
            )
            for p in problems
        ],
        checks=None
        if report.install is None
        else [
            CheckResponse(name=c.name, status=c.status, detail=c.detail, fix=c.fix)
            for c in report.install
        ],
        data_checked=report.data_checked,
        can_repair=offered and report.repairable,
        repair_offered=offered,
    )


@router.get("", response_model=HealthResponse)
def check(project: Project = Depends(current_project)) -> HealthResponse:
    return _to_response(health_service.check_health(project), project)


@router.post(
    "/repair",
    response_model=RepairResponse,
    dependencies=[requires(features_.DB_ADMIN)],
)
def repair(project: Project = Depends(current_project)) -> RepairResponse:
    """Back the database up, then add the tables and columns it lacks.
    409 while a sync is running or when no backup could be made."""
    try:
        result = health_service.repair_database(project)
    except health_service.RepairRefused as exc:
        raise HTTPException(409, detail=str(exc))
    return RepairResponse(
        backup=str(result.backup),
        added=result.added,
        health=_to_response(health_service.check_health(project), project),
    )
