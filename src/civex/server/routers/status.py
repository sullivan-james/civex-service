from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text

from civex.context import AppContext
from civex.domain.features import FEATURES
from civex.project import Project
from civex.server.deps import current_project, get_ctx
from civex.server.models import DBStatusResponse

router = APIRouter(prefix="/status", tags=["status"])


@router.get("/db", response_model=DBStatusResponse)
def db_status(ctx: AppContext = Depends(get_ctx)) -> DBStatusResponse:
    """
    Tests the database connection with a live round-trip. A bare
    Depends(get_ctx) isn't enough on its own — SQLAlchemy Sessions connect
    lazily, so building the context doesn't prove a query would actually
    succeed. A failure here is caught by get_ctx() the same as any other
    route's query (auto-recovers a docker-managed container when possible).
    """
    ctx._session.execute(text("SELECT 1"))
    return DBStatusResponse(ok=True)


class FeaturesResponse(BaseModel):
    features: list[str] = Field(
        description="What this server does for this project, by name "
        "(see `all`). The app hides what isn't here."
    )
    all: dict[str, str] = Field(
        description="Every feature a civex server may offer, with what it means."
    )


@router.get("/features", response_model=FeaturesResponse)
def features(project: Project = Depends(current_project)) -> FeaturesResponse:
    """What this server does for this project: drives, workflows on this
    machine, a terminal, updates and so on. A hosted project has fewer; the
    app reads this once and shows only what applies."""
    return FeaturesResponse(features=sorted(project.features), all=dict(FEATURES))
