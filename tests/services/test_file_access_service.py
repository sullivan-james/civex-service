"""Reaching files by name and hierarchy: planning a selection and exporting it.

The shape is the one the feature exists for: Encounter -> Recording -> Selection,
with selection tables (files) on the selections, some of them on a drive that can
be unplugged."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import event

from civex.context import AppContext
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.domain.file_access import (
    FilesScatteredError,
    FilesUnavailableError,
    FileSelection,
    LinksNotPossibleError,
)
from civex.domain.query import RecordQuery
from civex.domain.transfers import KIND_FILES, TransferSpec
from civex.repositories.local.file_ref_repo import LocalFileReferenceRepository
from civex.services.transfer_engine import run_transfer
from civex.services.file_access_service import MARKER, MISSING_NOTE


def _drive(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "mnt" / name
    path.mkdir(parents=True)
    return path


class Study:
    """Two encounters; Encounter 7 has recordings A and B with selection tables."""

    def __init__(self, ctx: AppContext, make_schema, make_collection, make_record):
        self.ctx = ctx
        make_schema("encounter", fields=[("name", "string"), ("notes", "file")])
        make_schema("recording", fields=[("rname", "string")], parent="encounter")
        make_schema(
            "selection",
            fields=[("sname", "string"), ("table", "file"), ("extra", "file_list")],
            parent="recording",
        )
        self.collection = make_collection("hb")
        self._make = make_record
        self.e7 = make_record("hb", "encounter", {"name": "Encounter 7"})
        self.e8 = make_record("hb", "encounter", {"name": "Encounter 8"})
        self.rec_a = self._child("recording", {"rname": "Recording A"}, self.e7)
        self.rec_b = self._child("recording", {"rname": "Recording B"}, self.e7)
        self.rec_c = self._child("recording", {"rname": "Recording C"}, self.e8)

    def _child(self, schema, data, parent):
        return self._make("hb", schema, data, parent_record_id=str(parent.id))

    def file(self, content: bytes, name: str, collection_id: str | None = None):
        return self.ctx.file_svc.store_bytes(content, name, collection_id).to_dict()

    def selection(self, parent, name: str, content: bytes, **kw) -> object:
        data = {"sname": name, "table": self.file(content, f"{name}.txt", kw.get("on"))}
        return self._child("selection", data, parent)


@pytest.fixture()
def study(ctx: AppContext, make_schema, make_collection, make_record) -> Study:
    return Study(ctx, make_schema, make_collection, make_record)


def _paths(plan) -> list[str]:
    return [i.path for i in plan.items]


def _sel(**kw) -> FileSelection:
    base = kw.pop("base", None)
    fields = kw.pop("fields", None)
    ids = kw.pop("record_ids", None)
    return FileSelection(
        query=RecordQuery(**kw), record_ids=ids, fields=fields, base=base
    )


def test_all_selection_tables_in_an_encounter_by_name_and_folder(
    ctx: AppContext, study: Study
) -> None:
    study.selection(study.rec_a, "s1", b"one")
    study.selection(study.rec_a, "s2", b"two")
    study.selection(study.rec_b, "s3", b"three")
    study.selection(study.rec_c, "other", b"elsewhere")  # another encounter

    plan = ctx.file_access_svc.plan(
        _sel(schema="selection", within=str(study.e7.id), fields=["table"])
    )

    # Paths start below the encounter the person is looking at.
    assert _paths(plan) == [
        "Recording A/s1/s1.txt",
        "Recording A/s2/s2.txt",
        "Recording B/s3/s3.txt",
    ]
    assert plan.complete and plan.total == 3


def test_from_a_collection_the_path_starts_at_the_top(
    ctx: AppContext, study: Study
) -> None:
    study.selection(study.rec_a, "s1", b"one")

    plan = ctx.file_access_svc.plan(_sel(dataset="hb", schema="selection"))

    assert _paths(plan) == ["Encounter 7/Recording A/s1/s1.txt"]


def test_everything_under_a_record_includes_its_own_files(
    ctx: AppContext, study: Study
) -> None:
    ctx.record_svc.update(
        str(study.e7.id),
        {"name": "Encounter 7", "notes": study.file(b"field notes", "notes.pdf")},
    )
    study.selection(study.rec_a, "s1", b"one")

    plan = ctx.file_access_svc.plan(_sel(within=str(study.e7.id)))

    assert sorted(_paths(plan)) == ["Recording A/s1/s1.txt", "notes.pdf"]


def test_ticked_rows_are_exactly_what_is_selected(
    ctx: AppContext, study: Study
) -> None:
    keep = study.selection(study.rec_a, "s1", b"one")
    study.selection(study.rec_a, "s2", b"two")

    plan = ctx.file_access_svc.plan(
        _sel(record_ids=[str(keep.id), "not-an-id"], base=str(study.e7.id))
    )

    assert _paths(plan) == ["Recording A/s1/s1.txt"]


def test_a_file_field_can_be_chosen_and_a_wrong_one_is_an_error(
    ctx: AppContext, study: Study
) -> None:
    rec = study.selection(study.rec_a, "s1", b"one")
    ctx.record_svc.update(
        str(rec.id),
        {
            "sname": "s1",
            "table": study.file(b"one", "s1.txt"),
            "extra": [study.file(b"x", "x.csv")],
        },
    )

    only_extra = ctx.file_access_svc.plan(
        _sel(schema="selection", within=str(study.e7.id), fields=["extra"])
    )
    with pytest.raises(ValidationError, match="nope"):
        ctx.file_access_svc.plan(
            _sel(schema="selection", within=str(study.e7.id), fields=["nope"])
        )

    assert _paths(only_extra) == ["Recording A/s1/x.csv"]


def test_a_missing_base_record_is_not_found(ctx: AppContext, study: Study) -> None:
    with pytest.raises(NotFoundError):
        ctx.file_access_svc.plan(_sel(dataset="hb", base="ffffffff"))


def test_recordings_with_the_same_name_get_separate_folders(
    ctx: AppContext, study: Study
) -> None:
    twin = study._child("recording", {"rname": "recording a"}, study.e7)
    study.selection(study.rec_a, "s1", b"one")
    study.selection(twin, "s2", b"two")

    plan = ctx.file_access_svc.plan(_sel(schema="selection", within=str(study.e7.id)))

    folders = sorted(p.split("/")[0] for p in _paths(plan))
    assert folders == [
        f"Recording A~{str(study.rec_a.id)[:8]}",
        f"recording a~{str(twin.id)[:8]}",
    ]


def test_two_different_files_with_one_name_in_a_folder_are_kept_apart(
    ctx: AppContext, study: Study
) -> None:
    rec = study.selection(study.rec_a, "s1", b"one")
    ctx.record_svc.update(
        str(rec.id),
        {
            "sname": "s1",
            "table": study.file(b"one", "s1.txt"),
            "extra": [study.file(b"different", "s1.txt"), study.file(b"one", "s1.txt")],
        },
    )

    plan = ctx.file_access_svc.plan(_sel(schema="selection", within=str(study.e7.id)))

    assert len(plan.items) == 2  # the repeat of identical content is dropped
    assert plan.duplicates_dropped == 1
    assert len({i.path for i in plan.items}) == 2


def test_the_plan_can_say_where_each_file_is_on_disk(
    ctx: AppContext, study: Study
) -> None:
    study.selection(study.rec_a, "s1", b"one")

    plan = ctx.file_access_svc.plan(
        _sel(schema="selection", within=str(study.e7.id)), with_sources=True
    )

    assert Path(plan.items[0].source).read_bytes() == b"one"


def test_a_big_selection_costs_a_fixed_number_of_queries(
    ctx: AppContext, study: Study
) -> None:
    def count_for(n: int) -> int:
        for i in range(n):
            study.selection(study.rec_a, f"s{n}-{i}", f"c{n}-{i}".encode())
        ctx.commit()
        statements: list[str] = []
        engine = ctx._session.get_bind()

        def count(conn, cursor, statement, *args):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", count)
        try:
            ctx.file_access_svc.plan(_sel(schema="selection", within=str(study.e7.id)))
        finally:
            event.remove(engine, "before_cursor_execute", count)
        return len(statements)

    few = count_for(3)
    many = count_for(30)

    assert many == few  # not a query per record, per file or per ancestor


# -- layouts: a folder per record, or everything in one ---------------------------------


def test_a_flat_layout_puts_every_file_in_one_folder(
    ctx: AppContext, study: Study
) -> None:
    study.selection(study.rec_a, "s1", b"one")
    study.selection(study.rec_b, "s2", b"two")

    plan = ctx.file_access_svc.plan(
        FileSelection(
            query=RecordQuery(schema="selection", within=str(study.e7.id)),
            layout="flat",
        )
    )

    assert _paths(plan) == ["s1.txt", "s2.txt"]


def test_flat_names_that_clash_keep_their_extension_and_stay_distinct(
    ctx: AppContext, study: Study
) -> None:
    # Two selections, both holding a file called table.txt, different content.
    for rec, text in ((study.rec_a, b"one"), (study.rec_b, b"two")):
        record = study.selection(rec, "x", text)
        ctx.record_svc.update(
            str(record.id), {"sname": "x", "table": study.file(text, "table.txt")}
        )

    plan = ctx.file_access_svc.plan(
        FileSelection(
            query=RecordQuery(schema="selection", within=str(study.e7.id)),
            layout="flat",
        )
    )

    assert len(set(_paths(plan))) == 2
    assert all(p.startswith("table~") and p.endswith(".txt") for p in _paths(plan))


def test_the_plan_says_where_each_records_file_is_even_when_a_repeat_was_dropped(
    ctx: AppContext, study: Study
) -> None:
    a = study.selection(study.rec_a, "s1", b"same")
    b = study.selection(study.rec_b, "s2", b"same")
    for record, name in ((a, "s1"), (b, "s2")):
        ctx.record_svc.update(
            str(record.id), {"sname": name, "table": study.file(b"same", "same.txt")}
        )

    plan = ctx.file_access_svc.plan(
        FileSelection(
            query=RecordQuery(schema="selection", within=str(study.e7.id)),
            layout="flat",
        )
    )

    assert _paths(plan) == ["same.txt"] and plan.duplicates_dropped == 1
    assert plan.paths_for(str(a.id), "table") == ["same.txt"]
    assert plan.paths_for(str(b.id), "table") == ["same.txt"]
    assert plan.paths_for("nobody", "table") == []


def test_a_layout_must_be_one_that_exists(ctx: AppContext, study: Study) -> None:
    with pytest.raises(ValidationError, match="layout"):
        ctx.file_access_svc.plan(
            FileSelection(query=RecordQuery(dataset="hb"), layout="spiral")
        )


def test_a_flat_plan_costs_no_ancestor_lookups(ctx: AppContext, study: Study) -> None:
    study.selection(study.rec_a, "s1", b"one")
    statements: list[str] = []
    engine = ctx._session.get_bind()

    def count(conn, cursor, statement, *a):
        statements.append(statement)

    selection = lambda layout: FileSelection(  # noqa: E731
        query=RecordQuery(schema="selection", within=str(study.e7.id)), layout=layout
    )
    event.listen(engine, "before_cursor_execute", count)
    try:
        ctx.file_access_svc.plan(selection("flat"))
        flat = len(statements)
        statements.clear()
        ctx.file_access_svc.plan(selection("tree"))
        tree = len(statements)
    finally:
        event.remove(engine, "before_cursor_execute", count)

    assert flat < tree


def test_the_missing_note_lists_what_could_not_be_reached(
    ctx: AppContext, study: Study, archive: Path
) -> None:
    study.selection(study.rec_a, "far", b"on archive", on=str(study.collection.id))
    selection = _sel(schema="selection", within=str(study.e7.id))
    assert ctx.file_access_svc.missing_note(ctx.file_access_svc.plan(selection)) is None
    _unplug(archive)

    note = ctx.file_access_svc.missing_note(ctx.file_access_svc.plan(selection))

    assert note is not None and "Recording A/far/far.txt" in note


# -- drives that are not there -------------------------------------------------


@pytest.fixture()
def archive(ctx: AppContext, study: Study, tmp_path_factory: pytest.TempPathFactory):
    """A second drive that is home to the collection's new files. It is outside
    the project folder, as a real external drive is."""
    drive = _drive(tmp_path_factory.mktemp("drives"), "archive")
    ctx.store_svc.add_volume("archive", str(drive))
    ctx.store_svc.set_placement(str(study.collection.id), "archive")
    return drive


def _unplug(drive: Path) -> Path:
    gone = drive.with_name(drive.name + "-unplugged")
    drive.rename(gone)
    return gone


def test_files_on_an_unplugged_drive_are_reported_before_anything_is_made(
    ctx: AppContext, study: Study, archive: Path, tmp_path: Path
) -> None:
    cid = str(study.collection.id)
    study.selection(study.rec_a, "near", b"on default")  # stored before? placement set
    study.selection(study.rec_a, "far", b"on archive", on=cid)
    _unplug(archive)

    plan = ctx.file_access_svc.plan(_sel(schema="selection", within=str(study.e7.id)))
    dest = tmp_path / "out"
    with pytest.raises(FilesUnavailableError) as raised:
        ctx.file_access_svc.export(
            _sel(schema="selection", within=str(study.e7.id)), dest
        )

    assert not plan.complete
    group = plan.unavailable[0]
    assert group.volume == "archive" and group.reason and group.fix
    assert group.records == [i.record_name for i in plan.items if not i.available][:10]
    assert "archive" in raised.value.plan.summary()
    assert not dest.exists()  # nothing was built


def test_going_ahead_without_them_leaves_a_note_and_a_later_run_completes_it(
    ctx: AppContext, study: Study, archive: Path, tmp_path: Path
) -> None:
    cid = str(study.collection.id)
    study.selection(study.rec_a, "near", b"on default")
    study.selection(study.rec_a, "far", b"on archive", on=cid)
    selection = _sel(schema="selection", within=str(study.e7.id))
    gone = _unplug(archive)
    dest = tmp_path / "out"

    first = ctx.file_access_svc.export(selection, dest, mode="copy", allow_partial=True)
    note = (dest / MISSING_NOTE).read_text()

    assert [i.path for i in first.missing] == ["Recording A/far/far.txt"]
    assert "Recording A/far/far.txt" in note and "archive" in note
    assert (dest / "Recording A" / "near" / "near.txt").read_bytes() == b"on default"
    assert not (dest / "Recording A" / "far" / "far.txt").exists()

    gone.rename(archive)
    second = ctx.file_access_svc.export(selection, dest, mode="copy")

    assert second.missing == [] and second.unchanged == 1 and second.written == 1
    assert (dest / "Recording A" / "far" / "far.txt").read_bytes() == b"on archive"
    assert not (dest / MISSING_NOTE).exists()


def test_a_copy_already_made_survives_the_drive_being_unplugged(
    ctx: AppContext, study: Study, archive: Path, tmp_path: Path
) -> None:
    cid = str(study.collection.id)
    study.selection(study.rec_a, "far", b"on archive", on=cid)
    selection = _sel(schema="selection", within=str(study.e7.id))
    dest = tmp_path / "out"
    ctx.file_access_svc.export(selection, dest, mode="copy")
    _unplug(archive)

    again = ctx.file_access_svc.export(selection, dest, mode="copy", allow_partial=True)

    assert again.unchanged == 1 and again.removed == 0
    assert (dest / "Recording A" / "far" / "far.txt").read_bytes() == b"on archive"


# -- export ----------------------------------------------------------------------


def test_export_builds_the_tree_and_updates_it_in_place(
    ctx: AppContext, study: Study, tmp_path: Path
) -> None:
    study.selection(study.rec_a, "s1", b"one")
    old = study.selection(study.rec_b, "s2", b"two")
    selection = _sel(schema="selection", within=str(study.e7.id))
    dest = tmp_path / "out"

    first = ctx.file_access_svc.export(selection, dest, mode="copy")
    assert first.copied == 2 and first.linked == 0
    assert (dest / "Recording B" / "s2" / "s2.txt").read_bytes() == b"two"

    ctx.record_svc.delete(str(old.id))
    study.selection(study.rec_a, "s3", b"three")
    second = ctx.file_access_svc.export(selection, dest, mode="copy")

    assert (second.copied, second.unchanged, second.removed) == (1, 1, 1)
    assert not (dest / "Recording B").exists()  # an emptied folder goes too
    assert (dest / "Recording A" / "s3" / "s3.txt").read_bytes() == b"three"
    assert (dest / MARKER).exists()


def test_export_leaves_a_folder_with_other_files_alone(
    ctx: AppContext, study: Study, tmp_path: Path
) -> None:
    study.selection(study.rec_a, "s1", b"one")
    dest = tmp_path / "mine"
    dest.mkdir()
    (dest / "thesis.docx").write_text("precious")

    with pytest.raises(ValidationError, match="other files"):
        ctx.file_access_svc.export(
            _sel(schema="selection", within=str(study.e7.id)), dest
        )

    assert (dest / "thesis.docx").read_text() == "precious"
    assert not (dest / "Recording A").exists()


def test_link_mode_makes_the_stored_file_itself_appear(
    ctx: AppContext, study: Study, tmp_path: Path
) -> None:
    study.selection(study.rec_a, "s1", b"one")
    dest = tmp_path / "out"

    result = ctx.file_access_svc.export(
        _sel(schema="selection", within=str(study.e7.id)), dest, mode="link"
    )

    plan = ctx.file_access_svc.plan(
        _sel(schema="selection", within=str(study.e7.id)), with_sources=True
    )
    assert result.linked == 1 and result.copied == 0
    assert os.path.samefile(
        dest / "Recording A" / "s1" / "s1.txt", plan.items[0].source
    )


def _only_sha(ctx: AppContext, study: Study) -> str:
    plan = ctx.file_access_svc.plan(_sel(schema="selection", within=str(study.e7.id)))
    return plan.items[0].sha256


def test_link_is_the_default_and_the_link_is_the_stored_file(
    ctx: AppContext, study: Study, tmp_path: Path
) -> None:
    study.selection(study.rec_a, "s1", b"one")
    dest = tmp_path / "out"

    result = ctx.file_access_svc.export(
        _sel(schema="selection", within=str(study.e7.id)), dest
    )

    plan = ctx.file_access_svc.plan(
        _sel(schema="selection", within=str(study.e7.id)), with_sources=True
    )
    assert (result.linked, result.copied) == (1, 0)
    assert os.path.samefile(
        dest / "Recording A" / "s1" / "s1.txt", plan.items[0].source
    )


def test_copy_mode_makes_copies_that_can_be_edited_safely(
    ctx: AppContext, study: Study, tmp_path: Path
) -> None:
    study.selection(study.rec_a, "s1", b"one")
    dest = tmp_path / "out"

    result = ctx.file_access_svc.export(
        _sel(schema="selection", within=str(study.e7.id)), dest, mode="copy"
    )
    (dest / "Recording A" / "s1" / "s1.txt").write_text("edited")

    assert result.copied == 1
    assert ctx.file_svc.retrieve(_only_sha(ctx, study)) == b"one"


def test_a_folder_that_cannot_hold_links_is_refused_before_anything_is_built(
    ctx: AppContext, study: Study, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study.selection(study.rec_a, "s1", b"one")

    def refuse(*a, **k):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr("civex.services.file_access_service.os.link", refuse)
    dest = tmp_path / "out"

    with pytest.raises(LinksNotPossibleError, match="Copy the files"):
        ctx.file_access_svc.export(
            _sel(schema="selection", within=str(study.e7.id)), dest
        )

    assert not dest.exists()  # the probe leaves nothing behind either


def test_a_bad_mode_is_refused(ctx: AppContext, study: Study, tmp_path: Path) -> None:
    for mode in ("move", "auto"):
        with pytest.raises(ValidationError, match="mode"):
            ctx.file_access_svc.export(_sel(dataset="hb"), tmp_path / "x", mode=mode)


def test_changing_how_a_folder_is_made_remakes_its_files(
    ctx: AppContext, study: Study, tmp_path: Path
) -> None:
    study.selection(study.rec_a, "s1", b"one")
    selection = _sel(schema="selection", within=str(study.e7.id))
    dest = tmp_path / "out"
    ctx.file_access_svc.export(selection, dest, mode="copy")

    again = ctx.file_access_svc.export(selection, dest, mode="link")

    assert (again.linked, again.copied, again.unchanged) == (1, 0, 0)


# -- where exports go: one drive, links or copies ---------------------------------


def _both_drives(ctx: AppContext, study: Study, archive: Path) -> FileSelection:
    """Selection tables on two drives: one on the default, one on archive."""
    study.selection(study.rec_a, "near", b"on default")
    study.selection(study.rec_a, "far", b"on archive", on=str(study.collection.id))
    return _sel(schema="selection", within=str(study.e7.id))


def test_files_on_several_drives_cannot_be_gathered_into_a_linked_folder(
    ctx: AppContext, study: Study, archive: Path, tmp_path: Path
) -> None:
    selection = _both_drives(ctx, study, archive)

    plan = ctx.file_access_svc.plan(selection)
    with pytest.raises(FilesScatteredError, match="2 drives"):
        ctx.file_access_svc.export_managed(selection, "tables")
    with pytest.raises(FilesScatteredError):
        ctx.file_access_svc.export(selection, tmp_path / "out")

    assert plan.scattered and plan.link_volume is None
    assert {v.volume for v in plan.by_volume} == {"default", "archive"}
    assert not (tmp_path / "out").exists()
    assert not (archive / "_exports").exists()


def test_the_same_files_can_be_copied_onto_one_drive(
    ctx: AppContext, study: Study, archive: Path
) -> None:
    selection = _both_drives(ctx, study, archive)

    result = ctx.file_access_svc.export_managed(
        selection, "tables", mode="copy", volume="archive"
    )

    dest = archive / "_exports" / "tables"
    assert result.dest == str(dest) and result.location == "archive"
    assert result.copied == 2 and result.linked == 0
    assert (dest / "Recording A" / "near" / "near.txt").read_bytes() == b"on default"
    assert (dest / "Recording A" / "far" / "far.txt").read_bytes() == b"on archive"


def test_a_copy_with_no_drive_named_goes_in_the_project(
    ctx: AppContext, study: Study, project_dir: Path
) -> None:
    study.selection(study.rec_a, "s1", b"one")

    result = ctx.file_access_svc.export_managed(
        _sel(schema="selection", within=str(study.e7.id)), "tables", mode="copy"
    )

    assert result.dest == str(project_dir / "_civex" / "exports" / "tables")
    assert result.location == "project"


def test_a_linked_folder_goes_on_the_drive_that_holds_the_files(
    ctx: AppContext, study: Study, archive: Path
) -> None:
    study.selection(study.rec_a, "far", b"on archive", on=str(study.collection.id))
    selection = _sel(schema="selection", within=str(study.e7.id))

    result = ctx.file_access_svc.export_managed(selection, "tables")

    plan = ctx.file_access_svc.plan(selection, with_sources=True)
    linked = archive / "_exports" / "tables" / "Recording A" / "far" / "far.txt"
    assert result.location == "archive" and result.linked == 1
    assert os.path.samefile(linked, plan.items[0].source)


def test_files_in_the_project_get_a_linked_folder_in_the_project(
    ctx: AppContext, study: Study, project_dir: Path
) -> None:
    study.selection(study.rec_a, "s1", b"one")

    result = ctx.file_access_svc.export_managed(
        _sel(schema="selection", within=str(study.e7.id)), "tables"
    )

    assert result.dest == str(project_dir / "_civex" / "exports" / "tables")
    assert result.location == "project" and result.linked == 1


def test_a_copy_that_will_not_fit_is_refused_and_says_by_how_much(
    ctx: AppContext, study: Study, archive: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study.selection(study.rec_a, "s1", b"x" * 5000)
    monkeypatch.setattr(ctx.file_access_svc._store, "room_on", lambda volume: 100)

    with pytest.raises(ValidationError, match="Not enough room"):
        ctx.file_access_svc.export_managed(
            _sel(schema="selection", within=str(study.e7.id)),
            "tables",
            mode="copy",
            volume="archive",
        )

    assert not (archive / "_exports").exists()


def test_a_drive_that_cannot_be_written_to_is_not_a_target(
    ctx: AppContext, study: Study, archive: Path
) -> None:
    study.selection(study.rec_a, "s1", b"one")
    ctx.store_svc.set_volume_state("archive", "readonly")
    selection = _sel(schema="selection", within=str(study.e7.id))

    with pytest.raises(LinksNotPossibleError, match="archive"):
        ctx.file_access_svc.export_managed(
            selection, "t", mode="copy", volume="archive"
        )
    with pytest.raises(NotFoundError, match="nowhere"):
        ctx.file_access_svc.export_managed(
            selection, "t", mode="copy", volume="nowhere"
        )


def test_an_exports_folder_inside_a_drive_is_invisible_to_the_object_scan(
    ctx: AppContext, study: Study, archive: Path
) -> None:
    selection = _both_drives(ctx, study, archive)
    before = {o.sha256 for o in ctx.file_svc._store.iter_volume_objects("archive")}

    ctx.file_access_svc.export_managed(
        selection, "tables", mode="copy", volume="archive"
    )

    after = {o.sha256 for o in ctx.file_svc._store.iter_volume_objects("archive")}
    assert after == before and len(before) == 1  # the copies are not objects


# -- gathering just a selection onto one drive ----------------------------------------


def test_a_move_names_only_what_is_not_on_the_drive_already(
    ctx: AppContext, study: Study, archive: Path
) -> None:
    selection = _both_drives(ctx, study, archive)
    plan = ctx.file_access_svc.plan(selection)

    shas, _ = ctx.file_access_svc.to_move(plan.items, "archive")

    on_default = [i.sha256 for i in plan.items if i.volume == "default"]
    assert shas == on_default and len(shas) == 1
    with pytest.raises(NotFoundError):
        ctx.file_access_svc.to_move(plan.items, "nowhere")


def test_gathering_the_selection_makes_it_linkable_without_moving_anything_else(
    ctx: AppContext, study: Study, archive: Path
) -> None:
    selection = _both_drives(ctx, study, archive)
    # Same collection, another encounter: not in the selection, so it must not move.
    bystander = study.selection(study.rec_c, "other", b"not selected")
    assert ctx.file_access_svc.plan(selection).scattered
    shas, _ = ctx.file_access_svc.to_move(
        ctx.file_access_svc.plan(selection).items, "archive"
    )

    outcome = run_transfer(
        ctx.file_svc._store,
        LocalFileReferenceRepository(ctx._session),
        TransferSpec(kind=KIND_FILES, targets=["archive"], shas=shas),
        progress=lambda p: None,
        commit=ctx.commit,
    )
    plan = ctx.file_access_svc.plan(selection)
    result = ctx.file_access_svc.export_managed(selection, "tables")

    assert outcome.status == "completed"
    assert not plan.scattered and plan.link_volume == "archive"
    assert result.location == "archive" and result.linked == 2
    # A file in the same collection that wasn't selected did not move.
    rest = ctx.file_access_svc.plan(_sel(record_ids=[str(bystander.id)]))
    assert rest.items[0].volume == "default"


# -- looking after exports ---------------------------------------------------------


def test_exports_are_listed_wherever_they_were_made(
    ctx: AppContext, study: Study, archive: Path
) -> None:
    selection = _both_drives(ctx, study, archive)
    ctx.file_access_svc.export_managed(
        selection, "copies", mode="copy", volume="archive"
    )
    only_far = study.selection(
        study.rec_b, "far2", b"more archive", on=str(study.collection.id)
    )
    ctx.file_access_svc.export_managed(_sel(record_ids=[str(only_far.id)]), "links")

    listed = {e.name: e for e in ctx.file_access_svc.list_exports()}

    assert listed["copies"].location == "archive"
    assert (listed["copies"].files, listed["copies"].copied) == (2, 2)
    assert listed["copies"].bytes_on_disk == len(b"on default") + len(b"on archive")
    assert listed["copies"].updated
    # Links take no space.
    assert listed["links"].location == "archive"
    assert listed["links"].linked == listed["links"].files == 1
    assert listed["links"].bytes_on_disk == 0


def test_listing_an_export_made_before_sizes_were_recorded_says_so(
    ctx: AppContext, project_dir: Path
) -> None:
    old = project_dir / "_civex" / "exports" / "old"
    old.mkdir(parents=True)
    (old / "a.txt").write_text("x")
    (old / MARKER).write_text(json.dumps({"files": {"a.txt": "ab" * 32}}))

    (info,) = ctx.file_access_svc.list_exports()

    assert (info.name, info.files) == ("old", 1)
    assert info.bytes_on_disk is None and info.linked is None


def test_a_folder_without_the_marker_is_not_listed(
    ctx: AppContext, project_dir: Path
) -> None:
    (project_dir / "_civex" / "exports" / "someones-folder").mkdir(parents=True)

    assert ctx.file_access_svc.list_exports() == []


def test_removing_a_linked_export_leaves_the_stored_file_alone(
    ctx: AppContext, study: Study
) -> None:
    study.selection(study.rec_a, "s1", b"one")
    result = ctx.file_access_svc.export_managed(
        _sel(schema="selection", within=str(study.e7.id)), "tables"
    )

    removed = ctx.file_access_svc.remove_export(result.dest)

    assert (removed.removed_files, removed.freed_bytes) == (1, 0)
    assert removed.folder_removed and not Path(result.dest).exists()
    assert ctx.file_svc.retrieve(_only_sha(ctx, study)) == b"one"
    assert ctx.file_access_svc.list_exports() == []


def test_removing_a_copied_export_gives_the_space_back(
    ctx: AppContext, study: Study
) -> None:
    study.selection(study.rec_a, "s1", b"one")
    result = ctx.file_access_svc.export_managed(
        _sel(schema="selection", within=str(study.e7.id)), "tables", mode="copy"
    )

    removed = ctx.file_access_svc.remove_export(result.dest)

    assert removed.freed_bytes == 3 and removed.folder_removed
    # The export folder's parent stays; only the export went.
    assert Path(result.dest).parent.exists()


def test_removing_an_export_keeps_what_the_user_added(
    ctx: AppContext, study: Study
) -> None:
    study.selection(study.rec_a, "s1", b"one")
    result = ctx.file_access_svc.export_managed(
        _sel(schema="selection", within=str(study.e7.id)), "tables", mode="copy"
    )
    mine = Path(result.dest) / "my notes.txt"
    mine.write_text("mine")

    removed = ctx.file_access_svc.remove_export(result.dest)

    assert removed.kept_files == 1 and not removed.folder_removed
    assert mine.read_text() == "mine"
    assert not (Path(result.dest) / "Recording A").exists()
    assert not (Path(result.dest) / MARKER).exists()


def test_removing_a_symlink_export_removes_the_link_not_what_it_points_at(
    ctx: AppContext, project_dir: Path, tmp_path: Path
) -> None:
    """An export made by an earlier version: symbolic links."""
    real = tmp_path / "precious.wav"
    real.write_bytes(b"recording")
    folder = project_dir / "_civex" / "exports" / "old"
    (folder / "A").mkdir(parents=True)
    (folder / "A" / "x.wav").symlink_to(real)
    (folder / MARKER).write_text(json.dumps({"files": {"A/x.wav": "ab" * 32}}))

    removed = ctx.file_access_svc.remove_export(folder)

    assert removed.removed_files == 1 and removed.folder_removed
    assert real.read_bytes() == b"recording"


def test_removal_never_follows_a_path_in_an_edited_marker(
    ctx: AppContext, project_dir: Path, tmp_path: Path
) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    folder = project_dir / "_civex" / "exports" / "evil"
    folder.mkdir(parents=True)
    escape_path = os.path.relpath(victim, folder).replace(os.sep, "/")
    (folder / MARKER).write_text(
        json.dumps({"files": {escape_path: "ab" * 32, "/etc/hostname": "ab" * 32}})
    )

    ctx.file_access_svc.remove_export(folder)

    assert victim.read_text() == "keep me"


def test_only_an_export_folder_can_be_removed(ctx: AppContext, tmp_path: Path) -> None:
    folder = tmp_path / "thesis"
    folder.mkdir()
    (folder / "chapter.docx").write_text("x")

    with pytest.raises(ValidationError, match="not a folder a civex export made"):
        ctx.file_access_svc.remove_export(folder)

    assert (folder / "chapter.docx").exists()


def test_zip_entries_use_the_same_paths_and_skip_what_cannot_be_reached(
    ctx: AppContext, study: Study, archive: Path
) -> None:
    cid = str(study.collection.id)
    study.selection(study.rec_a, "near", b"on default")
    study.selection(study.rec_a, "far", b"on archive", on=cid)
    _unplug(archive)

    plan = ctx.file_access_svc.plan(_sel(schema="selection", within=str(study.e7.id)))

    assert [n for n, _ in ctx.file_access_svc.zip_entries(plan)] == [
        "Recording A/near/near.txt"
    ]


# -- the record lookups the plan is built on ---------------------------------------


def test_get_many_keeps_the_order_asked_and_leaves_out_deleted_and_unknown(
    ctx: AppContext, study: Study
) -> None:
    a = study.selection(study.rec_a, "s1", b"one")
    b = study.selection(study.rec_a, "s2", b"two")
    gone = study.selection(study.rec_a, "s3", b"three")
    ctx.record_svc.delete(str(gone.id))

    got = ctx.record_svc.get_many([str(b.id), "junk", str(gone.id), str(a.id)])

    assert [r.id for r in got] == [b.id, a.id]
    assert got[0].data["table"]["location"]["volume"] == "default"


def test_ancestor_trails_are_root_first_and_named(
    ctx: AppContext, study: Study
) -> None:
    sel = study.selection(study.rec_a, "s1", b"one")

    trails = ctx.record_svc.ancestor_trails([sel, study.e7])

    assert [r.natural_name for r in trails[sel.id]] == ["Encounter 7", "Recording A"]
    assert trails[study.e7.id] == []


def test_path_on_is_arithmetic_and_does_not_touch_the_disk(
    ctx: AppContext, project_dir: Path
) -> None:
    sha = "ab" + "c" * 62

    path = ctx.file_svc._store.path_on(sha, "default")

    assert path.parent.name == "ab" and path.name == "c" * 62 and not path.exists()


# -- grouped: the folders above, the records that hold the files gathered ------------


def _grouped(**kw) -> FileSelection:
    return FileSelection(query=RecordQuery(**kw), layout="grouped")


def test_grouped_gathers_a_recordings_selections_into_one_folder(
    ctx: AppContext, study: Study
) -> None:
    study.selection(study.rec_a, "s1", b"one")
    study.selection(study.rec_a, "s2", b"two")
    study.selection(study.rec_b, "s3", b"three")

    inside = ctx.file_access_svc.plan(
        _grouped(schema="selection", within=str(study.e7.id))
    )
    top = ctx.file_access_svc.plan(_grouped(dataset="hb", schema="selection"))

    assert _paths(inside) == [
        "Recording A/Selections/s1.txt",
        "Recording A/Selections/s2.txt",
        "Recording B/Selections/s3.txt",
    ]
    assert "Encounter 7/Recording A/Selections/s1.txt" in _paths(top)


def test_grouped_keeps_the_base_records_own_files_at_the_top(
    ctx: AppContext, study: Study
) -> None:
    ctx.record_svc.update(
        str(study.e7.id),
        {"name": "Encounter 7", "notes": study.file(b"field notes", "notes.pdf")},
    )
    study.selection(study.rec_a, "s1", b"one")

    plan = ctx.file_access_svc.plan(_grouped(within=str(study.e7.id)))

    assert sorted(_paths(plan)) == ["Recording A/Selections/s1.txt", "notes.pdf"]


def test_grouped_names_each_kind_of_record_by_its_label(
    ctx: AppContext, make_schema, make_collection, make_record
) -> None:
    make_schema("site", fields=[("name", "string")])
    make_schema(
        "contour_file",
        fields=[("cname", "string"), ("data", "file")],
        parent="site",
        label="Contour File",
    )
    make_collection("c")
    site = make_record("c", "site", {"name": "North"})
    ref = ctx.file_svc.store_bytes(b"x", "a.txt").to_dict()
    make_record(
        "c", "contour_file", {"cname": "k1", "data": ref}, parent_record_id=str(site.id)
    )

    plan = ctx.file_access_svc.plan(_grouped(dataset="c", schema="contour_file"))

    assert _paths(plan) == ["North/Contour Files/a.txt"]


def test_grouped_tells_clashing_names_apart_by_selection(
    ctx: AppContext, study: Study
) -> None:
    for name, text in (("s1", b"one"), ("s2", b"two")):
        record = study.selection(study.rec_a, name, text)
        ctx.record_svc.update(
            str(record.id), {"sname": name, "table": study.file(text, "table.txt")}
        )

    plan = ctx.file_access_svc.plan(
        _grouped(schema="selection", within=str(study.e7.id))
    )

    assert _paths(plan) == [
        "Recording A/Selections/s1 - table.txt",
        "Recording A/Selections/s2 - table.txt",
    ]


def test_flat_clashes_are_told_apart_by_the_owning_record_too(
    ctx: AppContext, study: Study
) -> None:
    for rec, name, text in ((study.rec_a, "s1", b"one"), (study.rec_b, "s2", b"two")):
        record = study.selection(rec, name, text)
        ctx.record_svc.update(
            str(record.id), {"sname": name, "table": study.file(text, "table.txt")}
        )

    plan = ctx.file_access_svc.plan(
        FileSelection(
            query=RecordQuery(schema="selection", within=str(study.e7.id)),
            layout="flat",
        )
    )

    assert _paths(plan) == ["s1 - table.txt", "s2 - table.txt"]


def test_only_one_kind_of_file_flat_from_everywhere_beneath_an_encounter(
    ctx: AppContext, study: Study
) -> None:
    """The case this exists for: just the contour files, in one folder, from every
    selection in an encounter (not the encounter's own notes, not other fields)."""
    ctx.record_svc.update(
        str(study.e7.id),
        {"name": "Encounter 7", "notes": study.file(b"field notes", "notes.pdf")},
    )
    a = study.selection(study.rec_a, "s1", b"one")
    ctx.record_svc.update(
        str(a.id),
        {
            "sname": "s1",
            "table": study.file(b"one", "contour1.txt"),
            "extra": [study.file(b"x", "other.csv")],
        },
    )
    study.selection(study.rec_b, "s2", b"two")

    plan = ctx.file_access_svc.plan(
        FileSelection(
            query=RecordQuery(within=str(study.e7.id)),
            fields=["table"],
            layout="flat",
        )
    )

    assert sorted(_paths(plan)) == ["contour1.txt", "s2.txt"]


# -- what an export folder's metadata says about itself ----------------------------------


def test_the_metadata_names_the_civex_that_made_it_and_the_format_of_the_file(
    ctx: AppContext, study: Study, tmp_path: Path
) -> None:
    from civex import __version__

    study.selection(study.rec_a, "s1", b"one")
    dest = tmp_path / "out"

    ctx.file_access_svc.export(
        _sel(schema="selection", within=str(study.e7.id)), dest, mode="copy"
    )
    data = json.loads((dest / MARKER).read_text())

    assert data["civex_version"] == __version__
    # `format` is the layout of this file; there is no bare "version" to mistake
    # for civex's own.
    assert data["format"] == 2 and "version" not in data
    assert data["mode"] == "copy" and data["made_by"] == "civex"


def test_the_time_is_zulu_to_the_second(
    ctx: AppContext, study: Study, tmp_path: Path
) -> None:
    import re

    study.selection(study.rec_a, "s1", b"one")
    dest = tmp_path / "out"

    ctx.file_access_svc.export(
        _sel(schema="selection", within=str(study.e7.id)), dest, mode="copy"
    )
    updated = json.loads((dest / MARKER).read_text())["updated"]

    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", updated), updated


def test_any_moment_is_written_in_utc() -> None:
    from datetime import datetime, timedelta, timezone

    from civex.services.file_access_service import _zulu

    five_ahead = timezone(timedelta(hours=5))

    assert _zulu(datetime(2026, 1, 1, 12, 0, 30, 999999, tzinfo=five_ahead)) == (
        "2026-01-01T07:00:30Z"
    )
    assert _zulu(datetime(2026, 1, 1, tzinfo=timezone.utc)) == "2026-01-01T00:00:00Z"


def test_an_export_made_before_the_change_is_still_read_and_listed(
    ctx: AppContext, project_dir: Path
) -> None:
    old = project_dir / "_civex" / "exports" / "old"
    old.mkdir(parents=True)
    (old / "a.txt").write_text("x")
    (old / MARKER).write_text(
        json.dumps(
            {
                "made_by": "civex",
                "version": 2,
                "updated": "2026-10-05T21:50:38.587021+00:00",
                "files": {"a.txt": {"sha": "ab" * 32, "how": "copied", "size": 1}},
            }
        )
    )

    (info,) = ctx.file_access_svc.list_exports()

    assert info.name == "old" and info.copied == 1
    assert info.updated == "2026-10-05T21:50:38.587021+00:00"  # shown as it was written


# -- "these records, and everything beneath them" ----------------------------------------


def _below(**kw) -> FileSelection:
    return FileSelection(query=RecordQuery(**kw), below=True, **{})


def test_a_list_of_encounters_has_no_files_of_its_own_but_its_contents_do(
    ctx: AppContext, study: Study
) -> None:
    study.selection(study.rec_a, "s1", b"one")
    study.selection(study.rec_b, "s2", b"two")

    alone = ctx.file_access_svc.plan(_sel(dataset="hb", schema="encounter"))
    with_contents = ctx.file_access_svc.plan(_below(dataset="hb", schema="encounter"))

    assert alone.items == []
    assert _paths(with_contents) == [
        "Encounter 7/Recording A/s1/s1.txt",
        "Encounter 7/Recording B/s2/s2.txt",
    ]


def test_the_filter_that_narrows_the_encounters_narrows_what_is_taken(
    ctx: AppContext, study: Study
) -> None:
    study.selection(study.rec_a, "s1", b"one")
    study.selection(study.rec_c, "other", b"elsewhere")  # in Encounter 8

    plan = ctx.file_access_svc.plan(
        FileSelection(
            query=RecordQuery(dataset="hb", schema="encounter", search="Encounter 7"),
            below=True,
        )
    )

    assert _paths(plan) == ["Encounter 7/Recording A/s1/s1.txt"]


def test_ticked_rows_can_take_their_contents_too(ctx: AppContext, study: Study) -> None:
    study.selection(study.rec_a, "s1", b"one")
    study.selection(study.rec_c, "other", b"elsewhere")

    plan = ctx.file_access_svc.plan(
        FileSelection(query=RecordQuery(), record_ids=[str(study.e8.id)], below=True)
    )

    assert _paths(plan) == ["Encounter 8/Recording C/other/other.txt"]


def test_the_contents_can_be_narrowed_to_one_field_and_laid_out_flat(
    ctx: AppContext, study: Study
) -> None:
    a = study.selection(study.rec_a, "s1", b"one")
    ctx.record_svc.update(
        str(a.id),
        {
            "sname": "s1",
            "table": study.file(b"one", "contour1.txt"),
            "extra": [study.file(b"x", "other.csv")],
        },
    )

    plan = ctx.file_access_svc.plan(
        FileSelection(
            query=RecordQuery(dataset="hb", schema="encounter"),
            fields=["table"],
            layout="flat",
            below=True,
        )
    )

    assert _paths(plan) == ["contour1.txt"]


def test_what_was_deleted_is_not_taken(ctx: AppContext, study: Study) -> None:
    keep = study.selection(study.rec_a, "keep", b"keep")
    gone = study.selection(study.rec_a, "gone", b"gone")
    ctx.record_svc.delete(str(gone.id))

    plan = ctx.file_access_svc.plan(_below(dataset="hb", schema="encounter"))

    assert [i.record_id for i in plan.items] == [str(keep.id)]


def test_a_record_already_in_the_selection_is_not_taken_twice(
    ctx: AppContext, study: Study
) -> None:
    study.selection(study.rec_a, "s1", b"one")

    inside = ctx.file_access_svc.plan(
        FileSelection(query=RecordQuery(within=str(study.e7.id)), below=True)
    )

    assert _paths(inside) == ["Recording A/s1/s1.txt"]


def test_going_beneath_costs_a_query_a_level_not_a_query_a_record(
    ctx: AppContext, study: Study
) -> None:
    def statements() -> int:
        seen: list[str] = []
        engine = ctx._session.get_bind()

        def count(conn, cursor, statement, *a):
            seen.append(statement)

        event.listen(engine, "before_cursor_execute", count)
        try:
            ctx.file_access_svc.plan(_below(dataset="hb", schema="encounter"))
        finally:
            event.remove(engine, "before_cursor_execute", count)
        return len(seen)

    for i in range(3):
        study.selection(study.rec_a, f"a{i}", f"a{i}".encode())
    few = statements()
    for i in range(30):
        study.selection(study.rec_b, f"b{i}", f"b{i}".encode())
    many = statements()

    assert many == few


def test_the_contents_stay_within_the_kinds_asked_for(
    ctx: AppContext, study: Study
) -> None:
    ctx.record_svc.update(str(study.rec_a.id), {"rname": "Recording A"})
    study.selection(study.rec_a, "s1", b"one")

    plan = ctx.file_access_svc.plan(
        FileSelection(
            query=RecordQuery(dataset="hb"),
            schemas=["encounter", "recording"],  # not selections
            below=True,
        )
    )

    assert plan.items == []


# -- telling a waiting client how far it has got ------------------------------------------


class Recorder:
    """Stands in for a `Progress`, keeping what was reported."""

    def __init__(self) -> None:
        self.events: list[tuple] = []

    def phase(self, label: str, total: int = 0) -> None:
        self.events.append(("phase", label, total))

    def advance(self, done: int, total: int | None = None) -> None:
        self.events.append(("advance", done, total))

    def phases(self) -> list[str]:
        return [e[1] for e in self.events if e[0] == "phase"]


def test_a_plan_reports_the_records_it_goes_through_against_how_many_there_are(
    ctx: AppContext, study: Study
) -> None:
    for i in range(5):
        study.selection(study.rec_a, f"s{i}", f"c{i}".encode())
    seen = Recorder()

    ctx.file_access_svc.plan(
        _sel(schema="selection", within=str(study.e7.id)), progress=seen
    )

    assert seen.phases() == ["Finding files", "Working out the folders"]
    assert seen.events[0] == ("phase", "Finding files", 5)
    done = [e[1] for e in seen.events if e[0] == "advance"]
    assert done == sorted(done) and done[-1] == 5


def test_going_beneath_says_it_is_looking_inside(ctx: AppContext, study: Study) -> None:
    study.selection(study.rec_a, "s1", b"one")
    seen = Recorder()

    ctx.file_access_svc.plan(_below(dataset="hb", schema="encounter"), progress=seen)

    assert seen.phases() == [
        "Finding files",
        "Finding what is inside",
        "Working out the folders",
    ]


def test_ticked_rows_report_just_their_own_count(ctx: AppContext, study: Study) -> None:
    a = study.selection(study.rec_a, "s1", b"one")
    seen = Recorder()

    ctx.file_access_svc.plan(_sel(record_ids=[str(a.id)]), progress=seen)

    assert seen.events[0] == ("phase", "Finding files", 1)


def test_an_export_reports_making_the_folder_a_file_at_a_time(
    ctx: AppContext, study: Study, tmp_path: Path
) -> None:
    for i in range(4):
        study.selection(study.rec_a, f"s{i}", f"c{i}".encode())
    seen = Recorder()

    ctx.file_access_svc.export(
        _sel(schema="selection", within=str(study.e7.id)),
        tmp_path / "out",
        progress=seen,
    )

    assert seen.phases() == [
        "Finding files",
        "Working out the folders",
        "Making the folder",
    ]
    assert ("phase", "Making the folder", 4) in seen.events
    advances = [
        e[1]
        for e in seen.events[seen.events.index(("phase", "Making the folder", 4)) :]
        if e[0] == "advance"
    ]
    assert advances == [1, 2, 3, 4]


def test_a_copy_says_it_is_copying(
    ctx: AppContext, study: Study, tmp_path: Path
) -> None:
    study.selection(study.rec_a, "s1", b"one")
    seen = Recorder()

    ctx.file_access_svc.export(
        _sel(schema="selection", within=str(study.e7.id)),
        tmp_path / "out",
        mode="copy",
        progress=seen,
    )

    assert "Copying the files" in seen.phases()


def test_a_managed_export_reports_too(ctx: AppContext, study: Study) -> None:
    study.selection(study.rec_a, "s1", b"one")
    seen = Recorder()

    ctx.file_access_svc.export_managed(
        _sel(schema="selection", within=str(study.e7.id)), "tables", progress=seen
    )

    assert seen.phases()[0] == "Finding files" and "Making the folder" in seen.phases()
    # The plan is made once, however many stages report it.
    assert seen.phases().count("Finding files") == 1


def test_nothing_is_required_to_report(ctx: AppContext, study: Study) -> None:
    study.selection(study.rec_a, "s1", b"one")

    plan = ctx.file_access_svc.plan(_sel(schema="selection", within=str(study.e7.id)))

    assert len(plan.items) == 1


def test_ticked_rows_taken_with_what_is_inside_can_be_limited_to_some_kinds(
    ctx: AppContext, study: Study
) -> None:
    ctx.record_svc.update(
        str(study.e7.id),
        {"name": "Encounter 7", "notes": study.file(b"field notes", "notes.pdf")},
    )
    study.selection(study.rec_a, "s1", b"one")

    both = ctx.file_access_svc.plan(
        FileSelection(query=RecordQuery(), record_ids=[str(study.e7.id)], below=True)
    )
    only_selections = ctx.file_access_svc.plan(
        FileSelection(
            query=RecordQuery(),
            record_ids=[str(study.e7.id)],
            below=True,
            schemas=["selection"],
        )
    )

    assert sorted(_paths(both)) == [
        "Encounter 7/Recording A/s1/s1.txt",
        "Encounter 7/notes.pdf",
    ]
    # Only records of the kind asked for: the ticked encounter's own notes are
    # not of that kind, so they are left out.
    assert _paths(only_selections) == ["Encounter 7/Recording A/s1/s1.txt"]
