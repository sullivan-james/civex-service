"""The project's Analytics page: one shared, ordered list of cards."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from civex.context import AppContext
from civex.domain.dashboard import WIDGETS
from civex.domain.dtos import DashboardPageDTO
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.server.deps import get_ctx
from civex.server.models import ChartModel

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class CardRecords(BaseModel):
    """The records a chart card counts."""

    schema_id: str = Field(alias="schema", description="The kind of record, by id.")
    collection: str | None = Field(
        default=None, description="A collection's id; None: every collection."
    )
    within: str | None = Field(
        default=None, description="The id of a record they sit inside."
    )
    search: str | None = Field(default=None, description="A search they match.")
    filter: dict[str, Any] | None = Field(
        default=None,
        description="A filter tree, the shape the records 'filter' parameter takes.",
    )

    model_config = {"populate_by_name": True}


class CardChart(ChartModel):
    id: str = Field(
        default="", description="Ignored: a card's chart has the card's id."
    )


class DashboardCard(BaseModel):
    id: str = Field(description="The card's own id, unique on the page.")
    kind: Literal["chart", "widget"] = Field(
        description="A chart of some records, or a built-in widget."
    )
    size: Literal["small", "wide"] = Field(
        default="small", description="Half the page wide, or all of it."
    )
    title: str | None = Field(
        default=None,
        description="A title of its own; None shows the chart's or widget's name.",
    )
    chart: CardChart | None = Field(
        default=None, description="What a chart card draws."
    )
    records: CardRecords | None = Field(
        default=None, description="The records a chart card counts."
    )
    widget: str | None = Field(
        default=None,
        description="A widget card's widget: " + ", ".join(WIDGETS) + ".",
    )

    def to_dict(self) -> dict[str, Any]:
        out = self.model_dump(exclude_none=True, exclude={"chart", "records"})
        if self.chart is not None:
            chart = self.chart.to_dict()
            chart.pop("id", None)
            out["chart"] = chart
        if self.records is not None:
            out["records"] = self.records.model_dump(exclude_none=True, by_alias=True)
        return out


class DashboardCardResponse(DashboardCard):
    schema_name: str | None = Field(
        default=None,
        description="A chart card's kind of record, by name (what "
        "POST /records/summary takes); None once it is gone.",
    )
    schema_label: str | None = Field(
        default=None, description="That kind's display name."
    )
    collection_name: str | None = Field(
        default=None, description="A chart card's collection, by name."
    )
    problem: str | None = Field(
        default=None,
        description="Why a chart card can't be drawn any more (its kind or "
        "collection is gone); the card stays until someone removes it.",
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
                    schema_name=c.schema_name,
                    schema_label=c.schema_label,
                    collection_name=c.collection_name,
                    problem=c.problem,
                )
                for c in dto.cards
            ],
            edited=dto.edited,
            widgets={k: name for k, (name, _) in WIDGETS.items()},
        )


class SaveDashboardRequest(BaseModel):
    cards: list[DashboardCard] = Field(
        description="Every card the page is to hold, in order (this replaces "
        "the list). A new or changed chart card is checked against its kind."
    )


@router.get("", response_model=DashboardResponse)
def get_dashboard(ctx: AppContext = Depends(get_ctx)):
    """The Analytics page: its cards in order, each chart with the records
    it counts. Shared by everyone in the project. A chart card is drawn with
    POST /records/summary (or /records/points for a map) over its records."""
    return DashboardResponse.from_dto(ctx.dashboard_svc.page())


@router.put("", response_model=DashboardResponse)
def save_dashboard(body: SaveDashboardRequest, ctx: AppContext = Depends(get_ctx)):
    """Replace the Analytics page's cards (add, remove, reorder, resize in one
    request). Needs the right to write records somewhere, like a saved
    filter; the change is one entry in Activity and syncs to every device."""
    try:
        page = ctx.dashboard_svc.save([c.to_dict() for c in body.cards])
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return DashboardResponse.from_dto(page)
