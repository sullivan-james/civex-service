from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from civex.db.models import Dashboard
from civex.domain.dashboard import DASHBOARD_ID
from civex.domain.dtos import DashboardDTO


class LocalDashboardRepository:
    """The project's one Analytics page: the row with `DASHBOARD_ID`, made the
    first time it is saved."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self) -> DashboardDTO | None:
        row = self._s.get(Dashboard, DASHBOARD_ID)
        return _to_dto(row) if row is not None else None

    def save(self, cards: list[dict[str, Any]]) -> DashboardDTO:
        row = self._s.get(Dashboard, DASHBOARD_ID)
        if row is None:
            row = Dashboard(id=DASHBOARD_ID, cards=cards)
            self._s.add(row)
        else:
            row.cards = cards
        self._s.flush()
        return _to_dto(row)


def _to_dto(row: Dashboard) -> DashboardDTO:
    return DashboardDTO(
        id=row.id, cards=list(row.cards or []), created_at=row.created_at
    )
