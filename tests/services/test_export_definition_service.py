"""Exports saved with a schema: what they can say, where they are offered, and the
selection each one makes when it is run."""

from __future__ import annotations

import pytest

from civex.context import AppContext
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.domain.file_access import FileSelection


@pytest.fixture()
def tree(ctx: AppContext, make_schema, make_collection, make_record):
    """Encounter -> Recording -> Selection: audio on Recordings, contours and
    tables on Selections; plus an unrelated Site with a scan."""
    make_schema("encounter", fields=[("name", "string")])
    make_schema(
        "recording", fields=[("rname", "string"), ("audio", "file")], parent="encounter"
    )
    make_schema(
        "selection",
        fields=[
            ("sname", "string"),
            ("contour", "file"),
            ("table", "file"),
            ("quality", "string"),
        ],
        parent="recording",
    )
    make_schema("site", fields=[("sitename", "string"), ("scan", "file")])
    make_collection("hb", schemas=["encounter", "recording", "selection", "site"])

    class Tree:
        pass

    t = Tree()
    t.svc = ctx.export_def_svc
    t.file = lambda text, name: ctx.file_svc.store_bytes(text, name).to_dict()
    t.e7 = make_record("hb", "encounter", {"name": "Encounter 7"})
    t.rec = make_record(
        "hb", "recording", {"rname": "Rec A"}, parent_record_id=str(t.e7.id)
    )
    t.sel = lambda name, quality="good": make_record(
        "hb",
        "selection",
        {
            "sname": name,
            "quality": quality,
            "contour": t.file(name.encode(), f"{name}.contour"),
            "table": t.file(name.encode() + b"t", f"{name}.table"),
        },
        parent_record_id=str(t.rec.id),
    )
    t.site = make_record(
        "hb", "site", {"sitename": "North", "scan": t.file(b"scan", "scan.png")}
    )
    return t


# -- defining -------------------------------------------------------------------------


def test_an_export_is_saved_with_its_schema(ctx: AppContext, tree) -> None:
    made = tree.svc.create(
        "encounter",
        "Contour files",
        holder="selection",
        fields=["contour"],
        files_layout="flat",
    )
    ctx.commit()

    got = tree.svc.get("encounter", "Contour files")

    assert (got.schema_name, got.holder, got.fields, got.files_layout) == (
        "encounter",
        "selection",
        ["contour"],
        "flat",
    )
    assert made.id == got.id
    assert [d.name for d in tree.svc.list_for("encounter")] == ["Contour files"]
    assert tree.svc.list_for("recording") == []


def test_the_defaults_are_any_kind_every_field_a_folder_per_record(
    ctx: AppContext, tree
) -> None:
    made = tree.svc.create("encounter", "Everything")

    assert (made.holder, made.fields, made.filter_tree, made.files_layout) == (
        None,
        [],
        None,
        "tree",
    )


def test_a_name_is_free_text_and_unique_within_a_schema(ctx: AppContext, tree) -> None:
    tree.svc.create("encounter", "All the files (2026)")
    ctx.commit()

    with pytest.raises(AlreadyExistsError):
        tree.svc.create("encounter", "All the files (2026)")
    with pytest.raises(ValidationError):
        tree.svc.create("encounter", "a/b")
    # Another schema may use the same name.
    tree.svc.create("recording", "All the files (2026)")


def test_the_kind_that_holds_the_files_must_be_the_schema_or_beneath_it(
    ctx: AppContext, tree
) -> None:
    tree.svc.create("recording", "own", holder="recording")
    tree.svc.create("encounter", "below", holder="selection")

    with pytest.raises(ValidationError, match="beneath it"):
        tree.svc.create("recording", "above", holder="encounter")
    with pytest.raises(ValidationError, match="beneath it"):
        tree.svc.create("encounter", "elsewhere", holder="site")
    # The schema itself must be able to hold a file to be its own holder.
    with pytest.raises(ValidationError, match="can hold a file"):
        tree.svc.create("encounter", "no files here", holder="encounter")


def test_the_fields_must_be_file_fields_the_kind_has(ctx: AppContext, tree) -> None:
    # A Selection carries the Recording's audio too.
    made = tree.svc.create(
        "encounter", "ok", holder="selection", fields=["audio", "contour"]
    )
    assert made.fields == ["audio", "contour"]

    with pytest.raises(ValidationError, match="isn't a file field"):
        tree.svc.create("encounter", "bad", holder="selection", fields=["quality"])
    with pytest.raises(ValidationError, match="isn't a file field"):
        tree.svc.create("encounter", "worse", holder="selection", fields=["nope"])


def test_with_any_kind_the_fields_come_from_anywhere_in_the_schemas_tree(
    ctx: AppContext, tree
) -> None:
    tree.svc.create("encounter", "mixed", fields=["audio", "contour"])

    with pytest.raises(ValidationError, match="isn't a file field"):
        tree.svc.create("encounter", "site-scan", fields=["scan"])  # Site isn't beneath


