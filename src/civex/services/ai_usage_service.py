from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civex.repositories.local.ai_usage_repo import LocalAiUsageRepository


@dataclass
class UsageTotals:
    requests: int
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ModelUsage:
    provider: str
    model: str
    totals: UsageTotals


class AiUsageService:
    """Records token usage per provider API call, independent of whatever
    request happened to trigger it.

    Deliberately holds its own `engine` rather than a shared Session the way
    every other service does: /ai/chat's session is never committed (proposal
    validation runs inside a SAVEPOINT that's always rolled back, and the
    outer session itself is closed without a commit -- see AppContext /
    services/ai/service.py). Usage events must persist regardless of that,
    so each call opens and commits its own short-lived session on the same
    engine instead of riding along with a session that may never commit.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def record(
        self, provider: str, model: str, input_tokens: int, output_tokens: int
    ) -> None:
        with Session(self._engine) as session:
            LocalAiUsageRepository(session).add(
                provider, model, input_tokens, output_tokens
            )
            session.commit()

    def totals(self, since: datetime | None = None) -> UsageTotals:
        with Session(self._engine) as session:
            events = LocalAiUsageRepository(session).list_all(since=since)
        return UsageTotals(
            requests=len(events),
            input_tokens=sum(e.input_tokens for e in events),
            output_tokens=sum(e.output_tokens for e in events),
        )

    def by_model(self, since: datetime | None = None) -> list[ModelUsage]:
        with Session(self._engine) as session:
            events = LocalAiUsageRepository(session).list_all(since=since)
        buckets: dict[tuple[str, str], list] = {}
        for e in events:
            buckets.setdefault((e.provider, e.model), []).append(e)
        result = [
            ModelUsage(
                provider=provider,
                model=model,
                totals=UsageTotals(
                    requests=len(evs),
                    input_tokens=sum(e.input_tokens for e in evs),
                    output_tokens=sum(e.output_tokens for e in evs),
                ),
            )
            for (provider, model), evs in buckets.items()
        ]
        result.sort(key=lambda m: m.totals.total_tokens, reverse=True)
        return result
