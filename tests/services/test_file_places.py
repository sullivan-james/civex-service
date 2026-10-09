"""Where a selection's files are, by place, and picking files by place and
name for the Files tab and its actions."""

from __future__ import annotations

import pytest

from civex.domain.file_access import FileSelection, copy_key
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
    study,  # noqa: F811
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


def test_a_file_other_records_use_is_copied_for_the_picked_ones(ctx, study, archive):  # noqa: F811
    """Every file picked goes, and only the picked records' copies move: a
    copy other records point at stays (copied, not moved), so they keep it
    where it is. The listing says who else uses it."""
    svc = ctx.file_access_svc
    study.selection(study.rec_a, "s1", b"the same table")
    study.selection(study.rec_b, "s2", b"the same table")  # same content
    study.selection(study.rec_a, "s3", b"only s3's")
    ctx.commit()
    only_a = _within(study.rec_a)
    _, items = svc.chosen(only_a)
    listing = svc.listing(only_a)
    assert {i.filename: listing.others[copy_key(i)] for i in listing.items} == {
        "s1.txt": 1,
        "s3.txt": 0,
    }

    plan = svc.plan_move(items, "archive")
    assert (plan.files, plan.copied) == (2, 1)  # s1 stays for rec_b
    shas, _, _ = svc.to_move(items, "archive")
    assert len(shas) == 2


def test_a_shared_file_its_home_keeps_is_copied(ctx, study, archive):  # noqa: F811
    """On a drive that is the home of a collection using it, a picked file is
    copied, not moved: the home keeps it."""
    svc = ctx.file_access_svc
    home = str(study.collection.id)  # its home is the archive drive
    study.selection(study.rec_a, "s1", b"the same table", on=home)
    study.selection(study.rec_b, "s2", b"the same table", on=home)
    ctx.commit()
    _, items = svc.chosen(_within(study.rec_a))

    plan = svc.plan_move(items, "default")

    assert (plan.files, plan.copied) == (1, 1)
    shas, _, _ = svc.to_move(items, "default")
    assert len(shas) == 1


def test_a_move_says_what_it_is_doing_while_it_works_it_out(ctx, study, archive):  # noqa: F811
    """The move request reports each stage, so "Preparing the move" shows
    what it is busy with instead of an empty bar."""
    stages: list[str] = []

    class Seen:
        def phase(self, label, total=0, total_bytes=0):
            stages.append(label)

        def __getattr__(self, name):
            return lambda *a, **k: None

    study.selection(study.rec_a, "s1", b"one", on=str(study.collection.id))
    ctx.commit()
    svc = ctx.file_access_svc
    _, items = svc.chosen(_within(study.rec_a), progress=Seen())
    svc.to_move(items, "default", Seen())

    assert stages[0] != "Working out what moves"  # finding the files came first
    assert "Working out what moves" in stages


def test_a_file_several_records_use_is_one_row_and_one_file(ctx, study, archive):  # noqa: F811
    """Rows are files as stored: two records using one file are one row (both
    named in `uses`), counted once, and ticking it picks both uses."""
    svc = ctx.file_access_svc
    study.selection(study.rec_a, "s1", b"the same table")
    study.selection(study.rec_b, "s2", b"the same table")
    ctx.commit()
    everything = _within(study.e7)
    listing = svc.listing(everything)
    (row,) = listing.items
    assert listing.total == 1
    assert sum(p.files for p in listing.summary) == 1
    assert sorted(u.filename for u in listing.uses[copy_key(row)]) == [
        "s1.txt",
        "s2.txt",
    ]
    assert listing.others[copy_key(row)] == 0

    _, picked = svc.chosen(everything, shas=[row.sha256])
    assert len(picked) == 2
    assert svc.plan_move(picked, "archive").files == 1  # one stored file


