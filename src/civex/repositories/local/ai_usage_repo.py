from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from civex.db.models import AiUsageEvent
from civex.domain.dtos import AiUsageEventDTO


class LocalAiUsageRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def add(
        self, provider: str, model: str, input_tokens: int, output_tokens: int
    ) -> AiUsageEventDTO:
        row = AiUsageEvent(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        self._s.add(row)
        self._s.flush()
        return _to_dto(row)

    def list_all(
        self, since: datetime | None = None, until: datetime | None = None
    ) -> list[AiUsageEventDTO]:
        q = self._s.query(AiUsageEvent)
        if since is not None:
            q = q.filter(AiUsageEvent.created_at >= since)
        if until is not None:
            q = q.filter(AiUsageEvent.created_at < until)
        q = q.order_by(AiUsageEvent.created_at)
        return [_to_dto(r) for r in q.all()]


def _to_dto(row: AiUsageEvent) -> AiUsageEventDTO:
    return AiUsageEventDTO(
        id=row.id,
        provider=row.provider,
        model=row.model,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        created_at=row.created_at,
    )
