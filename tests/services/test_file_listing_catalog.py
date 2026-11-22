"""The files list is answered from the database alone, and says what a plan of
every file says.

`FileAccessService.listing`/`chosen` once planned every file of a selection
(every record loaded, named and located) to show fifty rows. They now read the
catalog and the records' file values in one statement and name only the page.
These tests hold the two to the same answers on a project seeded with the
awkward cases, hold the cost constant as records grow, and check that no drive
is asked where a file is."""

from __future__ import annotations

import dataclasses
from collections import Counter
from typing import Any

import pytest
from sqlalchemy import event

from civex.context import AppContext
from civex.domain.file_access import (
    FileSelection,
    copy_key,
    in_place,
    place_of,
    server_state,
)
from civex.domain.query import RecordQuery

from .test_file_access_service import Study, _unplug, archive, study  # noqa: F401


# -- what a plan of everything says (the list as it was first built) ----------


def _planned(ctx: AppContext, selection: FileSelection, **narrow: Any) -> dict:
    """The listing worked out the long way: plan every file of the selection,
    then count and narrow the plan's items."""
    svc = ctx.file_access_svc
    plan = svc.plan(dataclasses.replace(selection, fields=None))
    kinds = set(selection.fields) if selection.fields else None
    place, server = narrow.get("place"), narrow.get("server")
    items = [
        i
        for i in plan.items
        if (kinds is None or i.field in kinds)
        and (place is None or in_place(i, place))
        and (server is None or server_state(i) == server)
    ]
    of_kind = [i for i in plan.items if kinds is None or i.field in kinds]
    users = svc.refs.copy_users(i.sha256 for i in items)
    here: dict[str, set[str]] = {}
    uses: dict[str, list] = {}
    for i in sorted(items, key=lambda i: i.path.casefold()):
        here.setdefault(copy_key(i), set()).add(i.record_id)
        uses.setdefault(copy_key(i), []).append(i)
    used = {
        key: max(len(users.get((uses[key][0].sha256, uses[key][0].volume), ())), len(r))
        for key, r in here.items()
    }
    sharing = Counter(used.values())
    wanted = set(narrow.get("used_by") or [])
    rows = [k for k in uses if not wanted or used[k] in wanted]
    one_each = {copy_key(i): i for i in reversed(of_kind)}.values()
    places: dict[tuple[str, str], list[int]] = {}
    for i in one_each:
        at = places.setdefault(place_of(i), [0, 0])
        at[0] += 1
        at[1] += i.size
    by_kind: dict[str, list[int]] = {}
    for i in {(i.field, i.sha256): i for i in plan.items}.values():
        at = by_kind.setdefault(i.field, [0, 0])
        at[0] += 1
        at[1] += i.size
    return {
        "total": len(rows),
        "places": {k: tuple(v) for k, v in places.items()},
        "kinds": {k: tuple(v) for k, v in by_kind.items()},
        "sharing": [{"records": n, "files": sharing[n]} for n in sorted(sharing)],
        "rows": {
            key: {
                "item": uses[key][0].to_dict(),
                "uses": [u.to_dict() for u in uses[key]],
                "others": used[key] - len(here[key]),
            }
            for key in rows
        },
    }


def _listed(ctx: AppContext, selection: FileSelection, **narrow: Any) -> dict:
    """The same, as the list answers it now (every page of it)."""
    svc = ctx.file_access_svc
    rows: dict[str, dict] = {}
    offset = 0
    while True:
        page = svc.listing(selection, offset=offset, limit=3, **narrow)
        for item in page.items:
            key = copy_key(item)
            rows[key] = {
                "item": item.to_dict(),
                "uses": [u.to_dict() for u in page.uses[key]],
                "others": page.others[key],
            }
        offset += 3
        if offset >= page.total:
            break
    return {
        "total": page.total,
        "places": {(p.place, p.kind): (p.files, p.bytes) for p in page.summary},
        "kinds": {k["field"]: (k["files"], k["bytes"]) for k in page.kinds},
        "sharing": page.sharing,
        "rows": rows,
    }


