"""`civex files`: list and export the files of some records by name and folder."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from civex.context import AppContext
from civex.main import app

runner = CliRunner()


@pytest.fixture()
def study(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("encounter", fields=[("name", "string")])
    make_schema(
        "recording", fields=[("rname", "string"), ("table", "file")], parent="encounter"
    )
    collection = make_collection("hb")
    enc = make_record("hb", "encounter", {"name": "Encounter 7"})

    def add(name: str, content: bytes, on: str | None = None):
        ref = ctx.file_svc.store_bytes(content, f"{name}.txt", on).to_dict()
        make_record(
            "hb",
            "recording",
            {"rname": name, "table": ref},
            parent_record_id=str(enc.id),
        )

    add("a", b"alpha")
    return collection, enc, add


def _flat(text: str) -> str:
    """Output with Rich's line wrapping undone."""
    return " ".join(text.split())


def _invoke(*args: str):
    return runner.invoke(app, ["files", *args])


def test_list_shows_paths_and_sizes(study) -> None:
    result = _invoke("list", "--in", "hb", "--schema", "recording")

    assert result.exit_code == 0, result.output
    assert "Encounter 7/a/a.txt" in result.output
    assert "1 file(s)" in result.output


def test_list_under_a_record_starts_below_it(study) -> None:
    _, enc, _ = study

    result = _invoke("list", "--under", str(enc.id)[:8], "--schema", "recording")

    assert "a/a.txt" in result.output and "Encounter 7" not in result.output


def test_list_paths_prints_only_where_the_files_are_on_disk(study) -> None:
    result = _invoke("list", "--in", "hb", "--schema", "recording", "--paths")

    lines = result.output.strip().splitlines()
    assert result.exit_code == 0 and len(lines) == 1
    assert Path(lines[0]).read_bytes() == b"alpha"


def test_a_selection_must_be_given(study) -> None:
    result = _invoke("list")

    assert result.exit_code == 1 and "Say which files" in result.output


def test_a_wrong_field_is_an_error(study) -> None:
    result = _invoke("list", "--in", "hb", "--field", "nope")

    assert result.exit_code == 1 and "nope" in result.output


def test_export_links_into_the_exports_folder_and_run_again_changes_nothing(
    study, project_dir: Path
) -> None:
    args = ["export", "--in", "hb", "--schema", "recording", "--name", "tables"]

    first = _invoke(*args)
    again = _invoke(*args)

    out = _flat(first.output)
    assert first.exit_code == 0, first.output
    assert "1 linked" in out and "0 copied" in out
    assert "don't edit it in place" in out
    dest = project_dir / "_civex" / "exports" / "tables"
    assert (dest / "Encounter 7" / "a" / "a.txt").read_bytes() == b"alpha"
    assert "1 already there" in _flat(again.output)


def test_export_to_a_chosen_folder_still_works(study, tmp_path: Path) -> None:
    dest = tmp_path / "out"

    result = _invoke("export", str(dest), "--in", "hb", "--schema", "recording")

    assert result.exit_code == 0, result.output
    assert (dest / "Encounter 7" / "a" / "a.txt").exists()


def test_export_refuses_a_bad_mode(study, tmp_path: Path) -> None:
    result = _invoke("export", str(tmp_path / "o"), "--in", "hb", "--mode", "auto")

    assert result.exit_code == 1 and "--mode" in result.output


@pytest.fixture()
def unplugged(ctx: AppContext, study, tmp_path: Path):
    collection, _, add = study
    drive = tmp_path / "mnt" / "archive"
    drive.mkdir(parents=True)
    ctx.store_svc.add_volume("archive", str(drive))
    ctx.store_svc.set_placement(str(collection.id), "archive")
    add("far", b"on archive", on=str(collection.id))
    ctx.commit()
    drive.rename(drive.with_name("archive-unplugged"))


def test_unreachable_files_are_shown_first_and_nothing_is_made(
    unplugged, tmp_path: Path
) -> None:
    dest = tmp_path / "out"

    result = _invoke("export", str(dest), "--in", "hb", "--schema", "recording")

    assert result.exit_code == 1
    assert "archive" in result.output and "Nothing was exported" in result.output
    assert not dest.exists()


