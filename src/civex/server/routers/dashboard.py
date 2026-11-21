"""The project's Analytics page: one shared, ordered list of cards."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from civex.context import AppContext
from civex.domain.dashboard import WIDGETS
from civex.domain.dtos import DashboardPageDTO
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.server.deps import get_ctx
from civex.server.models import ViewResponse

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class DashboardCard(BaseModel):
    id: str = Field(description="The card's own id, unique on the page.")
    kind: Literal["analysis", "widget"] = Field(
        description="A saved analysis, or a built-in widget."
    )
    size: Literal["small", "wide"] = Field(
        default="small", description="Half the page wide, or all of it."
    )
    title: str | None = Field(
        default=None,
        description="A title of its own; None shows the analysis's or widget's name.",
    )
    view: str | None = Field(
        default=None, description="An analysis card's saved view, by id."
    )
    widget: str | None = Field(
        default=None,
        description="A widget card's widget: " + ", ".join(WIDGETS) + ".",
    )


class DashboardCardResponse(DashboardCard):
    analysis: ViewResponse | None = Field(
        default=None,
        description="The saved view an analysis card names; None once it has "
        "been deleted (the card stays until someone removes it).",
    )


class DashboardResponse(BaseModel):
    cards: list[DashboardCardResponse] = Field(description="The cards, in order.")
    edited: bool = Field(
        description="Whether anyone has changed the page yet; until then it "
        "shows every built-in widget."
    )
    widgets: dict[str, str] = Field(
        description="Every built-in widget a card can show, by key, with its name."
    )

    @classmethod
    def from_dto(cls, dto: DashboardPageDTO) -> DashboardResponse:
        return cls(
            cards=[
                DashboardCardResponse(
                    **c.card.to_dict(),
                    analysis=ViewResponse.from_dto(c.view) if c.view else None,
                )
                for c in dto.cards
            ],
            edited=dto.edited,
            widgets={k: name for k, (name, _) in WIDGETS.items()},
        )


class SaveDashboardRequest(BaseModel):
    cards: list[DashboardCard] = Field(
        description="Every card the page is to hold, in order (this replaces "
        "the list). A new analysis card must name a saved view with a summary."
    )


@router.get("", response_model=DashboardResponse)
def get_dashboard(ctx: AppContext = Depends(get_ctx)):
    """The Analytics page: its cards in order, each analysis with its saved
    view. Shared by everyone in the project."""
    return DashboardResponse.from_dto(ctx.dashboard_svc.page())


@router.put("", response_model=DashboardResponse)
def save_dashboard(body: SaveDashboardRequest, ctx: AppContext = Depends(get_ctx)):
    """Replace the Analytics page's cards (add, remove, reorder, resize in one
    request). Needs the right to write records somewhere, like a saved
    filter; the change is one entry in Activity and syncs to every device."""
    try:
        page = ctx.dashboard_svc.save(
            [c.model_dump(exclude_none=True) for c in body.cards]
        )
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return DashboardResponse.from_dto(page)