def test_a_schema_with_nothing_that_can_hold_a_file_cannot_have_an_export(
    ctx: AppContext, make_schema
) -> None:
    make_schema("plain", fields=[("name", "string")])

    with pytest.raises(ValidationError, match="can hold a file"):
        ctx.export_def_svc.create("plain", "nothing")


def test_a_filter_tests_one_kind_of_record_and_is_checked(
    ctx: AppContext, tree
) -> None:
    good = {"field": "quality", "op": "eq", "value": "good"}

    made = tree.svc.create(
        "encounter", "good ones", holder="selection", filter_tree=good
    )

    assert made.filter_tree == good
    with pytest.raises(ValidationError, match="which kind holds"):
        tree.svc.create("encounter", "no kind", filter_tree=good)
    with pytest.raises(ValidationError):
        tree.svc.create(
            "encounter",
            "bad field",
            holder="selection",
            filter_tree={"field": "nope", "op": "eq", "value": 1},
        )


def test_a_layout_must_exist(ctx: AppContext, tree) -> None:
    for layout in ("tree", "grouped", "flat"):
        tree.svc.create("encounter", f"as {layout}", files_layout=layout)

    with pytest.raises(ValidationError, match="layout"):
        tree.svc.create("encounter", "spiral", files_layout="spiral")


# -- changing and removing ------------------------------------------------------------


def test_an_update_changes_only_what_is_given(ctx: AppContext, tree) -> None:
    tree.svc.create(
        "encounter", "x", holder="selection", fields=["contour"], files_layout="flat"
    )

    renamed = tree.svc.update("encounter", "x", new_name="y")
    layout = tree.svc.update("encounter", "y", files_layout="grouped")

    assert (renamed.name, renamed.holder, renamed.fields, renamed.files_layout) == (
        "y",
        "selection",
        ["contour"],
        "flat",
    )
    assert (layout.holder, layout.fields, layout.files_layout) == (
        "selection",
        ["contour"],
        "grouped",
    )


def test_the_whole_definition_is_checked_again_after_a_change(
    ctx: AppContext, tree
) -> None:
    tree.svc.create("encounter", "x", holder="selection", fields=["contour"])

    # Contour is a Selection field; a Recording doesn't have it.
    with pytest.raises(ValidationError, match="isn't a file field"):
        tree.svc.update("encounter", "x", holder="recording")
    # ...but may change together with it.
    moved = tree.svc.update("encounter", "x", holder="recording", fields=["audio"])
    assert (moved.holder, moved.fields) == ("recording", ["audio"])


def test_a_filter_and_a_kind_can_be_cleared(ctx: AppContext, tree) -> None:
    good = {"field": "quality", "op": "eq", "value": "good"}
    tree.svc.create("encounter", "x", holder="selection", filter_tree=good)

    no_filter = tree.svc.update("encounter", "x", filter_tree=None)
    any_kind = tree.svc.update("encounter", "x", holder=None)

    assert no_filter.filter_tree is None and no_filter.holder == "selection"
    assert any_kind.holder is None


def test_a_rename_cannot_take_another_exports_name(ctx: AppContext, tree) -> None:
    tree.svc.create("encounter", "a")
    tree.svc.create("encounter", "b")

    with pytest.raises(AlreadyExistsError):
        tree.svc.update("encounter", "a", new_name="b")
    # Keeping its own name is fine.
    assert tree.svc.update("encounter", "a", new_name="a").name == "a"


def test_an_export_can_be_deleted_and_a_missing_one_is_not_found(
    ctx: AppContext, tree
) -> None:
    tree.svc.create("encounter", "a")
    ctx.commit()

    tree.svc.delete("encounter", "a")

    assert tree.svc.list_for("encounter") == []
    with pytest.raises(NotFoundError):
        tree.svc.get("encounter", "a")
    with pytest.raises(NotFoundError):
        tree.svc.delete("encounter", "a")
    with pytest.raises(NotFoundError):
        tree.svc.list_for("nope")


# -- where it is offered --------------------------------------------------------------


def _names(defs) -> list[str]:
    return sorted(d.name for d in defs)


def test_an_export_is_offered_from_its_schema_down_to_the_kind_that_holds_the_files(
    ctx: AppContext, tree
) -> None:
    tree.svc.create("encounter", "contours", holder="selection", fields=["contour"])

    assert _names(tree.svc.available_on("encounter")) == ["contours"]
    assert _names(tree.svc.available_on("recording")) == ["contours"]
    assert _names(tree.svc.available_on("selection")) == ["contours"]
    assert tree.svc.available_on("site") == []