def test_allow_partial_exports_the_rest_and_says_what_was_left_out(
    unplugged, tmp_path: Path
) -> None:
    dest = tmp_path / "out"

    result = _invoke(
        "export", str(dest), "--in", "hb", "--schema", "recording", "--allow-partial"
    )

    assert result.exit_code == 2  # done, but incomplete: a script can tell
    assert "MISSING.txt" in result.output
    assert (dest / "Encounter 7" / "a" / "a.txt").exists()
    assert "far" in (dest / "MISSING.txt").read_text()


def test_list_marks_a_file_that_cannot_be_reached(unplugged) -> None:
    result = _invoke("list", "--in", "hb", "--schema", "recording")

    assert "unavailable" in result.output and "archive" in result.output


def test_copy_mode_says_nothing_about_editing(study, tmp_path: Path) -> None:
    result = _invoke(
        "export",
        str(tmp_path / "o"),
        "--in",
        "hb",
        "--schema",
        "recording",
        "--mode",
        "copy",
    )

    out = _flat(result.output)
    assert "1 copied" in out and "0 linked" in out
    assert "in place" not in out


@pytest.fixture()
def two_drives(ctx: AppContext, study, tmp_path_factory: pytest.TempPathFactory):
    collection, _, add = study
    drive = tmp_path_factory.mktemp("drives") / "archive"
    drive.mkdir()
    ctx.store_svc.add_volume("archive", str(drive))
    ctx.store_svc.set_placement(str(collection.id), "archive")
    add("far", b"on archive", on=str(collection.id))
    ctx.commit()
    return drive


def test_files_on_two_drives_cannot_be_linked_and_the_error_says_what_to_do(
    two_drives, project_dir: Path
) -> None:
    result = _invoke("export", "--in", "hb", "--schema", "recording", "--name", "t")

    out = _flat(result.output)
    assert result.exit_code == 1
    assert "2 drives" in out and "--mode copy --to" in out
    assert not (project_dir / "_civex" / "exports" / "t").exists()


def test_the_same_files_can_be_copied_onto_one_drive(two_drives: Path) -> None:
    result = _invoke(
        "export",
        "--in",
        "hb",
        "--schema",
        "recording",
        "--name",
        "t",
        "--mode",
        "copy",
        "--to",
        "archive",
    )

    assert result.exit_code == 0, result.output
    assert "2 copied" in _flat(result.output)
    assert (two_drives / "_exports" / "t" / "Encounter 7" / "far" / "far.txt").exists()


def test_exports_are_listed_and_removed(study, project_dir: Path) -> None:
    _invoke("export", "--in", "hb", "--schema", "recording", "--name", "tables")
    _invoke(
        "export",
        "--in",
        "hb",
        "--schema",
        "recording",
        "--name",
        "copies",
        "--mode",
        "copy",
    )

    listing = _flat(_invoke("exports", "list").output)
    removed = _invoke("exports", "remove", "project/copies", "--yes")

    assert "tables" in listing and "copies" in listing
    assert removed.exit_code == 0, removed.output
    assert "removed 1 file" in _flat(removed.output)
    exports = project_dir / "_civex" / "exports"
    assert not (exports / "copies").exists() and (exports / "tables").exists()


def test_remove_all_and_nothing_to_remove(study, project_dir: Path) -> None:
    assert "Nothing matches" in _flat(
        _invoke("exports", "remove", "--all", "--yes").output
    )
    _invoke("export", "--in", "hb", "--schema", "recording", "--name", "tables")

    result = _invoke("exports", "remove", "--all", "--yes")

    assert result.exit_code == 0
    assert "No exports" in _flat(_invoke("exports", "list").output)


def test_remove_asks_which_exports(study) -> None:
    result = _invoke("exports", "remove")

    assert result.exit_code == 1 and "Say which" in result.output


def test_remove_older_than_keeps_recent_exports(study, project_dir: Path) -> None:
    _invoke("export", "--in", "hb", "--schema", "recording", "--name", "tables")

    result = _invoke("exports", "remove", "--older-than", "30", "--yes")

    assert "Nothing matches" in _flat(result.output)
    assert (project_dir / "_civex" / "exports" / "tables").exists()


def test_gather_moves_just_the_selection_so_it_can_be_linked(
    two_drives, project_dir: Path
) -> None:
    before = _invoke("export", "--in", "hb", "--schema", "recording", "--name", "t")
    assert before.exit_code == 1  # scattered

    dry = _invoke(
        "gather", "--to", "archive", "--in", "hb", "--schema", "recording", "--dry-run"
    )
    moved = _invoke("gather", "--to", "archive", "--in", "hb", "--schema", "recording")
    after = _invoke("export", "--in", "hb", "--schema", "recording", "--name", "t")

    assert "Would move 1 files" in _flat(dry.output)
    assert moved.exit_code == 0, moved.output
    assert after.exit_code == 0, after.output
    assert "2 linked" in _flat(after.output)
    assert (two_drives / "_exports" / "t" / "Encounter 7" / "a" / "a.txt").exists()