@pytest.fixture()
def seeded(ctx: AppContext, study: Study, archive, make_collection, make_record):  # noqa: F811
    """Every awkward case at once: a file on the encounter itself, a list of
    files, the same file twice in one record and in two records, a second
    copy on another drive with its own record, a deleted record's file, a
    deleted field's file, and a second collection."""
    cid = str(study.collection.id)
    ctx.record_svc.update(
        str(study.e7.id),
        {"name": "Encounter 7", "notes": study.file(b"field notes", "notes.pdf")},
    )
    study.s1 = study.selection(study.rec_a, "s1", b"one")
    study.s2 = study.selection(study.rec_a, "s2", b"the same table")
    study.s3 = study.selection(study.rec_b, "s3", b"the same table")  # shared
    study.s4 = study._child(
        "selection",
        {
            "sname": "s4",
            "table": study.file(b"four four", "s4.txt"),
            "extra": [
                study.file(b"extra a", "a.csv"),
                study.file(b"extra bb", "b.csv"),
                study.file(b"four four", "again.txt"),  # the table, again
            ],
        },
        study.rec_b,
    )
    study.far = study.selection(study.rec_c, "far", b"on the archive", on=cid)
    # The same content, written again onto the collection's own drive: two
    # copies, each with its own record.
    study.both = study.selection(study.rec_c, "both", b"one", on=cid)
    gone = study.selection(study.rec_a, "gone", b"deleted with its record")
    ctx.record_svc.delete(str(gone.id))
    make_collection("other")
    study.elsewhere = make_record(
        "other", "encounter", {"name": "Elsewhere", "notes": study.file(b"e", "e.pdf")}
    )
    ctx.commit()
    return study


def _selections(made: Study) -> dict[str, FileSelection]:
    within = str(made.e7.id)
    return {
        "a record and all inside it": FileSelection(query=RecordQuery(within=within)),
        "a collection": FileSelection(query=RecordQuery(dataset="hb"), below=True),
        "every collection": FileSelection(query=RecordQuery(), below=True),
        "one kind": FileSelection(query=RecordQuery(dataset="hb", schema="selection")),
        "a kind and what is inside": FileSelection(
            query=RecordQuery(dataset="hb", schema="recording"), below=True
        ),
        "inside a record, by kind": FileSelection(
            query=RecordQuery(schema="selection", within=within),
            below=True,
            with_within=True,
        ),
        "ticked rows and what is inside": FileSelection(
            record_ids=[str(made.rec_b.id), str(made.e8.id), "not-an-id"],
            below=True,
        ),
        "ticked rows alone": FileSelection(
            record_ids=[str(made.s4.id), str(made.e7.id)]
        ),
        "a filter on a kind beneath": FileSelection(
            query=RecordQuery(
                dataset="hb",
                schema="encounter",
                filter_tree={
                    "and": [
                        {
                            "schema": "selection",
                            "field": "sname",
                            "op": "eq",
                            "value": "s3",
                        }
                    ]
                },
            ),
            below=True,
        ),
        "only some kinds of record": FileSelection(
            query=RecordQuery(dataset="hb"), schemas=["encounter", "selection"]
        ),
        "one kind of file": FileSelection(
            query=RecordQuery(dataset="hb"), below=True, fields=["extra"]
        ),
        "in one folder": FileSelection(
            query=RecordQuery(dataset="hb"), below=True, layout="flat"
        ),
    }


def test_the_list_says_what_a_plan_of_every_file_says(ctx: AppContext, seeded: Study):
    for name, selection in _selections(seeded).items():
        for narrow in (
            {},
            {"place": "archive"},
            {"place": "here"},
            {"used_by": [2]},
            {"used_by": [1]},
        ):
            assert _listed(ctx, selection, **narrow) == _planned(
                ctx, selection, **narrow
            ), f"{name} {narrow}"


def test_a_drive_that_is_unplugged_reads_the_same(
    ctx: AppContext,
    seeded: Study,
    archive,  # noqa: F811
):
    _unplug(archive)
    everything = FileSelection(query=RecordQuery(), below=True)
    for narrow in ({}, {"place": "unreachable"}, {"place": "here"}):
        assert _listed(ctx, everything, **narrow) == _planned(ctx, everything, **narrow)


