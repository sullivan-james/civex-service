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
    assert svc.to_move(items, "archive") == [s1.sha256]  # s2 is there already
    _unplug(archive)
    _, items = svc.chosen(_within(study.e7))
    assert svc.to_move(items, "default") == []  # s2 can't be read to move
