"""The project's Analytics page: one shared, ordered list of cards (saved
analyses and built-in widgets, `civex.domain.dashboard`). Anyone who may write
records somewhere may change it, like a saved filter; every change is one
history entry about the page, so it shows in Activity and syncs."""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

from civex.domain import dashboard, permissions
from civex.domain.dashboard import Card
from civex.domain.dtos import DashboardCardDTO, DashboardPageDTO
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.domain.permissions import EVERYTHING, Permissions
from civex.repositories.protocols import (
    AuditRepository,
    DashboardRepository,
    ViewRepository,
)


class DashboardService:
    def __init__(
        self,
        repo: DashboardRepository,
        views: ViewRepository,
        audit_repo: AuditRepository | None = None,
        permissions: Permissions = EVERYTHING,
    ) -> None:
        self._repo = repo
        self._views = views
        self._audit = audit_repo
        self._permissions = permissions

    def cards(self) -> list[Card]:
        """The page's cards in order: as saved, or the default ones."""
        stored = self._repo.get()
        if stored is None:
            return dashboard.default_cards()
        return dashboard.parse_cards(stored.cards)

    def page(self) -> DashboardPageDTO:
        """The page as shown: each card, and for an analysis the saved view it
        names (None once that view is deleted; the card stays until someone
        removes it). Views are read in one query whatever the page holds."""
        self._permissions.require(permissions.READ)
        stored = self._repo.get()
        cards = (
            dashboard.parse_cards(stored.cards)
            if stored is not None
            else dashboard.default_cards()
        )
        views = {str(v.id): v for v in self._views.list_all()}
        return DashboardPageDTO(
            cards=[DashboardCardDTO(c, views.get(c.view or "")) for c in cards],
            edited=stored is not None,
        )

    def save(self, cards: list[dict[str, Any]]) -> DashboardPageDTO:
        """Replace the page's cards (in order). A new analysis card must name a
        saved view that has a summary; one already on the page may name a view
        deleted since, so saving never forces a person to tidy up first."""
        self._permissions.require_somewhere(permissions.WRITE_RECORDS)
        parsed = dashboard.parse_cards(cards)
        before = self._repo.get()
        known = {c.view for c in self.cards() if c.view}
        views = {str(v.id): v for v in self._views.list_all()}
        for card in parsed:
            if card.view is None or card.view in known:
                continue
            view = views.get(card.view)
            if view is None:
                raise ValidationError("That saved analysis does not exist")
            if view.summary is None:
                raise ValidationError(
                    f"View '{view.name}' is a saved filter, not an analysis: "
                    "save it from the explorer's Summary to put it on the page"
                )
        stored = [c.to_dict() for c in parsed]
        if before is not None and before.cards == stored:
            return self.page()
        after = self._repo.save(stored)
        if self._audit:
            if before is None:
                self._audit.log_change(
                    "create", "dashboard", after.id, None, after.to_dict()
                )
            else:
                self._audit.log_change(
                    "update", "dashboard", after.id, before.to_dict(), after.to_dict()
                )
        return self.page()

    def add(
        self,
        *,
        view_id: str | None = None,
        widget: str | None = None,
        size: str = "small",
        title: str | None = None,
        position: int | None = None,
    ) -> DashboardPageDTO:
        """Put one card on the page: a saved analysis (`view_id`) or a
        built-in widget, at `position` (None: at the end)."""
        if (view_id is None) == (widget is None):
            raise ValidationError("Add a saved analysis or a widget")
        card = {
            "id": uuid.uuid4().hex[:12],
            "kind": dashboard.ANALYSIS if view_id else dashboard.WIDGET,
            "size": size,
            "title": title,
            "view": view_id,
            "widget": widget,
        }
        cards = [c.to_dict() for c in self.cards()]
        at = len(cards) if position is None else max(0, min(position, len(cards)))
        cards.insert(at, {k: v for k, v in card.items() if v is not None})
        return self.save(cards)

    def remove(self, card_id: str) -> DashboardPageDTO:
        """Take one card off the page."""
        cards = self.cards()
        if not any(c.id == card_id for c in cards):
            raise NotFoundError(f"No card '{card_id}' on the page")
        return self.save([c.to_dict() for c in cards if c.id != card_id])

    def resize(self, card_id: str, size: str) -> DashboardPageDTO:
        cards = self.cards()
        if not any(c.id == card_id for c in cards):
            raise NotFoundError(f"No card '{card_id}' on the page")
        return self.save(
            [(replace(c, size=size) if c.id == card_id else c).to_dict() for c in cards]
        )
