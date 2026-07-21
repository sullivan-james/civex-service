from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from civex.context import AppContext
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.server.deps import get_ctx
from civex.server.models import LicenseResponse, PolicyResponse
from civex.services.policy_service import _find_license_text

router = APIRouter(prefix="/legal", tags=["legal"])


@router.get("/license", response_model=LicenseResponse)
def get_license() -> LicenseResponse:
    """The software's own license text -- independent of any project, so
    this doesn't go through Depends(get_ctx)."""
    return LicenseResponse(text=_find_license_text())


@router.get("/policies", response_model=list[PolicyResponse])
def list_policies(ctx: AppContext = Depends(get_ctx)) -> list[PolicyResponse]:
    """Org-authored data/governance policy documents from _civex/policies/."""
    return [
        PolicyResponse(stem=p.stem, title=p.title, content=p.content)
        for p in ctx.policy_svc.list()
    ]


@router.get("/policies/{stem}", response_model=PolicyResponse)
def get_policy(stem: str, ctx: AppContext = Depends(get_ctx)) -> PolicyResponse:
    try:
        p = ctx.policy_svc.get(stem)
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    return PolicyResponse(stem=p.stem, title=p.title, content=p.content)