def test_it_is_not_offered_above_the_schema_it_is_saved_with(
    ctx: AppContext, tree
) -> None:
    tree.svc.create("recording", "audio only", holder="recording", fields=["audio"])

    assert tree.svc.available_on("encounter") == []
    assert _names(tree.svc.available_on("recording")) == ["audio only"]
    # A Selection record is beneath the Recording but holds no Recording-kind files
    # of its own below it, so it is not offered there.
    assert tree.svc.available_on("selection") == []


def test_an_any_kind_export_is_offered_on_every_schema_in_its_tree(
    ctx: AppContext, tree
) -> None:
    tree.svc.create("recording", "everything")

    assert _names(tree.svc.available_on("recording")) == ["everything"]
    assert _names(tree.svc.available_on("selection")) == ["everything"]
    assert tree.svc.available_on("encounter") == []


def test_a_collection_is_offered_the_exports_of_the_schemas_it_is_for(
    ctx: AppContext, tree
) -> None:
    tree.svc.create("encounter", "a")
    tree.svc.create("site", "scans", holder="site")

    assert _names(tree.svc.for_collection(["encounter", "recording"])) == ["a"]
    assert _names(tree.svc.for_collection(["site"])) == ["scans"]
    assert tree.svc.for_collection([]) == []
    assert tree.svc.for_collection(["nope"]) == []


# -- running it -----------------------------------------------------------------------


def test_the_selection_for_a_run_is_the_definition_in_a_collection_or_a_record(
    ctx: AppContext, tree
) -> None:
    good = {"field": "quality", "op": "eq", "value": "good"}
    d = tree.svc.create(
        "encounter",
        "x",
        holder="selection",
        fields=["contour"],
        filter_tree=good,
        files_layout="grouped",
    )

    run = tree.svc.selection(d, collection="hb", within="abcd")

    assert isinstance(run, FileSelection)
    assert (run.query.dataset, run.query.schema, run.query.within) == (
        "hb",
        "selection",
        "abcd",
    )
    assert run.query.filter_tree == good
    assert (run.fields, run.layout, run.schemas) == (["contour"], "grouped", None)


def test_an_any_kind_export_stays_within_its_schemas_own_tree(
    ctx: AppContext, tree
) -> None:
    d = tree.svc.create("encounter", "x")

    run = tree.svc.selection(d, collection="hb")

    assert run.query.schema is None
    assert sorted(run.schemas or []) == ["encounter", "recording", "selection"]


def test_running_for_a_collection_takes_just_the_chosen_fields_from_every_selection(
    ctx: AppContext, tree
) -> None:
    tree.sel("s1")
    tree.sel("s2")
    d = tree.svc.create(
        "encounter",
        "contours",
        holder="selection",
        fields=["contour"],
        files_layout="flat",
    )

    plan = ctx.file_access_svc.plan(tree.svc.selection(d, collection="hb"))

    assert sorted(i.path for i in plan.items) == ["s1.contour", "s2.contour"]


def test_running_within_an_encounter_groups_what_it_finds(
    ctx: AppContext, tree
) -> None:
    tree.sel("s1")
    d = tree.svc.create(
        "encounter",
        "grouped",
        holder="selection",
        fields=["contour"],
        files_layout="grouped",
    )

    plan = ctx.file_access_svc.plan(tree.svc.selection(d, within=str(tree.e7.id)))

    assert [i.path for i in plan.items] == ["Rec A/Selections/s1.contour"]


def test_a_filter_narrows_which_records_are_exported(ctx: AppContext, tree) -> None:
    tree.sel("good1", "good")
    tree.sel("bad1", "bad")
    d = tree.svc.create(
        "encounter",
        "good only",
        holder="selection",
        fields=["contour"],
        files_layout="flat",
        filter_tree={"field": "quality", "op": "eq", "value": "good"},
    )

    plan = ctx.file_access_svc.plan(tree.svc.selection(d, collection="hb"))

    assert [i.path for i in plan.items] == ["good1.contour"]


def test_any_kind_takes_every_file_in_the_tree_but_not_other_schemas_files(
    ctx: AppContext, tree
) -> None:
    ctx.record_svc.update(
        str(tree.rec.id), {"rname": "Rec A", "audio": tree.file(b"wav", "a.wav")}
    )
    tree.sel("s1")
    d = tree.svc.create("encounter", "all", files_layout="flat")

    plan = ctx.file_access_svc.plan(tree.svc.selection(d, collection="hb"))

    # The recording's audio and the selection's contour and table; the Site's
    # scan, in the same collection, is not in an encounter's tree.
    assert sorted(i.path for i in plan.items) == ["a.wav", "s1.contour", "s1.table"]


def test_any_kind_within_an_encounter_excludes_other_schemas_too(
    ctx: AppContext, tree
) -> None:
    tree.sel("s1")
    d = tree.svc.create("recording", "all", files_layout="flat")

    inside = ctx.file_access_svc.plan(tree.svc.selection(d, within=str(tree.rec.id)))

    assert sorted(i.path for i in inside.items) == ["s1.contour", "s1.table"]
