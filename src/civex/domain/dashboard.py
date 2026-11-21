"""The project's Analytics page: one shared, ordered list of cards.

A card is a chart (`civex.domain.charts.Chart`: the one chart definition,
with the records it was made for, `Scope`) or one of the built-in widgets
(`WIDGETS`), with a size and an optional title of its own. The page is one
thing per project (`DASHBOARD_ID`, the same on every copy, so two devices
that both edit it edit the same thing); until someone edits it, it is
`default_cards()`. Pure: the shape and its one check (`parse_cards`);
`DashboardService` stores it, asks permission and writes history.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from civex.domain.charts import Chart, Scope, parse_chart
from civex.domain.exceptions import ValidationError

#: The page's id, on every copy of every project.
DASHBOARD_ID = uuid.UUID("5d1e9a7c-3b2f-4c6e-8a0d-7f4b2e1c9a35")

CHART = "chart"
WIDGET = "widget"
KINDS = (CHART, WIDGET)
#: How wide a card is: half the page, or all of it.
SIZES = ("small", "wide")
MAX_CARDS = 60
MAX_TITLE = 200

#: The built-in widgets, in the order the default page shows them, with their
#: plain name and the size they start at.
WIDGETS: dict[str, tuple[str, str]] = {
    "record_growth": ("Record growth", "small"),
    "record_counts": ("Records by collection", "small"),
    "storage": ("Storage", "small"),
    "schema_lint": ("Schema names", "small"),
    "run_success": ("Workflow runs", "small"),
    "plugin_failures": ("Failures by plugin", "small"),
    "durations": ("Step durations", "small"),
    "triggers": ("Runs by trigger", "small"),
    "activity": ("Activity over time", "small"),
    "activity_kinds": ("Activity by kind", "small"),
    "ai_tokens": ("AI usage", "wide"),
}


@dataclass(frozen=True)
class Card:
    id: str  # the card's own id, unique on the page
    kind: str  # CHART or WIDGET
    size: str = "small"
    title: str | None = None  # None: the chart's or widget's own name
    chart: Chart | None = None  # what a chart card draws
    records: Scope | None = None  # ... and the records it counts
    widget: str | None = None  # a key of WIDGETS

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "kind": self.kind, "size": self.size}
        if self.title:
            out["title"] = self.title
        if self.chart is not None and self.records is not None:
            out["chart"] = self.chart.to_dict()
            out["records"] = self.records.to_dict()
        if self.widget:
            out["widget"] = self.widget
        return out


def default_cards() -> list[Card]:
    """The page before anyone has edited it: every widget, as it always was."""
    return [
        Card(id=f"widget-{name}", kind=WIDGET, size=size, widget=name)
        for name, (_, size) in WIDGETS.items()
    ]


def parse_cards(raw: Any) -> list[Card]:
    """Read and check a list of cards: each a known kind, holding a chart
    and its records or naming a known widget, a known size, a short title,
    and ids unique on the page. Whether the kind and fields exist is the
    service's to ask."""
    if not isinstance(raw, list):
        raise ValidationError("The page's cards are a list")
    if len(raw) > MAX_CARDS:
        raise ValidationError(f"A page holds at most {MAX_CARDS} cards")
    cards: list[Card] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValidationError("A card is an object")
        unknown = set(item) - {
            "id",
            "kind",
            "size",
            "title",
            "chart",
            "records",
            "widget",
        }
        if unknown:
            raise ValidationError("A card has no " + ", ".join(sorted(unknown)))
        card_id = item.get("id")
        if not isinstance(card_id, str) or not card_id or len(card_id) > 64:
            raise ValidationError("A card needs an id of up to 64 characters")
        if card_id in seen:
            raise ValidationError(f"Two cards have the id '{card_id}'")
        seen.add(card_id)
        kind = item.get("kind")
        if kind not in KINDS:
            raise ValidationError(f"A card is one of: {', '.join(KINDS)}")
        size = item.get("size") or "small"
        if size not in SIZES:
            raise ValidationError(f"A card's size is one of: {', '.join(SIZES)}")
        title = item.get("title") or None
        if title is not None and (not isinstance(title, str) or len(title) > MAX_TITLE):
            raise ValidationError(f"A card's title is text of up to {MAX_TITLE}")
        chart = records = widget = None
        if kind == CHART:
            chart = parse_chart({"id": card_id, **(item.get("chart") or {})})
            records = Scope.from_dict(item.get("records"))
        else:
            widget = item.get("widget")
            if widget not in WIDGETS:
                raise ValidationError(
                    f"Unknown widget '{widget}'. Use one of: " + ", ".join(WIDGETS)
                )
        cards.append(Card(card_id, kind, size, title, chart, records, widget))
    return cards