def test_a_deleted_fields_files_are_not_listed(ctx: AppContext, seeded: Study):
    """The catalog still cites them (the field can be restored); the list is
    of the files records show."""
    ctx.schema_svc.delete_field("encounter", "notes")
    ctx.commit()
    everything = FileSelection(query=RecordQuery(), below=True)
    listed = _listed(ctx, everything)
    assert listed == _planned(ctx, everything)
    assert "notes" not in listed["kinds"]


def test_what_is_acted_on_is_what_is_listed(ctx: AppContext, seeded: Study):
    """`chosen` (what a move, a download and freeing space take) holds the
    same files as the plan, each with where it is."""
    svc = ctx.file_access_svc
    for name, selection in _selections(seeded).items():
        plan = svc.plan(dataclasses.replace(selection, fields=None))
        kinds = set(selection.fields) if selection.fields else None
        expected = {
            (i.record_id, i.field, i.sha256, i.size, i.volume, i.state, i.available)
            for i in plan.items
            if kinds is None or i.field in kinds
        }
        got = {
            (i.record_id, i.field, i.sha256, i.size, i.volume, i.state, i.available)
            for i in svc.chosen(selection)
        }
        assert got == expected, name


def test_sorting_orders_the_whole_list_not_the_page(ctx: AppContext, seeded: Study):
    svc = ctx.file_access_svc
    everything = FileSelection(query=RecordQuery(), below=True)

    def column(sort: str, read) -> list:
        out: list = []
        for offset in (0, 3, 6, 9):
            out += [
                read(i)
                for i in svc.listing(
                    everything, sort=sort, offset=offset, limit=3
                ).items
            ]
        return out

    sizes = column("size", lambda i: i.size)
    assert sizes == sorted(sizes) and len(sizes) == svc.listing(everything).total
    assert column("-size", lambda i: i.size) == sorted(sizes, reverse=True)
    places = column("place", lambda i: place_of(i)[0])
    assert places == sorted(places)
    # By record: in the order the records were added, as the records list is.
    assert column("path", lambda i: i.record_name)[:2] == ["Encounter 7", "s1"]


def test_a_search_finds_a_file_by_its_name_or_its_records(
    ctx: AppContext, seeded: Study
):
    svc = ctx.file_access_svc
    everything = FileSelection(query=RecordQuery(dataset="hb"), below=True)

    def found(term: str) -> list[str]:
        return sorted(i.filename for i in svc.listing(everything, name=term).items)

    assert found("a.csv") == ["a.csv"]  # the file's own name
    # Its record (whose table is listed once, under the first of its names).
    assert found("S4") == ["a.csv", "again.txt", "b.csv"]
    # A record above it: everything inside Recording B.
    assert found("recording b") == ["a.csv", "again.txt", "b.csv", "s3.txt"]
    assert found("nothing like it") == []
    # The counts beside the list are of the selection, not of what was found.
    assert sum(k["files"] for k in svc.listing(everything, name="a.csv").kinds) > 1


def test_a_preview_has_the_plans_totals_and_names_only_the_first_files(
    ctx: AppContext,
    seeded: Study,
    archive,  # noqa: F811
):
    svc = ctx.file_access_svc
    _unplug(archive)  # so some of it can't be reached, and is said so
    for name, selection in _selections(seeded).items():
        plan = svc.plan(selection)
        preview = svc.preview(selection, limit=2)
        whole, shown = plan.to_dict(False), preview.to_dict(False)
        for said in (whole, shown):
            for group in said["unavailable"]:
                group["records"] = sorted(group["records"])
        assert shown == whole, name
        # The files it names are the plan's own, path and all; the rest are
        # counted, not named.
        paths = {(i.record_id, i.field, i.sha256, i.path) for i in plan.items}
        named = preview.items[: preview.named]
        assert named and len(named) <= 6, name
        assert {(i.record_id, i.field, i.sha256, i.path) for i in named} <= paths
        assert len(preview.to_dict(True, 0, 50)["items"]) == preview.named


