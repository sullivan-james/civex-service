"""Charts: the ones a kind of record's lists open with (`schemas.charts`) and
the cards of the project's Analytics page (a chart and the records it counts):
what is checked on save, what a reader may not do, and that every change is
one entry in history."""

from __future__ import annotations

from pathlib import Path

import pytest

from civex.config import FileConfigStore, load_config_at
from civex.context import AppContext, build_context, build_local_context
from civex.domain import dashboard
from civex.domain import permissions as p
from civex.domain.exceptions import NotAllowedError, NotFoundError, ValidationError
from civex.domain.permissions import Permissions
from civex.project import Project, scaffold_project


@pytest.fixture()
def study(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema(
        "sample", fields=[("site", "string"), ("taken", "date"), ("where", "geo")]
    )
    ctx.schema_svc.add_field("sample", "depth", "float", restrictions={"unit": "m"})
    ctx.commit()
    survey = make_collection("survey")
    for site, depth in (("a", 1.0), ("a", 3.0), ("b", 10.0)):
        make_record("survey", "sample", {"site": site, "depth": depth})
    return survey


# --- a kind's charts

BY_SITE = {"id": "a", "group_by": ["site"], "measures": ["count"]}


def test_a_kind_keeps_its_charts_as_the_server_writes_them(ctx: AppContext, study):
    saved = ctx.schema_svc.set_charts(
        "sample",
        [
            {
                "id": "a",
                "title": "Depth",
                "group_by": ["site", "depth:5.0"],
                "measures": ["count", "mean:depth"],
                "sort": {"column": "mean:depth", "direction": "desc"},
                "chart_measure": "mean:depth",
            },
            {"id": "b", "map": "where"},
        ],
    )
    ctx.commit()
    assert saved.charts == [
        {
            "id": "a",
            "title": "Depth",
            "group_by": ["site", "depth:5"],
            "measures": ["count", "mean:depth"],
            "sort": {"column": "mean:depth", "direction": "desc"},
            "chart_measure": "mean:depth",
        },
        {"id": "b", "map": "where"},
    ]
    assert ctx.schema_svc.get("sample").charts == saved.charts
    assert ctx.schema_svc.set_charts("sample", []).charts == []


@pytest.mark.parametrize(
    "chart, words",
    [
        ({"group_by": ["nowhere"]}, "nowhere"),
        ({"measures": ["mean:site"]}, "mean"),
        ({"group_by": ["site:month"]}, "not a date"),
        ({"measures": ["count"], "sort": {"column": "mean:depth"}}, "sorted by"),
        ({"show": "pie"}, "opens as"),
        ({"measures": ["count"], "chart_measure": "sum:depth"}, "chart draws"),
        ({"colour": "red"}, "no colour"),
        ({"group_by": ["site", "taken:year", "depth:1", "taken"]}, "at most"),
        ({"map": "site"}, "not a location"),
        ({"map": "where", "group_by": ["site"]}, "no bars"),
        ({"measures": ["inside:nothing"]}, "beneath"),
    ],
)
def test_a_chart_that_could_not_be_drawn_is_refused(
    ctx: AppContext, study, chart, words
):
    with pytest.raises(ValidationError, match=words):
        ctx.schema_svc.set_charts("sample", [{"id": "x", **chart}])


def test_two_charts_may_not_share_an_id(ctx: AppContext, study):
    with pytest.raises(ValidationError, match="same id"):
        ctx.schema_svc.set_charts("sample", [BY_SITE, BY_SITE])


def test_setting_charts_is_one_entry_and_nothing_when_unchanged(ctx: AppContext, study):
    ctx.schema_svc.set_charts("sample", [BY_SITE])
    ctx.schema_svc.set_charts("sample", [BY_SITE])
    ctx.commit()
    entries = [
        e
        for e in ctx.history_svc.page(entity_type="schema")
        if any(c["field"] == "charts" for c in e.changes or [])
    ]
    assert len(entries) == 1


def test_charts_follow_a_renamed_field_and_drop_with_a_deleted_one(
    ctx: AppContext, study
):
    ctx.schema_svc.set_charts(
        "sample",
        [
            {
                "id": "a",
                "group_by": ["site"],
                "measures": ["count", "mean:depth"],
                "chart_measure": "mean:depth",
            },
            {"id": "b", "group_by": ["taken:year"]},
            {"id": "c", "map": "where"},
        ],
    )
    ctx.schema_svc.update_field("sample", "depth", new_name="deep")
    charts = ctx.schema_svc.get("sample").charts
    assert charts[0]["measures"] == ["count", "mean:deep"]
    assert charts[0]["chart_measure"] == "mean:deep"
    ctx.schema_svc.delete_field("sample", "site")
    ctx.schema_svc.delete_field("sample", "where")
    assert [c["id"] for c in ctx.schema_svc.get("sample").charts] == ["b"]
    # What is left can still be drawn.
    for chart in ctx.schema_svc.get("sample").charts:
        ctx.record_svc.check_chart("sample", charts_of(chart))


def charts_of(raw):
    from civex.domain.charts import parse_chart

    return parse_chart(raw)


# --- the Analytics page


def test_the_page_starts_as_every_widget(ctx: AppContext):
    page = ctx.dashboard_svc.page()
    assert not page.edited
    assert [c.card.widget for c in page.cards] == list(dashboard.WIDGETS)
    assert ctx.dashboard_svc._repo.get() is None  # nothing stored until edited


def test_a_chart_card_holds_its_chart_and_its_records(ctx: AppContext, study):
    ctx.dashboard_svc.add(
        chart={"group_by": ["site"], "measures": ["count"]},
        schema="sample",
        collection="survey",
        filter_tree={"field": "depth", "op": "gt", "value": 2},
        size="wide",
        position=0,
    )
    page = ctx.dashboard_svc.page()
    assert page.edited
    first = page.cards[0]
    assert first.schema_name == "sample" and first.collection_name == "survey"
    assert first.problem is None
    assert first.card.chart.summary.group_by == ["site"]
    # The card is drawn with the usual summary, over the records it names.
    query = ctx.dashboard_svc.query_for(first.card)
    result = ctx.record_svc.summarise(query, first.card.chart.summary.request())
    assert [(r.groups[0].value, r.values[0]) for r in result.rows] == [
        ("a", 1),
        ("b", 1),
    ]
    # Narrowed to another collection, it counts that one's records.
    ctx.dataset_svc.create("other")
    other = ctx.dashboard_svc.query_for(first.card, collection="other")
    assert ctx.record_svc.summarise(
        other, first.card.chart.summary.request()
    ).total == [0]


def test_editing_the_page_reorders_resizes_and_removes(ctx: AppContext, study):
    ctx.dashboard_svc.add(chart={"group_by": ["site"]}, schema="sample", position=0)
    page = ctx.dashboard_svc.page()
    first = page.cards[0]
    cards = [c.card.to_dict() for c in page.cards]
    cards.reverse()
    ctx.dashboard_svc.save(cards)
    assert ctx.dashboard_svc.cards()[-1].id == first.card.id
    ctx.dashboard_svc.resize(first.card.id, "wide")
    ctx.dashboard_svc.remove("widget-storage")
    ids = [c.id for c in ctx.dashboard_svc.cards()]
    assert "widget-storage" not in ids and len(ids) == len(dashboard.WIDGETS)
    with pytest.raises(NotFoundError):
        ctx.dashboard_svc.remove("nothing")


def test_only_charts_that_can_be_drawn_and_known_widgets_go_on_the_page(
    ctx: AppContext, study
):
    with pytest.raises(ValidationError, match="nowhere"):
        ctx.dashboard_svc.add(chart={"group_by": ["nowhere"]}, schema="sample")
    with pytest.raises(NotFoundError):
        ctx.dashboard_svc.add(chart={"group_by": ["site"]}, schema="nothing")
    with pytest.raises(NotFoundError):
        ctx.dashboard_svc.add(
            chart={"group_by": ["site"]}, schema="sample", collection="nothing"
        )
    with pytest.raises(ValidationError):
        ctx.dashboard_svc.add(
            chart={"group_by": ["site"]},
            schema="sample",
            filter_tree={"field": "nowhere", "op": "eq", "value": 1},
        )
    with pytest.raises(ValidationError, match="Unknown widget"):
        ctx.dashboard_svc.add(widget="weather")
    with pytest.raises(ValidationError, match="size"):
        ctx.dashboard_svc.add(widget="storage", size="huge")
    with pytest.raises(ValidationError, match="Two cards"):
        ctx.dashboard_svc.save(
            [
                {"id": "x", "kind": "widget", "widget": "storage"},
                {"id": "x", "kind": "widget", "widget": "triggers"},
            ]
        )


def test_a_card_stays_when_its_field_or_collection_is_gone(ctx: AppContext, study):
    ctx.dashboard_svc.add(
        chart={"group_by": ["site"]}, schema="sample", collection="survey"
    )
    card = ctx.dashboard_svc.cards()[-1]
    ctx.schema_svc.delete_field("sample", "site")
    ctx.dataset_svc.delete("survey")
    shown = ctx.dashboard_svc.page().cards[-1]
    assert shown.problem == "That collection is gone"
    # Saving the page with it still on is fine; it goes when someone removes it.
    ctx.dashboard_svc.resize("widget-storage", "wide")
    ctx.dashboard_svc.remove(card.id)


def test_each_change_to_the_page_is_one_entry_in_history(ctx: AppContext, study):
    ctx.dashboard_svc.add(widget="storage", size="wide")
    ctx.dashboard_svc.remove("widget-triggers")
    # Saving the page as it is writes nothing.
    ctx.dashboard_svc.save([c.to_dict() for c in ctx.dashboard_svc.cards()])
    ctx.commit()
    entries = ctx.history_svc.page(entity_type="dashboard")
    assert sorted(e.action for e in entries) == ["create", "update"]
    update = next(e for e in entries if e.action == "update")
    assert [c["field"] for c in update.changes] == ["cards"]


# --- who may


@pytest.fixture()
def as_reader(tmp_path: Path):
    root = tmp_path / "study"
    scaffold_project(root)
    owner = build_local_context(load_config_at(root))
    owner.schema_svc.create("sample")
    owner.schema_svc.add_field("sample", "site", "string")
    owner.dataset_svc.create("mine")
    owner.commit()
    view = {"group_by": ["site"]}

    def as_(perms: Permissions) -> AppContext:
        return build_context(
            Project(
                config=load_config_at(root),
                config_store=FileConfigStore(root),
                actor="Dr Example",
                permissions=perms,
            )
        )

    yield as_, view
    owner.close()


def test_a_reader_sees_the_page_but_may_not_change_it(as_reader):
    as_, view = as_reader
    reader = as_(Permissions.of(p.READ))
    try:
        assert reader.dashboard_svc.page().cards
        with pytest.raises(NotAllowedError):
            reader.dashboard_svc.add(chart=view, schema="sample")
        with pytest.raises(NotAllowedError):
            reader.schema_svc.set_charts("sample", [{"id": "a", **view}])
    finally:
        reader.close()
    writer = as_(Permissions.of(p.READ, p.WRITE_RECORDS))
    try:
        writer.dashboard_svc.add(chart=view, schema="sample")
        # A kind's charts are part of the structure: writing records is not enough.
        with pytest.raises(NotAllowedError):
            writer.schema_svc.set_charts("sample", [{"id": "a", **view}])
        writer.commit()
    finally:
        writer.close()
