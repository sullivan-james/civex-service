"""Saved analyses (a saved view with a summary) and the project's Analytics page
(one shared list of cards): what is checked on save, what a reader may not do,
and that every change is one entry in history."""

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
    make_schema("sample", fields=[("site", "string"), ("taken", "date")])
    ctx.schema_svc.add_field("sample", "depth", "float", restrictions={"unit": "m"})
    ctx.commit()
    survey = make_collection("survey")
    for site, depth in (("a", 1.0), ("a", 3.0), ("b", 10.0)):
        make_record("survey", "sample", {"site": site, "depth": depth})
    return survey


# --- saved analyses


def test_a_view_saves_a_summary_as_the_server_writes_it(ctx: AppContext, study):
    view = ctx.view_svc.create(
        "sample",
        "depth by site",
        filter_tree={"field": "depth", "op": "gt", "value": 0},
        summary={
            "group_by": ["site", "depth:5.0"],
            "measures": ["count", "mean:depth"],
            "sort": {"column": "mean:depth", "direction": "desc"},
            "show": "chart",
            "chart_measure": "mean:depth",
            "collection": str(study.id),
        },
    )
    ctx.commit()
    assert view.summary == {
        "group_by": ["site", "depth:5"],
        "measures": ["count", "mean:depth"],
        "sort": {"column": "mean:depth", "direction": "desc"},
        "show": "chart",
        "chart_measure": "mean:depth",
        "collection": str(study.id),
        "within": None,
        "search": None,
    }
    result = ctx.view_svc.summarise("sample", "depth by site")
    assert [(r.groups[0].value, r.values[0]) for r in result.rows] == [
        ("a", 2),
        ("b", 1),
    ]


@pytest.mark.parametrize(
    "summary, words",
    [
        ({"group_by": ["nowhere"]}, "nowhere"),
        ({"measures": ["mean:site"]}, "mean"),
        ({"group_by": ["site:month"]}, "not a date"),
        ({"measures": ["count"], "sort": {"column": "mean:depth"}}, "sorted by"),
        ({"show": "pie"}, "shown as"),
        ({"measures": ["count"], "chart_measure": "sum:depth"}, "chart draws"),
        ({"collection": "not-an-id"}, "is an id"),
        ({"colour": "red"}, "no colour"),
        ({"group_by": ["site", "taken:year", "depth:1", "taken"]}, "at most"),
    ],
)
def test_a_summary_that_could_not_run_is_refused(
    ctx: AppContext, study, summary, words
):
    with pytest.raises(ValidationError, match=words):
        ctx.view_svc.create("sample", "bad", summary=summary)


def test_an_analysis_can_change_and_become_a_plain_filter_again(ctx: AppContext, study):
    ctx.view_svc.create("sample", "a", summary={"group_by": ["site"]})
    updated = ctx.view_svc.update("sample", "a", summary={"group_by": ["taken:year"]})
    assert updated.summary["group_by"] == ["taken:year"]
    # Leaving it out leaves it alone; None clears it.
    assert ctx.view_svc.update("sample", "a", columns=["site"]).summary is not None
    assert ctx.view_svc.update("sample", "a", summary=None).summary is None
    with pytest.raises(ValidationError, match="not a saved analysis"):
        ctx.view_svc.summarise("sample", "a")


# --- the Analytics page


def test_the_page_starts_as_every_widget(ctx: AppContext):
    page = ctx.dashboard_svc.page()
    assert not page.edited
    assert [c.card.widget for c in page.cards] == list(dashboard.WIDGETS)
    assert ctx.dashboard_svc._repo.get() is None  # nothing stored until edited


def test_editing_the_page_adds_reorders_resizes_and_removes(ctx: AppContext, study):
    view = ctx.view_svc.create("sample", "by site", summary={"group_by": ["site"]})
    ctx.dashboard_svc.add(view_id=str(view.id), size="wide", position=0)
    page = ctx.dashboard_svc.page()
    assert page.edited
    first = page.cards[0]
    assert first.card.view == str(view.id) and first.view.name == "by site"

    cards = [c.card.to_dict() for c in page.cards]
    cards.reverse()
    ctx.dashboard_svc.save(cards)
    assert ctx.dashboard_svc.cards()[-1].view == str(view.id)
    ctx.dashboard_svc.resize(first.card.id, "small")
    ctx.dashboard_svc.remove("widget-storage")
    ids = [c.id for c in ctx.dashboard_svc.cards()]
    assert "widget-storage" not in ids and len(ids) == len(dashboard.WIDGETS)
    with pytest.raises(NotFoundError):
        ctx.dashboard_svc.remove("nothing")


def test_only_saved_analyses_and_known_widgets_go_on_the_page(ctx: AppContext, study):
    plain = ctx.view_svc.create("sample", "plain")
    with pytest.raises(ValidationError, match="not an analysis"):
        ctx.dashboard_svc.add(view_id=str(plain.id))
    with pytest.raises(ValidationError, match="does not exist"):
        ctx.dashboard_svc.add(view_id="00000000-0000-0000-0000-000000000001")
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


def test_a_card_stays_when_its_analysis_is_deleted(ctx: AppContext, study):
    view = ctx.view_svc.create("sample", "gone", summary={"group_by": ["site"]})
    ctx.dashboard_svc.add(view_id=str(view.id))
    ctx.view_svc.delete("sample", "gone")
    page = ctx.dashboard_svc.page()
    (card,) = [c for c in page.cards if c.card.view == str(view.id)]
    assert card.view is None
    # Saving the page with it still on is fine; it goes when someone removes it.
    ctx.dashboard_svc.resize("widget-storage", "wide")
    ctx.dashboard_svc.remove(card.card.id)


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
    view = owner.view_svc.create("sample", "by site", summary={"group_by": ["site"]})
    owner.commit()

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
            reader.dashboard_svc.add(view_id=str(view.id))
        with pytest.raises(NotAllowedError):
            reader.view_svc.create("sample", "x", summary={"group_by": ["site"]})
    finally:
        reader.close()
    writer = as_(Permissions.of(p.READ, p.WRITE_RECORDS))
    try:
        writer.dashboard_svc.add(view_id=str(view.id))
        writer.commit()
    finally:
        writer.close()
