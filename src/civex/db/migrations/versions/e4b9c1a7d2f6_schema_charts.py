"""schemas.charts; a saved analysis becomes a chart on the Analytics page

A kind of record says which charts its lists open with (`schemas.charts`, a
list of chart definitions). A chart on the Analytics page now holds its
definition and the records it counts itself, instead of naming a saved view
with a summary, so `views.summary` goes: every view that has one becomes a
chart card on the page (in place where a card named it, else added at the
end) carrying the view's kind, filter, collection, record and search, and the
view stays as a saved filter. Card ids are derived from what they replace, so
every copy of a project converts to the same page.

Revision ID: e4b9c1a7d2f6
Revises: d7a3e9c5b2f1
Create Date: 2026-11-21 12:00:00.000000
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa

import civex.db.models

revision: str = "e4b9c1a7d2f6"
down_revision: Union[str, None] = "d7a3e9c5b2f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = civex.db.models._JSON
# The page's id and the widgets it showed before anyone edited it, as they
# were when this migration was written.
_DASHBOARD_ID = uuid.UUID("5d1e9a7c-3b2f-4c6e-8a0d-7f4b2e1c9a35")
_WIDGETS = [
    ("record_growth", "small"),
    ("record_counts", "small"),
    ("storage", "small"),
    ("schema_lint", "small"),
    ("run_success", "small"),
    ("plugin_failures", "small"),
    ("durations", "small"),
    ("triggers", "small"),
    ("activity", "small"),
    ("activity_kinds", "small"),
    ("ai_tokens", "wide"),
]


def _chart_card(
    card_id: str, size: str, title: str | None, view: Any
) -> dict[str, Any]:
    """A view's summary as a chart card: the chart, and the records it was
    made for (the view's kind and filter, the summary's collection, record
    and search)."""
    summary = view.summary or {}
    chart: dict[str, Any] = {
        "id": card_id,
        "group_by": list(summary.get("group_by") or []),
        "measures": list(summary.get("measures") or ["count"]),
    }
    if summary.get("sort"):
        chart["sort"] = summary["sort"]
    if (summary.get("show") or "table") != "chart":
        chart["show"] = "table"
    if summary.get("chart_measure"):
        chart["chart_measure"] = summary["chart_measure"]
    records: dict[str, Any] = {"schema": str(view.schema_id)}
    for key in ("collection", "within", "search"):
        if summary.get(key):
            records[key] = summary[key]
    if view.filter_tree:
        records["filter"] = view.filter_tree
    return {
        "id": card_id,
        "kind": "chart",
        "size": size,
        "title": title or view.name,
        "chart": chart,
        "records": records,
    }


def _convert_analyses(bind: Any) -> None:
    views = sa.table(
        "views",
        sa.column("id", sa.Uuid()),
        sa.column("schema_id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("filter_tree", _JSON),
        sa.column("summary", _JSON),
        sa.column("created_at", civex.db.models._UTCDateTime()),
    )
    dashboards = sa.table(
        "dashboards",
        sa.column("id", sa.Uuid()),
        sa.column("cards", _JSON),
        sa.column("created_at", civex.db.models._UTCDateTime()),
    )
    analyses = {
        str(v.id): v
        for v in bind.execute(sa.select(views).order_by(views.c.created_at, views.c.id))
        if isinstance(v.summary, dict)
    }
    page = bind.execute(
        sa.select(dashboards.c.cards).where(dashboards.c.id == _DASHBOARD_ID)
    ).first()
    if page is None and not analyses:
        return
    old = (
        list(page.cards or [])
        if page is not None
        else [
            {"id": f"widget-{name}", "kind": "widget", "size": size, "widget": name}
            for name, size in _WIDGETS
        ]
    )
    cards: list[dict[str, Any]] = []
    placed: set[str] = set()
    for card in old:
        if card.get("kind") != "analysis":
            cards.append(card)
            continue
        view = analyses.get(str(card.get("view")))
        if view is None:
            continue  # its view was deleted: there is nothing to draw
        placed.add(str(view.id))
        cards.append(
            _chart_card(
                card["id"], card.get("size") or "small", card.get("title"), view
            )
        )
    for view_id, view in analyses.items():
        if view_id not in placed:
            cards.append(_chart_card("v" + view.id.hex[:11], "small", None, view))
    if page is None:
        bind.execute(
            sa.insert(dashboards).values(
                id=_DASHBOARD_ID, cards=cards, created_at=datetime.now(timezone.utc)
            )
        )
    elif cards != old:
        bind.execute(
            sa.update(dashboards)
            .where(dashboards.c.id == _DASHBOARD_ID)
            .values(cards=cards)
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "charts" not in {c["name"] for c in inspector.get_columns("schemas")}:
        with op.batch_alter_table("schemas") as batch:
            batch.add_column(sa.Column("charts", _JSON, nullable=True))
    if "summary" in {c["name"] for c in inspector.get_columns("views")}:
        _convert_analyses(bind)
        with op.batch_alter_table("views") as batch:
            batch.drop_column("summary")


def downgrade() -> None:
    with op.batch_alter_table("views") as batch:
        batch.add_column(sa.Column("summary", _JSON, nullable=True))
    with op.batch_alter_table("schemas") as batch:
        batch.drop_column("charts")
