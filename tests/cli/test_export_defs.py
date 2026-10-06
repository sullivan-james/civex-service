"""`civex schema exports` and `civex files ... --export`."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from civex.context import AppContext
from civex.main import app

runner = CliRunner()


def _flat(text: str) -> str:
    return " ".join(text.split())


def _invoke(*args: str):
    return runner.invoke(app, list(args))


@pytest.fixture()
def tree(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("encounter", fields=[("name", "string")])
    make_schema("recording", fields=[("rname", "string")], parent="encounter")
    make_schema(
        "selection",
        fields=[("sname", "string"), ("contour", "file"), ("table", "file")],
        parent="recording",
    )
    make_collection("hb")
    e7 = make_record("hb", "encounter", {"name": "Encounter 7"})
    rec = make_record(
        "hb", "recording", {"rname": "Rec A"}, parent_record_id=str(e7.id)
    )
    for name in ("s1", "s2"):
        make_record(
            "hb",
            "selection",
            {
                "sname": name,
                "contour": ctx.file_svc.store_bytes(
                    name.encode(), f"{name}.contour"
                ).to_dict(),
            },
            parent_record_id=str(rec.id),
        )
    return e7


def _add(*extra: str):
    return _invoke(
        "schema",
        "exports",
        "add",
        "encounter",
        "Contours",
        "--kind",
        "selection",
        "--field",
        "contour",
        "--layout",
        "flat",
        *extra,
    )


def test_an_export_is_added_listed_shown_changed_and_removed(tree) -> None:
    added = _add()
    listed = _invoke("schema", "exports", "list", "encounter")
    shown = _invoke("schema", "exports", "show", "encounter", "Contours")
    changed = _invoke(
        "schema",
        "exports",
        "set",
        "encounter",
        "Contours",
        "--layout",
        "grouped",
        "--rename",
        "Contour files",
    )
    removed = _invoke(
        "schema", "exports", "remove", "encounter", "Contour files", "--yes"
    )
    after = _invoke("schema", "exports", "list", "encounter")

    assert added.exit_code == 0, added.output
    assert "Saved encounter/Contours" in _flat(added.output)
    assert "Contours" in _flat(listed.output) and "contour of selection" in _flat(
        listed.output
    )
    out = _flat(shown.output)
    assert "kind of record: selection" in out and "file fields: contour" in out
    assert "layout: flat" in out
    assert changed.exit_code == 0, changed.output
    assert "grouped" in _flat(changed.output) and "Contour files" in _flat(
        changed.output
    )
    assert removed.exit_code == 0 and "No exports" in _flat(after.output)


def test_a_bad_export_is_refused_with_the_reason(tree) -> None:
    above = _invoke("schema", "exports", "add", "recording", "x", "--kind", "encounter")
    bad_field = _invoke(
        "schema",
        "exports",
        "add",
        "encounter",
        "y",
        "--kind",
        "selection",
        "--field",
        "sname",
    )
    bad_filter = _invoke(
        "schema",
        "exports",
        "add",
        "encounter",
        "z",
        "--kind",
        "selection",
        "--filter",
        "{nope",
    )
    missing = _invoke("schema", "exports", "show", "encounter", "nope")

    assert above.exit_code == 1 and "beneath it" in _flat(above.output)
    assert bad_field.exit_code == 1 and "isn't a file field" in _flat(bad_field.output)
    assert bad_filter.exit_code == 1 and "not valid JSON" in _flat(bad_filter.output)
    assert missing.exit_code == 1 and "not found" in _flat(missing.output)


def test_a_filter_and_a_kind_can_be_given_and_cleared(tree) -> None:
    _add("--filter", '{"field": "sname", "op": "eq", "value": "s1"}')

    shown = _invoke("schema", "exports", "show", "encounter", "Contours")
    cleared = _invoke(
        "schema",
        "exports",
        "set",
        "encounter",
        "Contours",
        "--no-filter",
        "--any-kind",
        "--all-fields",
    )
    after = _invoke("schema", "exports", "show", "encounter", "Contours")

    assert '"sname"' in _flat(shown.output)
    assert cleared.exit_code == 0, cleared.output
    out = _flat(after.output)
    assert "any kind beneath" in out and "every one" in out and "filter:" not in out


def test_conflicting_or_empty_changes_are_refused(tree) -> None:
    _add()

    both = _invoke(
        "schema",
        "exports",
        "set",
        "encounter",
        "Contours",
        "--kind",
        "selection",
        "--any-kind",
    )
    none = _invoke("schema", "exports", "set", "encounter", "Contours")
    no_confirm = _invoke("schema", "exports", "remove", "encounter", "Contours")

    assert both.exit_code == 1 and "not both" in _flat(both.output)
    assert none.exit_code == 1 and "Nothing to change" in _flat(none.output)
    assert no_confirm.exit_code == 1  # asked, and no answer was given


def test_the_exports_available_within_a_schema_include_those_above_it(tree) -> None:
    _add()

    on_recording = _invoke("schema", "exports", "list", "recording", "--available")
    own_only = _invoke("schema", "exports", "list", "recording")

    assert "Contours" in _flat(on_recording.output)
    assert "No exports" in _flat(own_only.output)


def test_an_export_runs_on_a_collection_from_the_files_commands(
    tree, tmp_path: Path
) -> None:
    _add()

    listed = _invoke("files", "list", "--export", "encounter/Contours", "--in", "hb")
    made = _invoke(
        "files",
        "export",
        str(tmp_path / "out"),
        "--export",
        "encounter/Contours",
        "--in",
        "hb",
        "--mode",
        "copy",
    )

    out = _flat(listed.output)
    assert listed.exit_code == 0, listed.output
    assert " s1.contour " in out and " s2.contour " in out
    assert made.exit_code == 0, made.output
    assert (tmp_path / "out" / "s1.contour").read_bytes() == b"s1"


def test_an_export_runs_within_a_record_and_its_layout_can_be_overridden(tree) -> None:
    _add()

    result = _invoke(
        "files",
        "list",
        "--export",
        "encounter/Contours",
        "--under",
        str(tree.id)[:8],
        "--layout",
        "grouped",
    )

    out = _flat(result.output)
    assert result.exit_code == 0, result.output
    assert "Rec A/Selections/s1.contour" in out


def test_a_malformed_or_unknown_export_reference_is_refused(tree) -> None:
    malformed = _invoke("files", "list", "--export", "encounter")
    unknown = _invoke("files", "list", "--export", "encounter/nope")

    assert malformed.exit_code == 1 and "schema/name" in _flat(malformed.output)
    assert unknown.exit_code == 1 and "not found" in _flat(unknown.output)


def test_an_export_can_be_saved_with_a_table_and_changed(tree) -> None:
    added = _invoke(
        "schema",
        "exports",
        "add",
        "encounter",
        "Tables",
        "--kind",
        "selection",
        "--table",
        "xlsx",
        "--column",
        "sname",
        "--no-files",
    )
    assert added.exit_code == 0, added.output
    shown = _flat(_invoke("schema", "exports", "show", "encounter", "Tables").output)
    assert "table: xlsx" in shown and "columns: sname" in shown
    assert "no (table alone)" in shown

    changed = _invoke(
        "schema",
        "exports",
        "set",
        "encounter",
        "Tables",
        "--files",
        "--field",
        "contour",
    )
    assert changed.exit_code == 0, changed.output
    listed = _flat(_invoke("schema", "exports", "list", "encounter").output)
    assert "contour of selection" in listed and "xlsx table" in listed

    gone = _invoke("schema", "exports", "set", "encounter", "Tables", "--no-table")
    assert gone.exit_code == 0, gone.output
    assert "table" not in _flat(
        _invoke("schema", "exports", "list", "encounter").output
    ).replace("table alone", "")


def test_a_table_needs_something_to_export(tree) -> None:
    result = _invoke(
        "schema",
        "exports",
        "add",
        "encounter",
        "Nothing",
        "--kind",
        "selection",
        "--no-files",
    )

    assert result.exit_code == 1
    assert "files, tables, or both" in _flat(result.output)
