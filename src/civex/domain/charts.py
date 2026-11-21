"""A chart: one definition, used for a kind's charts (`schemas.charts`), the
explorer's charts column and the cards of the Analytics page.

A chart is either **bars** (a `SavedSummary`: what the records are grouped by
and what each bar shows, worked out by `RecordService.summarise`) or a **map**
of a location field (`RecordService.points`). It says nothing about which
records: a chart counts the records it is shown beside (a list in the
explorer), or the ones an Analytics card names (`Scope`). Pure: the shapes
and their one check (`parse_chart`, `parse_charts`, `Scope.from_dict`);
whether the fields exist is the record service's (`RecordService.check_chart`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from civex.domain.exceptions import ValidationError
from civex.domain.summary import SavedSummary

MAX_CHARTS = 24
MAX_TITLE = 200
_SUMMARY_KEYS = ("group_by", "measures", "sort", "show", "chart_measure")


@dataclass(frozen=True)
class Chart:
    id: str  # unique among the charts it is listed with
    title: str | None = None  # None: named for what it shows
    summary: SavedSummary | None = None  # bars
    # A map: the location field, as a grouping writes one (`field`, or
    # `kind.field` for a kind above).
    map: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id}
        if self.title:
            out["title"] = self.title
        if self.map is not None:
            out["map"] = self.map
        elif self.summary is not None:
            out.update(self.summary.to_dict())
        return out

    @property
    def map_field(self) -> tuple[str, str | None]:
        """A map's (field, kind above or None)."""
        schema, _, field = (self.map or "").rpartition(".")
        return field, schema or None


def parse_chart(raw: Any) -> Chart:
    """Read and check one chart: an id, a short title, and either a map's
    field or a summary (`SavedSummary.from_dict`)."""
    if not isinstance(raw, dict):
        raise ValidationError("A chart is an object")
    unknown = set(raw) - {"id", "title", "map", *_SUMMARY_KEYS}
    if unknown:
        raise ValidationError("A chart has no " + ", ".join(sorted(unknown)))
    chart_id = raw.get("id")
    if not isinstance(chart_id, str) or not chart_id or len(chart_id) > 64:
        raise ValidationError("A chart needs an id of up to 64 characters")
    title = raw.get("title") or None
    if title is not None and (not isinstance(title, str) or len(title) > MAX_TITLE):
        raise ValidationError(f"A chart's title is text of up to {MAX_TITLE}")
    where = raw.get("map")
    if where is not None:
        if not isinstance(where, str) or not where.rpartition(".")[2]:
            raise ValidationError("A map names a location field")
        if any(raw.get(k) for k in _SUMMARY_KEYS):
            raise ValidationError("A map has no bars")
        return Chart(chart_id, title, map=where)
    summary = SavedSummary.from_dict({k: raw[k] for k in _SUMMARY_KEYS if k in raw})
    return Chart(chart_id, title, summary=summary)


def parse_charts(raw: Any) -> list[Chart]:
    """Read and check a list of charts (ids unique in it)."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValidationError("Charts are a list")
    if len(raw) > MAX_CHARTS:
        raise ValidationError(f"At most {MAX_CHARTS} charts")
    charts = [parse_chart(item) for item in raw]
    ids = [c.id for c in charts]
    if len(set(ids)) != len(ids):
        raise ValidationError("Two charts have the same id")
    return charts


@dataclass(frozen=True)
class Scope:
    """The records an Analytics card's chart counts: a kind (by id, so a
    rename costs nothing), and optionally a collection (id; None: every
    collection), a record they sit inside (id), a search and a filter tree
    (the views' wire shape, by field name)."""

    schema: str
    collection: str | None = None
    within: str | None = None
    search: str | None = None
    filter: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"schema": self.schema}
        for key in ("collection", "within", "search", "filter"):
            value = getattr(self, key)
            if value:
                out[key] = value
        return out

    @classmethod
    def from_dict(cls, raw: Any) -> Scope:
        if not isinstance(raw, dict):
            raise ValidationError("A chart's records are an object")
        unknown = set(raw) - {"schema", "collection", "within", "search", "filter"}
        if unknown:
            raise ValidationError(
                "A chart's records have no " + ", ".join(sorted(unknown))
            )

        def an_id(key: str) -> str | None:
            value = raw.get(key) or None
            if value is None:
                return None
            try:
                return str(uuid.UUID(str(value)))
            except ValueError:
                raise ValidationError(f"A chart's '{key}' is an id") from None

        schema = an_id("schema")
        if schema is None:
            raise ValidationError("A chart card names a kind of record by id")
        search = raw.get("search") or None
        if search is not None and not isinstance(search, str):
            raise ValidationError("A chart's 'search' is text")
        tree = raw.get("filter") or None
        if tree is not None and not isinstance(tree, dict):
            raise ValidationError("A chart's 'filter' is a filter tree")
        return cls(schema, an_id("collection"), an_id("within"), search, tree)