def test_a_preview_costs_the_same_however_many_records(ctx: AppContext, study: Study):  # noqa: F811
    svc = ctx.file_access_svc
    made: list = []
    everything = FileSelection(query=RecordQuery(dataset="hb"), below=True)
    seen = []
    for size in (5, 60):
        _grow(study, size, made)
        seen.append(_statements(ctx, lambda: svc.preview(everything, limit=3)))
        assert svc.preview(everything, limit=3).total == size
    assert seen[0] == seen[1], seen


def test_planning_reads_only_the_records_that_hold_files(
    ctx: AppContext,
    study: Study,  # noqa: F811
):
    """A plan of files costs by the files (a page of the records holding
    them at a time), never by the records they are among: more records with
    no file add nothing."""
    svc = ctx.file_access_svc
    made: list = []
    _grow(study, 12, made)
    everything = FileSelection(query=RecordQuery(dataset="hb"), below=True)
    before = _statements(ctx, lambda: svc.plan(everything))
    for n in range(150):  # recordings with nothing in them
        study._child("recording", {"rname": f"empty {n}"}, study.e8)
    ctx.commit()

    assert _statements(ctx, lambda: svc.plan(everything)) == before
    assert svc.plan(everything).total == 12


# -- cost -----------------------------------------------------------------------


def _statements(ctx: AppContext, work) -> int:
    seen: list[str] = []
    engine = ctx._session.get_bind()

    def count(conn, cursor, statement, *args):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        work()
    finally:
        event.remove(engine, "before_cursor_execute", count)
    return len(seen)


def _grow(project: Study, upto: int, made: list) -> None:
    """Encounters, each with a recording holding selections with files: three
    levels, files at the bottom and on the way down."""
    while len(made) < upto:
        n = len(made)
        encounter = project._make("hb", "encounter", {"name": f"E{n}"})
        recording = project._child("recording", {"rname": f"R{n}"}, encounter)
        made.append(project.selection(recording, f"sel{n}", f"content {n}".encode()))
    project.ctx.commit()


def test_listing_costs_the_same_however_many_records(ctx: AppContext, study: Study):  # noqa: F811
    svc = ctx.file_access_svc
    made: list = []
    selections = {
        "collection": FileSelection(query=RecordQuery(dataset="hb"), below=True),
        "kind and inside": FileSelection(
            query=RecordQuery(dataset="hb", schema="encounter"), below=True
        ),
        "everything": FileSelection(query=RecordQuery(), below=True),
    }
    costs: dict[str, list[int]] = {name: [] for name in selections}
    for size in (5, 40, 160):
        _grow(study, size, made)
        for name, selection in selections.items():
            costs[name].append(
                _statements(ctx, lambda: svc.listing(selection, limit=5, name="sel"))
            )
            assert svc.listing(selection, limit=5).total == size
    for name, seen in costs.items():
        assert len(set(seen)) == 1, f"{name}: {seen}"
        assert seen[0] < 40, f"{name}: {seen}"


def test_picking_files_costs_the_same_however_many_records(
    ctx: AppContext,
    study: Study,  # noqa: F811
):
    svc = ctx.file_access_svc
    made: list = []
    everything = FileSelection(query=RecordQuery(dataset="hb"), below=True)
    seen = []
    for size in (5, 60):
        _grow(study, size, made)
        seen.append(_statements(ctx, lambda: svc.chosen(everything, used_by=[1])))
    assert seen[0] == seen[1] and seen[0] < 12, seen


def test_the_list_asks_no_drive_where_a_file_is(
    ctx: AppContext, seeded: Study, monkeypatch: pytest.MonkeyPatch
):
    """It must work with drives unplugged and never wait on one: where a file
    is comes from the catalog. (A drive is still asked whether it can be
    used: once each, `volume_status`.)"""
    store = ctx.file_svc._store

    def refuse(*args: Any, **kwargs: Any):
        raise AssertionError("the list looked for a file on a drive")

    for name in (
        "locate_volumes",
        "_locate",
        "_find_unrecorded",
        "path_on",
        "object_path",
        "exists",
        "size_of",
        "copies_of",
    ):
        if hasattr(store, name):
            monkeypatch.setattr(store, name, refuse)
    svc = ctx.file_access_svc
    everything = FileSelection(query=RecordQuery(), below=True)

    assert svc.chosen(everything, place="here")
    assert svc.chosen(everything, place="archive", used_by=[1])
