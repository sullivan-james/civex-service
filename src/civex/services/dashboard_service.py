"""The project's Analytics page: one shared, ordered list of cards (charts
with the records they count, and built-in widgets, `civex.domain.dashboard`).
Anyone who may write records somewhere may change it, like a saved filter;
every change is one history entry about the page, so it shows in Activity and
syncs."""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

from civex.domain import dashboard, permissions
from civex.domain.charts import Scope, parse_chart
from civex.domain.dashboard import Card
from civex.domain.dtos import DashboardCardDTO, DashboardPageDTO
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.domain.permissions import EVERYTHING, Permissions
from civex.domain.query import RecordQuery
from civex.repositories.protocols import (
    AuditRepository,
    DashboardRepository,
    DatasetRepository,
)
from civex.services.record_service import RecordService
from civex.services.schema_service import SchemaService


class DashboardService:
    def __init__(
        self,
        repo: DashboardRepository,
        schema_svc: SchemaService,
        record_svc: RecordService,
        datasets: DatasetRepository,
        audit_repo: AuditRepository | None = None,
        permissions: Permissions = EVERYTHING,
    ) -> None:
        self._repo = repo
        self._schemas = schema_svc
        self._records = record_svc
        self._datasets = datasets
        self._audit = audit_repo
        self._permissions = permissions

    def cards(self) -> list[Card]:
        """The page's cards in order: as saved, or the default ones."""
        stored = self._repo.get()
        if stored is None:
            return dashboard.default_cards()
        return dashboard.parse_cards(stored.cards)

    def page(self) -> DashboardPageDTO:
        """The page as shown: each card, and for a chart the names of the
        kind and collection its records are of (a card whose kind or
        collection is gone stays, with the `problem`, until someone removes
        it). Kinds and collections are read once whatever the page holds."""
        self._permissions.require(permissions.READ)
        stored = self._repo.get()
        cards = (
            dashboard.parse_cards(stored.cards)
            if stored is not None
            else dashboard.default_cards()
        )
        scopes = [c.records for c in cards if c.records is not None]
        schemas = (
            self._schemas.find({uuid.UUID(s.schema) for s in scopes}) if scopes else {}
        )
        collections = (
            {str(d.id): d.name for d in self._datasets.list_all(with_count=False)}
            if any(s.collection for s in scopes)
            else {}
        )
        shown = []
        for card in cards:
            scope = card.records
            if scope is None:
                shown.append(DashboardCardDTO(card))
                continue
            schema = schemas.get(uuid.UUID(scope.schema))
            collection = collections.get(scope.collection or "")
            problem = None
            if schema is None or schema.deleted_at is not None:
                problem = "That kind of record is gone"
            elif scope.collection and collection is None:
                problem = "That collection is gone"
            shown.append(
                DashboardCardDTO(
                    card,
                    schema_name=schema.name if schema else None,
                    schema_label=schema.display_name if schema else None,
                    collection_name=collection,
                    problem=problem,
                )
            )
        return DashboardPageDTO(cards=shown, edited=stored is not None)

    def query_for(self, card: Card, collection: str | None = None) -> RecordQuery:
        """The records a chart card counts, as the query a list would run:
        its kind, filter, search and the record it was made inside, in its
        collection, or in `collection` (a name) when the page is narrowed to
        one."""
        scope = card.records
        if scope is None:
            raise ValidationError("That card is not a chart")
        schema = self._schemas.get_by_id(uuid.UUID(scope.schema))
        if schema is None:
            raise NotFoundError("That kind of record is gone")
        dataset = collection
        if dataset is None and scope.collection:
            found = self._datasets.get_by_id(
                uuid.UUID(scope.collection), with_count=False
            )
            if found is None:
                raise NotFoundError("That collection is gone")
            dataset = found.name
        return RecordQuery(
            dataset=dataset,
            schema=schema.name,
            within=scope.within,
            search=scope.search,
            filter_tree=scope.filter,
        )

    def _check(self, card: Card) -> None:
        """A chart card can be drawn: its kind exists, its chart's fields are
        the kind's (`RecordService.check_chart`) and its filter is one a list
        of that kind takes."""
        assert card.chart is not None
        query = self.query_for(card)
        assert query.schema is not None
        self._records.check_chart(query.schema, card.chart)
        self._records.resolve(
            RecordQuery(schema=query.schema, filter_tree=query.filter_tree)
        )

    def save(self, cards: list[dict[str, Any]]) -> DashboardPageDTO:
        """Replace the page's cards (in order). A new or changed chart card is
        checked against its kind; one already on the page as it is may name a
        kind or field gone since, so saving never forces a person to tidy up
        first."""
        self._permissions.require_somewhere(permissions.WRITE_RECORDS)
        parsed = dashboard.parse_cards(cards)
        before = self._repo.get()
        known = {c.id: c for c in self.cards()}
        for card in parsed:
            if card.chart is None:
                continue
            old = known.get(card.id)
            if old is not None and (old.chart, old.records) == (
                card.chart,
                card.records,
            ):
                continue
            self._check(card)
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
        chart: dict[str, Any] | None = None,
        schema: str | None = None,
        collection: str | None = None,
        within: str | None = None,
        search: str | None = None,
        filter_tree: dict[str, Any] | None = None,
        widget: str | None = None,
        size: str = "small",
        title: str | None = None,
        position: int | None = None,
    ) -> DashboardPageDTO:
        """Put one card on the page: a chart (`chart`, as `Chart.to_dict`
        writes one without its id) of the records of kind `schema` (a name)
        in `collection` (a name; None: every collection), inside the record
        `within`, matching `search` and `filter_tree`; or a built-in widget.
        At `position` (None: at the end)."""
        if (chart is None) == (widget is None):
            raise ValidationError("Add a chart or a widget")
        card_id = uuid.uuid4().hex[:12]
        card: dict[str, Any] = {"id": card_id, "size": size, "title": title}
        if chart is not None:
            if not schema:
                raise ValidationError("A chart is of one kind of record")
            records = {
                "schema": str(self._schemas.get(schema).id),
                "collection": (
                    str(self._collection(collection).id) if collection else None
                ),
                "within": within,
                "search": search,
                "filter": filter_tree,
            }
            drawn = parse_chart({**chart, "id": card_id}).to_dict()
            drawn.pop("id")
            card |= {
                "kind": dashboard.CHART,
                "chart": drawn,
                "records": Scope.from_dict(records).to_dict(),
            }
        else:
            card |= {"kind": dashboard.WIDGET, "widget": widget}
        cards = [c.to_dict() for c in self.cards()]
        at = len(cards) if position is None else max(0, min(position, len(cards)))
        cards.insert(at, {k: v for k, v in card.items() if v is not None})
        return self.save(cards)

    def _collection(self, name: str):
        found = self._datasets.get_by_name(name, with_count=False)
        if found is None:
            raise NotFoundError(f"Collection '{name}' not found")
        return found

    def card(self, card_id: str) -> Card:
        for card in self.cards():
            if card.id == card_id:
                return card
        raise NotFoundError(f"No card '{card_id}' on the page")

    def remove(self, card_id: str) -> DashboardPageDTO:
        """Take one card off the page."""
        self.card(card_id)
        return self.save([c.to_dict() for c in self.cards() if c.id != card_id])

    def resize(self, card_id: str, size: str) -> DashboardPageDTO:
        self.card(card_id)
        return self.save(
            [
                (replace(c, size=size) if c.id == card_id else c).to_dict()
                for c in self.cards()
            ]
        )
