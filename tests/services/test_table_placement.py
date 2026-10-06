"""Tables written where they are wanted: once at the top, in each folder of a kind,
or as a record's own metadata. One concept (what the rows are, where it goes, its
columns), so each case here is a choice of those."""

from __future__ import annotations

import csv
import zipfile
from pathlib import Path

import pytest

from civex.context import AppContext
from civex.domain.exceptions import ValidationError
from civex.domain.file_access import FileSelection
from civex.domain.query import RecordQuery
from civex.domain.tables import TableSpec
from civex.services.archive import build_download
from civex.services.file_access_service import GENERATED, MARKER


@pytest.fixture()
def tree(ctx: AppContext, make_schema, make_collection, make_record):
    """Encounter 7 -> recordings A (two selections), B (one) and C (none), each
    selection holding a contour file."""
    make_schema("encounter", fields=[("name", "string"), ("site", "string")])
    make_schema(
        "recording", fields=[("rname", "string"), ("depth", "float")], parent="encounter"
    )
    make_schema(
        "selection",
        fields=[("sname", "string"), ("quality", "string"), ("contour", "file")],
        parent="recording",
    )
    make_collection("hb")
    enc = make_record("hb", "encounter", {"name": "Encounter 7", "site": "North"})
    made = {}
    for rname, depth, selections in (
        ("A", 1.5, ["s1", "s2"]),
        ("B", 2.5, ["s3"]),
        ("C", 3.5, []),
    ):
        rec = make_record(
            "hb",
            "recording",
            {"rname": rname, "depth": depth},
            parent_record_id=str(enc.id),
        )
        made[rname] = rec
        for sname in selections:
            ref = ctx.file_svc.store_bytes(sname.encode(), f"{sname}.txt").to_dict()
            make_record(
                "hb",
                "selection",
                {"sname": sname, "quality": "good", "contour": ref},
                parent_record_id=str(rec.id),
            )
    return enc, made


def _sel(enc, *tables: TableSpec, files: bool = True, **kw) -> FileSelection:
    return FileSelection(
        query=RecordQuery(schema="selection", within=str(enc.id)),
        tables=list(tables),
        files=files,
        **kw,
    )


