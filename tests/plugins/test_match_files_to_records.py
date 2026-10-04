"""`civex.match_files_to_records` must not attach a file to a record another file
in the same run also belongs to.

A real run had 64 files for selections 1 to 156 and the pattern `sel_([0-9]{2})`,
which reads two digits: selections 103, 108, 111, 149 and so on came out as 10, 10,
11 and 14, and each overwrote the contour file of a selection it had nothing to do
with, while the run reported 64 files and touched 47 records."""

from __future__ import annotations

import pytest

from civex.plugins.base import WorkflowContext
from civex.plugins.registry import get_plugin


@pytest.fixture()
def setup(ctx, make_collection, make_schema, make_record):
    dataset = make_collection("study")
    make_schema("recording", fields=[])
    parent = make_record("study", "recording", {})
    ctx.schema_svc.create("selection", parent="recording")
    ctx.schema_svc.add_field("selection", "selection_number", "integer")
    ctx.schema_svc.add_field("selection", "contour_file", "file")
    ctx.commit()
    return WorkflowContext(record=parent, dataset=dataset, _app_ctx=ctx), parent


def _files(ctx, *names: str) -> list[dict]:
    return [ctx.file_svc.store_bytes(n.encode(), n).to_dict() for n in names]


def _match(wf_ctx, files, pattern: str):
    registration = get_plugin("civex.match_files_to_records")
    config = registration.config_model(
        schema="selection",
        key_field="selection_number",
        file_field="contour_file",
        pattern=pattern,
    )
    return registration.invoke({"files": files}, config, wf_ctx, 60.0).outputs


def _selections(ctx, parent) -> dict[int, str]:
    found = ctx.record_svc.find(
        "study", schema_name="selection", parent_record_id=str(parent.id), limit=500
    )
    return {
        r.data["selection_number"]: r.data["contour_file"]["filename"] for r in found
    }


def test_a_pattern_that_reads_too_little_attaches_nothing_wrong(ctx, setup) -> None:
    wf_ctx, parent = setup
    files = _files(
        ctx,
        "pc_sel_14_a.csv",  # selection 14
        "pc_sel_149_a.csv",  # selection 149, read as 14
        "pc_sel_142_a.csv",  # selection 142, read as 14
        "pc_sel_20_a.csv",  # selection 20: no clash
    )

    out = _match(wf_ctx, files, r"sel_([0-9]{2})")  # two digits: the mistake

    # The files that clash are left alone, none of them guessed at...
    assert out["created"] == 1 and out["updated"] == 0
    assert _selections(ctx, parent) == {20: "pc_sel_20_a.csv"}
    # ...and each is listed with the others it clashes with.
    assert len(out["ambiguous"]) == 3
    assert any(
        "pc_sel_149_a.csv" in a and "key 14" in a and "pc_sel_14_a.csv" in a
        for a in out["ambiguous"]
    )


def test_the_same_files_with_a_pattern_that_reads_the_whole_number(ctx, setup) -> None:
    wf_ctx, parent = setup
    files = _files(ctx, "pc_sel_14_a.csv", "pc_sel_149_a.csv", "pc_sel_142_a.csv")

    out = _match(wf_ctx, files, r"sel_([0-9]+)")

    assert out["created"] == 3 and out["ambiguous"] == []
    assert _selections(ctx, parent) == {
        14: "pc_sel_14_a.csv",
        149: "pc_sel_149_a.csv",
        142: "pc_sel_142_a.csv",
    }


def test_leading_zeros_still_mean_the_same_key(ctx, setup) -> None:
    wf_ctx, parent = setup
    files = _files(ctx, "x_sel_01_a.csv", "x_sel_1_b.csv")  # both are selection 1

    out = _match(wf_ctx, files, r"sel_([0-9]+)")

    assert out["created"] == 0 and len(out["ambiguous"]) == 2
    assert _selections(ctx, parent) == {}


def test_an_existing_record_is_still_updated_by_a_single_file(ctx, setup) -> None:
    wf_ctx, parent = setup
    _match(wf_ctx, _files(ctx, "old_sel_7.csv"), r"sel_([0-9]+)")

    out = _match(wf_ctx, _files(ctx, "new_sel_7.csv"), r"sel_([0-9]+)")

    assert out["updated"] == 1 and out["ambiguous"] == []
    assert _selections(ctx, parent) == {7: "new_sel_7.csv"}


def test_what_the_run_reports_adds_up(ctx, setup) -> None:
    wf_ctx, _ = setup
    files = _files(ctx, "a_sel_10.csv", "a_sel_103.csv", "a_sel_20.csv", "nope.csv")

    out = _match(wf_ctx, files, r"sel_([0-9]{2})")

    # Every file is somewhere: made a record, updated one, missed the pattern, or
    # was ambiguous. None is counted twice or lost.
    assert out["created"] + out["updated"] + len(out["unmatched"]) + len(
        out["ambiguous"]
    ) == len(files)
