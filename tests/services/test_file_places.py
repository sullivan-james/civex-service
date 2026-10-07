"""Where a selection's files are, by place, and picking files by place and
name for the Files tab and its actions."""

from __future__ import annotations

import pytest

from civex.domain.file_access import FileSelection
from civex.domain.query import RecordQuery

from .test_file_access_service import Study, _unplug, archive, study  # noqa: F401


def _within(record) -> FileSelection:
    return FileSelection(query=RecordQuery(within=str(record.id)))


@pytest.fixture()
def spread(ctx, study: Study, archive):  # noqa: F811
    """s1 on the project's own drive, s2 on the archive drive."""
    s1 = study.selection(study.rec_a, "s1", b"one")
    s2 = study.selection(study.rec_a, "s2", b"two two", on=str(study.collection.id))
    ctx.commit()
    return s1, s2


def test_the_summary_says_where_every_file_is(ctx, study, spread):  # noqa: F811
    listing = ctx.file_access_svc.listing(_within(study.e7))
    places = {(p.place, p.kind): (p.files, p.bytes) for p in listing.summary}
    assert places == {("default", "drive"): (1, 3), ("archive", "drive"): (1, 7)}
    assert listing.total == 2


def test_files_are_picked_by_place_and_by_name(ctx, study, spread):  # noqa: F811
    svc = ctx.file_access_svc
    on_archive = svc.listing(_within(study.e7), place="archive").items
    assert [i.filename for i in on_archive] == ["s2.txt"]
    assert [i.filename for i in svc.listing(_within(study.e7), name="S1").items] == [
        "s1.txt"
    ]
    biggest = svc.listing(_within(study.e7), sort="-size").items
    assert [i.filename for i in biggest] == ["s2.txt", "s1.txt"]
    # The summary still shows every place, so another can be picked.
    assert len(svc.listing(_within(study.e7), place="archive").summary) == 2


def test_a_drive_that_cant_be_read_is_its_own_place(ctx, study, spread, archive):  # noqa: F811
    _unplug(archive)
    listing = ctx.file_access_svc.listing(_within(study.e7), place="unreachable")
    assert [i.filename for i in listing.items] == ["s2.txt"]
    (gone,) = [p for p in listing.summary if p.kind == "unreachable"]
    assert gone.place == "archive" and gone.reason


def test_moving_names_only_what_is_elsewhere_and_reachable(ctx, study, spread, archive):  # noqa: F811
    svc = ctx.file_access_svc
    _, items = svc.chosen(_within(study.e7))
    s1 = next(i for i in items if i.filename == "s1.txt")
    assert svc.to_move(items, "archive")[:2] == ([s1.sha256], 0)  # s2 is there
    _unplug(archive)
    _, items = svc.chosen(_within(study.e7))
    assert svc.to_move(items, "default")[:2] == ([], 0)  # s2 can't be read


def test_files_are_picked_by_kind_and_every_kind_is_still_counted(ctx, study, spread):  # noqa: F811
    notes = study.file(b"field notes", "notes.txt")
    ctx.record_svc.update(str(study.e7.id), {"name": "Encounter 7", "notes": notes})
    ctx.commit()
    svc = ctx.file_access_svc
    every = svc.listing(_within(study.e7))
    assert {k["field"]: k["files"] for k in every.kinds} == {"table": 2, "notes": 1}

    tables = _within(study.e7)
    tables.fields = ["table"]
    listing = svc.listing(tables)
    assert sorted(i.filename for i in listing.items) == ["s1.txt", "s2.txt"]
    assert sum(p.files for p in listing.summary) == 2  # where the tables are
    assert len(listing.kinds) == 2  # the other kind can still be picked
    _, picked = svc.chosen(tables)
    assert {i.field for i in picked} == {"table"}  # and actions take the same


def test_records_beneath_count_only_if_they_match_the_filter_at_their_level(
    ctx,
    study,
    spread,  # noqa: F811
):
    """Encounters "with a Selection named s1" take that Selection's files, not
    every Selection's: a record beneath is taken when the list, run for its
    kind with the same filter, would list it."""
    svc = ctx.file_access_svc
    selection = FileSelection(
        query=RecordQuery(
            dataset="hb",
            schema="encounter",
            filter_tree={
                "and": [
                    {"schema": "selection", "field": "sname", "op": "eq", "value": "s1"}
                ]
            },
        ),
        below=True,
    )
    _, items = svc.chosen(selection)
    assert [i.filename for i in items] == ["s1.txt"]

    no_filter = FileSelection(
        query=RecordQuery(dataset="hb", schema="encounter"), below=True
    )
    _, items = svc.chosen(no_filter)
    assert sorted(i.filename for i in items) == ["s1.txt", "s2.txt"]


def test_a_file_other_records_use_stays_put_unless_asked(ctx, study, archive):  # noqa: F811
    """Moving one record's files leaves a file other records also use where
    it is (moving it would move it for them too), unless asked."""
    svc = ctx.file_access_svc
    shared = study.selection(study.rec_a, "s1", b"the same table")
    study.selection(study.rec_b, "s2", b"the same table")  # same content
    own = study.selection(study.rec_a, "s3", b"only s3's")
    ctx.commit()
    only_a = _within(study.rec_a)
    _, items = svc.chosen(only_a)
    listing = svc.listing(only_a)
    assert {i.filename: listing.others[i.path] for i in listing.items} == {
        "s1.txt": 1,
        "s3.txt": 0,
    }

    plan = svc.plan_move(items, "archive")
    assert (plan.files, plan.shared_left) == (2 - 1, 1)
    shas, _, _ = svc.to_move(items, "archive")
    assert len(shas) == 1  # only s3's own file

    with_shared = svc.plan_move(items, "archive", include_shared=True)
    assert (with_shared.files, with_shared.shared_left) == (2, 0)
    assert shared and own


def test_ticked_rows_pick_those_records_files_not_every_record_sharing_them(
    ctx, study, archive  # noqa: F811
):
    """Two records use one file; ticking one row picks that record's file
    only, so the other record's makes it "shared with records not picked"."""
    svc = ctx.file_access_svc
    study.selection(study.rec_a, "s1", b"the same table")
    study.selection(study.rec_b, "s2", b"the same table")
    ctx.commit()
    everything = _within(study.e7)
    rows = svc.listing(everything).items
    assert len(rows) == 2 and rows[0].sha256 == rows[1].sha256

    _, picked = svc.chosen(everything, paths=[rows[0].path])
    assert len(picked) == 1
    plan = svc.plan_move(picked, "archive")
    assert (plan.files, plan.shared_left) == (0, 1)  # stays: rec_b uses it