def test_files_are_picked_by_how_many_records_use_them(ctx, study, archive):  # noqa: F811
    """`used_by` keeps files used by exactly that many live records, and the
    listing counts the files by it (its choices), before narrowing by it."""
    svc = ctx.file_access_svc
    study.selection(study.rec_a, "s1", b"the same table")
    study.selection(study.rec_b, "s2", b"the same table")
    study.selection(study.rec_a, "s3", b"only s3's")
    ctx.commit()
    everything = _within(study.e7)
    listing = svc.listing(everything, used_by=[2])
    assert [len(listing.uses[copy_key(i)]) for i in listing.items] == [2]
    assert listing.sharing == [{"records": 1, "files": 1}, {"records": 2, "files": 1}]
    _, picked = svc.chosen(everything, used_by=[1])  # actions follow the list
    assert [i.filename for i in picked] == ["s3.txt"]


def test_a_files_info_names_every_record_that_uses_it(ctx, study):  # noqa: F811
    study.selection(study.rec_a, "s1", b"the same table")
    study.selection(study.rec_b, "s2", b"the same table")
    ctx.commit()
    (row,) = ctx.file_access_svc.listing(_within(study.e7)).items
    info = ctx.file_info_svc.info(row.sha256)
    assert info.records == 2
    assert sorted(u.name for u in info.uses) == ["s1", "s2"]
    assert all(u.trail for u in info.uses)  # the records above each


def test_a_records_list_of_what_it_contains_can_take_its_own_files_too(
    ctx,
    study,  # noqa: F811
):
    """A record's Contains tab lists its children; its files there are theirs
    and, with `with_within`, the record's own (as the record's storage line
    counts them)."""
    import dataclasses

    ctx.schema_svc.add_field("recording", "audio", "file")
    study.selection(study.rec_a, "s1", b"one")
    ctx.commit()
    rec_a = ctx.record_svc.get(str(study.rec_a.id))
    ctx.record_svc.update(
        str(rec_a.id),
        {**rec_a.data, "audio": study.file(b"the recording", "rec.wav")},
    )
    ctx.commit()
    children = FileSelection(
        query=RecordQuery(schema="selection", within=str(study.rec_a.id)),
        below=True,
    )
    svc = ctx.file_access_svc
    assert [i.filename for i in svc.listing(children).items] == ["s1.txt"]
    both = dataclasses.replace(children, with_within=True)
    assert sorted(i.filename for i in svc.listing(both).items) == ["rec.wav", "s1.txt"]
    everything = svc.listing(_within(study.rec_a)).total
    assert svc.listing(both).total == everything


def test_moving_onto_a_drive_that_has_the_content_copies_nothing(
    ctx, study, archive  # noqa: F811
):
    """De-duplication: s2's records point at a copy on the archive, and the
    project drive already holds the same content (s1's). Moving s2 there copies
    nothing: its record points at that copy, and the archive copy, used by
    nothing any more, is freed. The preview says exactly that first."""
    from civex.services.transfer_engine import run_transfer

    svc = ctx.file_access_svc
    study.selection(study.rec_a, "s1", b"the same bytes")  # on default
    s2 = study.selection(
        study.rec_b, "s2", b"the same bytes", on=str(study.collection.id)
    )  # its own copy, on the archive (the collection's home)
    ctx.commit()
    store = ctx.file_svc._store
    sha = next(iter(store.copies_used([s2.id]).keys()))[1]
    assert store.copies_used([s2.id]) == {(s2.id, sha): "archive"}
    _, items = svc.chosen(_within(study.rec_b))

    plan = svc.plan_move(items, "default")

    assert (plan.files, plan.already_there, plan.repointed) == (0, 1, 1)
    assert plan.freed_bytes == len(b"the same bytes")

    shas, _, _ = svc.to_move(items, "default")
    outcome = run_transfer(
        store,
        svc.refs,
        svc.move_spec(shas, "default", [str(s2.id)]),
        progress=lambda p: None,
        commit=ctx.commit,
    )

    assert outcome.status == "completed"
    assert store.copies_used([s2.id]) == {(s2.id, sha): "default"}
    assert [v for v, _ in store.copies([sha])[sha]] == ["default"]  # archive freed
