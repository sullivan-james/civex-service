"""The path rule for reaching stored files by name and hierarchy."""

from __future__ import annotations

from civex.domain.file_access import (
    MAX_SEGMENT,
    FileItem,
    FilePlan,
    folder_segments,
    file_names_in_folder,
    safe_segment,
)


def test_safe_segment_replaces_what_a_filesystem_refuses() -> None:
    assert safe_segment('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"
    assert safe_segment("  Encounter 7.  ") == "Encounter 7"


def test_safe_segment_never_returns_something_empty_or_dotty() -> None:
    assert safe_segment("") == "_"
    assert safe_segment(None, "fallback") == "fallback"
    assert safe_segment("..") == "_"
    assert safe_segment("...   ") == "_"


def test_safe_segment_refuses_windows_device_names() -> None:
    assert safe_segment("CON") == "_CON"
    assert safe_segment("nul.txt") == "_nul.txt"
    assert safe_segment("console.txt") == "console.txt"


def test_safe_segment_caps_length_but_keeps_the_extension() -> None:
    out = safe_segment("x" * 300 + ".txt")
    assert len(out) == MAX_SEGMENT and out.endswith(".txt")


def test_siblings_with_the_same_name_are_told_apart_and_only_they_are() -> None:
    parents = {"a" * 32: None, "b" * 32: None, "c" * 32: None}
    names = {"a" * 32: "Recording 3", "b" * 32: "recording 3", "c" * 32: "Other"}

    out = folder_segments(parents, names)

    # Case differences count as the same name: a Windows or macOS drive does.
    assert out["a" * 32] == "Recording 3~aaaaaaaa"
    assert out["b" * 32] == "recording 3~bbbbbbbb"
    assert out["c" * 32] == "Other"


def test_the_same_name_under_different_parents_is_not_a_clash() -> None:
    parents = {"a" * 32: None, "b" * 32: "p" * 32, "c" * 32: "q" * 32}
    names = {"a" * 32: "x", "b" * 32: "Recording", "c" * 32: "Recording"}

    out = folder_segments(parents, names)

    assert out["b" * 32] == out["c" * 32] == "Recording"


def test_a_nameless_record_is_named_by_its_id() -> None:
    assert folder_segments({"abcdef0123": None}, {})["abcdef0123"] == "abcdef01"


def test_files_in_one_folder_with_the_same_name_keep_their_extension() -> None:
    names, repeats = file_names_in_folder(
        [("table.txt", "1" * 64), ("Table.txt", "2" * 64), ("other.txt", "3" * 64)]
    )

    assert names == ["table~11111111.txt", "Table~22222222.txt", "other.txt"]
    assert repeats == 0


def test_the_same_file_twice_in_a_folder_is_one_file() -> None:
    names, repeats = file_names_in_folder(
        [("table.txt", "1" * 64), ("table.txt", "1" * 64)]
    )

    assert names == ["table.txt", None]
    assert repeats == 1


def _item(path: str, available: bool, volume: str | None = "default") -> FileItem:
    return FileItem(
        path=path,
        sha256="0" * 64,
        filename=path,
        size=10,
        record_id="r",
        record_name="R",
        field="f",
        volume=volume,
        available=available,
        reason="" if available else "not connected",
    )


def test_a_plan_with_everything_reachable_is_complete() -> None:
    plan = FilePlan(items=[_item("a", True), _item("b", True)])

    assert plan.complete and plan.total == 2 and plan.bytes == 20
    assert plan.summary() == "2 file(s), all available."


def test_a_plan_pages_its_items_but_totals_cover_all_of_them() -> None:
    plan = FilePlan(items=[_item(c, True) for c in "abcde"])

    page = plan.to_dict(offset=1, limit=2)

    assert [i["path"] for i in page["items"]] == ["b", "c"]
    assert page["total"] == 5
    assert plan.to_dict(include_items=False)["items"] == []


# -- grouped folders and naming by owner ---------------------------------------------


def test_a_kind_of_record_becomes_a_plural_folder() -> None:
    from civex.domain.file_access import group_folder, pluralize

    assert pluralize("Selection") == "Selections"
    assert pluralize("Contour File") == "Contour Files"
    assert pluralize("Study") == "Studies"
    assert pluralize("Day") == "Days"  # a vowel before the y keeps it
    assert pluralize("Class") == "Classes"
    assert pluralize("Box") == "Boxes"
    assert pluralize("Batch") == "Batches"
    assert pluralize("") == ""
    assert group_folder("Sel/ection") == "Sel_ections"  # still a safe name


def test_a_clash_in_a_shared_folder_is_told_apart_by_the_record_that_owns_each() -> (
    None
):
    names, repeats = file_names_in_folder(
        [
            ("table.txt", "1" * 64, "Selection 1"),
            ("table.txt", "2" * 64, "Selection 2"),
            ("other.txt", "3" * 64, "Selection 1"),
        ]
    )

    assert names == ["Selection 1 - table.txt", "Selection 2 - table.txt", "other.txt"]
    assert repeats == 0


def test_owners_that_are_not_distinct_fall_back_to_the_hash() -> None:
    same_owner = file_names_in_folder(
        [("t.txt", "1" * 64, "Sel"), ("t.txt", "2" * 64, "Sel")]
    )[0]
    same_name_other_case = file_names_in_folder(
        [("t.txt", "1" * 64, "Sel"), ("t.txt", "2" * 64, "sel")]
    )[0]
    missing_owner = file_names_in_folder(
        [("t.txt", "1" * 64, "Sel"), ("t.txt", "2" * 64, None)]
    )[0]

    for names in (same_owner, same_name_other_case, missing_owner):
        assert all(n.startswith("t~") and n.endswith(".txt") for n in names)


def test_the_same_file_twice_is_still_one_file_when_owners_are_given() -> None:
    names, repeats = file_names_in_folder(
        [("t.txt", "1" * 64, "A"), ("t.txt", "1" * 64, "B")]
    )

    assert names == ["t.txt", None] and repeats == 1


def test_there_are_three_layouts() -> None:
    from civex.domain.file_access import LAYOUTS

    assert LAYOUTS == ("tree", "grouped", "flat")