def _rows(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _paths(root: Path) -> set[str]:
    return {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.name != MARKER
    }


# -- a table in each folder of a kind ---------------------------------------------


def test_each_recording_gets_a_table_of_its_own_selections(
    ctx: AppContext, tree, tmp_path: Path
) -> None:
    enc, _ = tree
    spec = TableSpec("csv", ["sname", "quality"], kind="selection", where="recording")
    dest = tmp_path / "out"

    result = ctx.file_access_svc.export(_sel(enc, spec), dest, "copy")

    assert result.tables == 2  # C has no selections: nothing to list
    assert _rows(dest / "A" / "Selections.csv") == [
        {"sname": "s1", "quality": "good"},
        {"sname": "s2", "quality": "good"},
    ]
    assert _rows(dest / "B" / "Selections.csv") == [{"sname": "s3", "quality": "good"}]
    assert not (dest / "C").exists()


def test_a_folder_with_no_rows_can_still_get_a_table(
    ctx: AppContext, tree, tmp_path: Path
) -> None:
    enc, _ = tree
    spec = TableSpec(
        "csv", ["sname"], kind="selection", where="recording", skip_empty=False
    )
    dest = tmp_path / "out"

    ctx.file_access_svc.export(_sel(enc, spec), dest, "copy")

    assert _rows(dest / "C" / "Selections.csv") == []
    assert (dest / "C" / "Selections.csv").read_text().strip() == "sname"


def test_a_table_for_each_selection_is_that_records_metadata(
    ctx: AppContext, tree, tmp_path: Path
) -> None:
    enc, _ = tree
    spec = TableSpec(
        "csv",
        ["sname", "quality", "rname", "depth", "site"],  # own, then inherited
        kind="selection",
        where="selection",
        shape="fields",
    )
    dest = tmp_path / "out"

    ctx.file_access_svc.export(_sel(enc, spec), dest, "copy")

    meta = {r["field"]: r["value"] for r in _rows(dest / "A" / "s1" / "Metadata.csv")}
    assert meta == {
        "sname": "s1",
        "quality": "good",
        "rname": "A",
        "depth": "1.5",
        "site": "North",
    }
    assert (dest / "B" / "s3" / "Metadata.csv").is_file()
    # The file and its metadata sit together.
    assert (dest / "A" / "s1" / "s1.txt").is_file()


def test_a_recordings_metadata_comes_from_an_export_of_its_selections(
    ctx: AppContext, tree, tmp_path: Path
) -> None:
    """Rows are the records the export takes and the ones above them, so a table
    of recordings works from an export of selections."""
    enc, _ = tree
    spec = TableSpec(
        "csv", ["rname", "depth"], kind="recording", where="recording", shape="fields"
    )
    dest = tmp_path / "out"

    ctx.file_access_svc.export(_sel(enc, spec), dest, "copy")

    assert {r["field"]: r["value"] for r in _rows(dest / "A" / "Metadata.csv")} == {
        "rname": "A",
        "depth": "1.5",
    }
    assert (dest / "B" / "Metadata.csv").is_file()
    assert not (dest / "C").exists()  # no selections beneath it: not in this export


def test_one_table_of_a_kind_above_the_files_goes_at_the_top(
    ctx: AppContext, tree, tmp_path: Path
) -> None:
    enc, _ = tree
    spec = TableSpec("csv", ["rname", "depth"], kind="recording")
    dest = tmp_path / "out"

    ctx.file_access_svc.export(_sel(enc, spec), dest, "copy")

    assert [r["rname"] for r in _rows(dest / "Recordings.csv")] == ["A", "B"]


def test_several_tables_in_one_export(ctx: AppContext, tree, tmp_path: Path) -> None:
    enc, _ = tree
    dest = tmp_path / "out"

    result = ctx.file_access_svc.export(
        _sel(
            enc,
            TableSpec("csv", ["sname"], kind="selection"),
            TableSpec("csv", ["sname"], kind="selection", where="recording"),
            TableSpec(
                "csv", ["sname"], kind="selection", where="selection", shape="fields"
            ),
        ),
        dest,
        "copy",
    )

    assert result.tables == 1 + 2 + 3
    assert (dest / "Selections.csv").is_file()
    assert (dest / "A" / "Selections.csv").is_file()
    assert (dest / "A" / "s2" / "Metadata.csv").is_file()


def test_tables_need_no_files(ctx: AppContext, tree, tmp_path: Path) -> None:
    enc, _ = tree
    spec = TableSpec("csv", ["sname"], kind="selection", where="recording")
    dest = tmp_path / "out"

    ctx.file_access_svc.export(_sel(enc, spec, files=False), dest, "copy")

    assert _paths(dest) == {"A/Selections.csv", "B/Selections.csv"}


# -- names -----------------------------------------------------------------------


def test_the_name_is_a_template_over_the_folders_record(
    ctx: AppContext, tree, tmp_path: Path
) -> None:
    enc, _ = tree
    spec = TableSpec(
        "csv",
        ["sname"],
        kind="selection",
        where="recording",
        name="{rname} selections",
    )
    dest = tmp_path / "out"

    ctx.file_access_svc.export(_sel(enc, spec), dest, "copy")

    assert (dest / "A" / "A selections.csv").is_file()
    assert (dest / "B" / "B selections.csv").is_file()


def test_a_table_never_takes_the_name_of_a_file_beside_it(
    ctx: AppContext, tree, tmp_path: Path
) -> None:
    enc, _ = tree
    # Selection s1's own file is s1.txt; name the metadata table the same, no ext.
    spec = TableSpec(
        "txt" if False else "csv",
        ["sname"],
        kind="selection",
        where="selection",
        shape="fields",
        name="s1",
    )
    plan = ctx.file_access_svc.plan(_sel(enc, spec))

    names = {t.path for t in plan.tables}
    assert "A/s1/s1.csv" in names  # not a clash with s1.txt: different extension
    two = ctx.file_access_svc.plan(
        _sel(
            enc,
            TableSpec("csv", ["sname"], kind="selection", where="recording"),
            TableSpec("csv", ["quality"], kind="selection", where="recording"),
        )
    )
    in_a = sorted(t.name for t in two.tables if t.folder == "A")
    assert in_a == ["Selections (2).csv", "Selections.csv"]


# -- the rules a table has to satisfy -----------------------------------------------


def test_a_table_in_each_folder_needs_the_folder_per_record_layout(
    ctx: AppContext, tree
) -> None:
    enc, _ = tree
    spec = TableSpec("csv", None, kind="selection", where="recording")
    for layout in ("grouped", "flat"):
        with pytest.raises(ValidationError, match="folder per record"):
            ctx.file_access_svc.plan(_sel(enc, spec, layout=layout))


def test_the_rules_of_a_spec_are_checked_when_it_is_made() -> None:
    with pytest.raises(ValidationError, match="needs its kind"):
        TableSpec("csv", where="recording")
    with pytest.raises(ValidationError, match="Field/value"):
        TableSpec("csv", kind="selection", where="recording", shape="fields")
    with pytest.raises(ValidationError, match="Field/value"):
        TableSpec("csv", kind="selection", shape="fields")
    with pytest.raises(ValidationError, match="shape"):
        TableSpec("csv", shape="sideways")


def test_the_plan_says_where_each_table_goes_and_how_big_it_is(
    ctx: AppContext, tree
) -> None:
    enc, _ = tree
    spec = TableSpec("csv", ["sname"], kind="selection", where="recording")

    plan = ctx.file_access_svc.plan(_sel(enc, spec))

    assert [(t.path, t.rows) for t in plan.tables] == [
        ("A/Selections.csv", 2),
        ("B/Selections.csv", 1),
    ]
    assert plan.tables[0].to_dict()["folder"] == "A"
    assert plan.items  # the files are planned beside them


def test_a_base_starts_the_folders_below_it(
    ctx: AppContext, tree, tmp_path: Path
) -> None:
    enc, made = tree
    spec = TableSpec("csv", ["sname"], kind="selection", where="recording")
    sel = FileSelection(
        query=RecordQuery(schema="selection", within=str(made["A"].id)),
        tables=[spec],
    )
    dest = tmp_path / "out"

    ctx.file_access_svc.export(sel, dest, "copy")

    # The recording is the base: its own table is at the top of the export.
    assert _rows(dest / "Selections.csv") == [{"sname": "s1"}, {"sname": "s2"}]


# -- keeping an export up to date ---------------------------------------------------


def test_re_exporting_without_a_table_removes_it_and_its_empty_folder(
    ctx: AppContext, tree, tmp_path: Path
) -> None:
    enc, _ = tree
    spec = TableSpec("csv", ["sname"], kind="selection", where="recording")
    dest = tmp_path / "out"
    ctx.file_access_svc.export(_sel(enc, spec, files=False), dest, "copy")
    assert _paths(dest) == {"A/Selections.csv", "B/Selections.csv"}

    ctx.file_access_svc.export(_sel(enc, spec), dest, "copy")  # now with files too
    assert "A/Selections.csv" in _paths(dest)

    ctx.file_access_svc.export(
        _sel(enc, TableSpec("csv", ["sname"], kind="selection")), dest, "copy"
    )
    paths = _paths(dest)
    assert "Selections.csv" in paths
    assert "A/Selections.csv" not in paths and "B/Selections.csv" not in paths


def test_the_marker_lists_each_table_by_its_path(
    ctx: AppContext, tree, tmp_path: Path
) -> None:
    import json

    enc, _ = tree
    spec = TableSpec("csv", ["sname"], kind="selection", where="recording")
    dest = tmp_path / "out"

    ctx.file_access_svc.export(_sel(enc, spec), dest, "copy")

    marker = json.loads((dest / MARKER).read_text())
    files = marker.get("files", marker)
    assert files["A/Selections.csv"]["how"] == GENERATED


# -- handing it over ---------------------------------------------------------------


def test_the_zip_has_each_table_in_its_folder(
    ctx: AppContext, tree, tmp_path: Path
) -> None:
    enc, _ = tree
    spec = TableSpec("csv", ["sname"], kind="selection", where="recording")
    sel = _sel(enc, spec)
    plan = ctx.file_access_svc.plan(sel)
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    download = build_download(
        ctx.file_access_svc, ctx.file_svc, sel, plan, scratch, name="export"
    )

    with zipfile.ZipFile(download.path) as z:
        names = set(z.namelist())
    assert {"A/Selections.csv", "B/Selections.csv", "A/s1/s1.txt"} <= names


def test_a_single_table_is_handed_over_alone_under_its_own_name(
    ctx: AppContext, tree, tmp_path: Path
) -> None:
    enc, made = tree
    spec = TableSpec("csv", ["sname"], kind="selection", where="recording")
    sel = FileSelection(
        query=RecordQuery(schema="selection", within=str(made["B"].id)),
        tables=[spec],
        files=False,
    )
    plan = ctx.file_access_svc.plan(sel)
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    download = build_download(ctx.file_access_svc, ctx.file_svc, sel, plan, scratch)

    assert download.filename == "Selections.csv"
    assert download.media_type == "text/csv"


# -- saved with a schema --------------------------------------------------------------


def test_a_saved_export_keeps_its_tables_and_runs_them(
    ctx: AppContext, tree, tmp_path: Path
) -> None:
    enc, _ = tree
    tables = [
        {
            "format": "csv",
            "columns": ["sname"],
            "kind": "selection",
            "where": "recording",
        },
        {
            "format": "csv",
            "columns": ["sname"],
            "kind": "selection",
            "where": "selection",
            "shape": "fields",
        },
    ]
    saved = ctx.export_def_svc.create(
        "encounter", "Everything", holder="selection", tables=tables
    )
    ctx.commit()

    run = ctx.export_def_svc.selection(saved, within=str(enc.id))

    assert [(t.kind, t.where, t.shape) for t in run.tables] == [
        ("selection", "recording", "rows"),
        ("selection", "selection", "fields"),
    ]
    dest = tmp_path / "out"
    ctx.file_access_svc.export(run, dest, "copy")
    assert (dest / "A" / "Selections.csv").is_file()
    assert (dest / "A" / "s1" / "Metadata.csv").is_file()


def test_a_saved_table_is_checked_against_the_tree_it_is_saved_in(
    ctx: AppContext, tree, make_schema
) -> None:
    make_schema("unrelated", fields=[("x", "string")])
    svc = ctx.export_def_svc

    with pytest.raises(ValidationError, match="isn't 'encounter'"):
        svc.create(
            "encounter",
            "Bad kind",
            holder="selection",
            tables=[{"format": "csv", "kind": "unrelated"}],
        )
    with pytest.raises(ValidationError, match="can only be written in the folder"):
        svc.create(
            "encounter",
            "Bad place",
            holder="selection",
            tables=[{"format": "csv", "kind": "recording", "where": "selection"}],
        )
    with pytest.raises(ValidationError, match="isn't a field of 'selection'"):
        svc.create(
            "encounter",
            "Bad column",
            holder="selection",
            tables=[{"format": "csv", "kind": "selection", "columns": ["nope"]}],
        )
    with pytest.raises(ValidationError, match="folder per record"):
        svc.create(
            "encounter",
            "Bad layout",
            holder="selection",
            files_layout="flat",
            tables=[{"format": "csv", "kind": "selection", "where": "recording"}],
        )
    with pytest.raises(ValidationError):
        svc.create(
            "encounter",
            "Bad name",
            holder="selection",
            tables=[
                {
                    "format": "csv",
                    "kind": "selection",
                    "where": "recording",
                    "name": "{nonsense}",
                }
            ],
        )


# -- cost -----------------------------------------------------------------------------


def _statements(ctx: AppContext, work) -> int:
    from sqlalchemy import event

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


def test_planning_tables_in_each_folder_costs_the_same_however_many_folders(
    ctx: AppContext, make_record, tree
) -> None:
    """A table per recording and a sheet per selection are not a query each."""
    enc, _ = tree
    specs = [
        TableSpec("csv", ["sname"], kind="selection", where="recording"),
        TableSpec("csv", ["sname"], kind="selection", where="selection", shape="fields"),
    ]

    def add(n: int, tag: str) -> None:
        for i in range(n):
            rec = make_record(
                "hb",
                "recording",
                {"rname": f"{tag}{i}", "depth": 1.0},
                parent_record_id=str(enc.id),
            )
            make_record(
                "hb",
                "selection",
                {"sname": f"{tag}{i}"},
                parent_record_id=str(rec.id),
            )
        ctx.commit()

    def plan() -> int:
        return _statements(ctx, lambda: ctx.file_access_svc.plan(_sel(enc, *specs)))

    add(2, "x")
    few = plan()
    add(25, "y")
    many = plan()

    assert many == few


def test_writing_tables_in_each_folder_costs_the_same_however_many_folders(
    ctx: AppContext, make_record, tree, tmp_path: Path
) -> None:
    enc, _ = tree
    specs = [
        TableSpec("csv", ["sname", "rname", "site"], kind="selection", where="recording"),
        TableSpec(
            "csv",
            ["sname", "rname", "depth"],
            kind="selection",
            where="selection",
            shape="fields",
        ),
    ]

    def add(n: int, tag: str) -> None:
        for i in range(n):
            rec = make_record(
                "hb",
                "recording",
                {"rname": f"{tag}{i}", "depth": 1.0},
                parent_record_id=str(enc.id),
            )
            make_record(
                "hb", "selection", {"sname": f"{tag}{i}"}, parent_record_id=str(rec.id)
            )
        ctx.commit()

    def write(name: str) -> int:
        sel = _sel(enc, *specs, files=False)
        plan = ctx.file_access_svc.plan(sel)
        out = tmp_path / name
        out.mkdir()
        return _statements(ctx, lambda: ctx.file_access_svc.write_tables(sel, plan, out))

    add(2, "x")
    few = write("few")
    add(25, "y")
    many = write("many")

    assert many == few
    assert (tmp_path / "many").rglob("Metadata.csv")