def test_gather_says_when_there_is_nothing_to_move(study) -> None:
    result = _invoke("gather", "--to", "default", "--in", "hb", "--schema", "recording")

    assert result.exit_code == 0
    assert "already on 'default'" in _flat(result.output)


def test_layout_flat_lists_files_without_their_folders(study) -> None:
    result = _invoke("list", "--in", "hb", "--schema", "recording", "--layout", "flat")

    out = _flat(result.output)
    assert result.exit_code == 0, result.output
    assert " a.txt " in out and "Encounter 7" not in out


def test_a_saved_view_is_a_preset_for_files(study, ctx: AppContext) -> None:
    ctx.view_svc.create(
        "recording", "tables", columns=["rname", "table"], files_layout="flat"
    )
    ctx.commit()

    result = _invoke("list", "--view", "recording/tables")

    out = _flat(result.output)
    assert result.exit_code == 0, result.output
    assert " a.txt " in out and "Encounter 7" not in out  # the view's layout


def test_a_view_can_be_overridden_and_must_have_file_columns(
    study, ctx: AppContext
) -> None:
    ctx.view_svc.create("recording", "tables", columns=["rname", "table"])
    ctx.view_svc.create("recording", "names", columns=["rname"])
    ctx.commit()

    overridden = _invoke("list", "--view", "recording/tables", "--layout", "flat")
    no_files = _invoke("list", "--view", "recording/names")
    malformed = _invoke("list", "--view", "tables")

    assert " a.txt " in _flat(overridden.output)
    assert no_files.exit_code == 1 and "no file columns" in _flat(no_files.output)
    assert malformed.exit_code == 1 and "schema/view" in _flat(malformed.output)


def test_export_makes_a_table_beside_the_files(study, tmp_path: Path) -> None:
    dest = tmp_path / "out"

    result = _invoke(
        "export",
        str(dest),
        "--in",
        "hb",
        "--schema",
        "recording",
        "--mode",
        "copy",
        "--table",
        "tsv",
        "--column",
        "rname",
        "--column",
        "table",
    )

    assert result.exit_code == 0, result.output
    assert "1 table(s) written" in _flat(result.output)
    assert (dest / "Recordings.tsv").read_text().splitlines() == [
        "rname\ttable",
        "a\tEncounter 7/a/a.txt",
    ]


def test_a_table_alone_is_exported_without_files(study, tmp_path: Path) -> None:
    dest = tmp_path / "out"

    result = _invoke(
        "export",
        str(dest),
        "--in",
        "hb",
        "--schema",
        "recording",
        "--table",
        "csv",
        "--no-files",
    )

    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in dest.iterdir() if p.is_file()) == [
        ".civex-export.json",
        "Recordings.csv",
    ]


def test_download_writes_a_lone_table_or_a_zip(study, tmp_path: Path) -> None:
    table = tmp_path / "names.xlsx"
    both = tmp_path / "all.zip"

    one = _invoke(
        "download",
        str(table),
        "--in",
        "hb",
        "--schema",
        "recording",
        "--table",
        "xlsx",
        "--no-files",
    )
    two = _invoke(
        "download", str(both), "--in", "hb", "--schema", "recording", "--table", "csv"
    )

    assert one.exit_code == 0 and two.exit_code == 0, one.output + two.output
    assert table.read_bytes()[:2] == b"PK"  # an xlsx is itself a zip container
    import zipfile

    assert sorted(zipfile.ZipFile(both).namelist()) == [
        "Encounter 7/a/a.txt",
        "Recordings.csv",
    ]


def test_columns_and_no_files_need_a_table(study) -> None:
    assert _invoke("list", "--in", "hb").exit_code == 0
    bad = _invoke("export", "--in", "hb", "--column", "x")
    assert bad.exit_code == 1 and "--table" in _flat(bad.output)
    bad = _invoke("export", "--in", "hb", "--no-files")
    assert bad.exit_code == 1
    bad = _invoke("export", "--in", "hb", "--table", "parquet")
    assert bad.exit_code == 1
