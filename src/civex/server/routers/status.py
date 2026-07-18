from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text

from civex.context import AppContext
from civex.server.deps import get_ctx
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
