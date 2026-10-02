"""Managing placements: persistence by collection id, validation, and what
happens to them when a volume is removed or a collection is renamed/purged."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from civex.config import PlacementConfig, load_config
from civex.context import AppContext
from civex.domain.exceptions import NotFoundError, ValidationError


def _drive(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "mnt" / name
    path.mkdir(parents=True)
    return path


def test_set_placement_is_saved_in_config_keyed_by_collection_id(
    ctx: AppContext, tmp_path: Path, make_collection
) -> None:
    ctx.store_svc.add_volume("archive", str(_drive(tmp_path, "archive")))
    study = make_collection("study")

    ctx.store_svc.set_placement(str(study.id), "archive", "fail")

    saved = load_config().store_config.placement
    assert saved == {str(study.id): PlacementConfig("archive", "fail")}
    assert "study" not in (Path.cwd() / "_civex" / "config.toml").read_text()


def test_set_placement_validates_its_input(ctx: AppContext, tmp_path: Path) -> None:
    ctx.store_svc.add_volume("archive", str(_drive(tmp_path, "archive")))
    cid = str(uuid.uuid4())

    with pytest.raises(ValidationError, match="not a collection id"):
        ctx.store_svc.set_placement("study", "archive")
    with pytest.raises(NotFoundError, match="Volume 'nope'"):
        ctx.store_svc.set_placement(cid, "nope")
    with pytest.raises(ValidationError, match="spill, fail"):
        ctx.store_svc.set_placement(cid, "archive", "sometimes")
    assert ctx.store_svc.placements() == {}


def test_clear_placement(ctx: AppContext, tmp_path: Path) -> None:
    ctx.store_svc.add_volume("archive", str(_drive(tmp_path, "archive")))
    cid = str(uuid.uuid4())
    ctx.store_svc.set_placement(cid, "archive")

    assert ctx.store_svc.clear_placement(cid) is True
    assert ctx.store_svc.clear_placement(cid) is False
    assert load_config().store_config.placement == {}


def test_renaming_a_collection_changes_nothing(
    ctx: AppContext, tmp_path: Path, make_collection
) -> None:
    ctx.store_svc.add_volume("archive", str(_drive(tmp_path, "archive")))
    study = make_collection("study")
    ctx.store_svc.set_placement(str(study.id), "archive")

    ctx.dataset_svc.update("study", new_name="trial")
    ctx.commit()

    assert str(study.id) in load_config().store_config.placement
    store = ctx.file_svc._store
    assert store.put(b"after rename", "a.txt", str(study.id)).volume == "archive"


def test_purging_a_collection_drops_its_placement(
    ctx: AppContext, tmp_path: Path, make_collection
) -> None:
    ctx.store_svc.add_volume("archive", str(_drive(tmp_path, "archive")))
    study = make_collection("study")
    keep = make_collection("keep")
    ctx.store_svc.set_placement(str(study.id), "archive")
    ctx.store_svc.set_placement(str(keep.id), "archive")

    ctx.dataset_svc.delete("study")
    assert str(study.id) in ctx.store_svc.placements()  # recoverable until purged
    ctx.dataset_svc.purge("study")

    assert set(ctx.store_svc.placements()) == {str(keep.id)}


def test_a_volume_that_homes_a_collection_cannot_be_removed_without_force(
    ctx: AppContext, tmp_path: Path, make_collection
) -> None:
    ctx.store_svc.add_volume("archive", str(_drive(tmp_path, "archive")))
    study = make_collection("study")
    ctx.store_svc.set_placement(str(study.id), "archive")

    with pytest.raises(ValidationError, match="1 collection\\(s\\) are homed"):
        ctx.store_svc.remove_volume("archive")
    assert "archive" in ctx.store_svc._config.store_config.volumes

    ctx.store_svc.remove_volume("archive", force=True)

    assert "archive" not in load_config().store_config.volumes
    assert load_config().store_config.placement == {}


def test_files_added_through_the_cli_path_follow_the_collections_home(
    ctx: AppContext, tmp_path: Path, make_collection
) -> None:
    ctx.store_svc.add_volume("archive", str(_drive(tmp_path, "archive")))
    study = make_collection("study")
    ctx.store_svc.set_placement(str(study.id), "archive")
    src = tmp_path / "data.bin"
    src.write_bytes(b"typed at the prompt")

    value = ctx.record_svc.coerce_value(
        str(src), "file", "attachment", collection_id=str(study.id)
    )
    elsewhere = ctx.record_svc.coerce_value(str(src), "file", "attachment")

    assert value["volume"] == "archive"
    # The same bytes again, from anywhere, are the one existing copy.
    assert elsewhere["volume"] == "archive"
    assert elsewhere["sha256"] == value["sha256"]


def test_a_workflow_plugin_stores_files_in_the_trigger_records_collection(
    ctx: AppContext, tmp_path: Path, make_collection, make_schema, make_record
) -> None:
    from civex.plugins.base import WorkflowContext

    ctx.store_svc.add_volume("archive", str(_drive(tmp_path, "archive")))
    study = make_collection("study")
    make_schema("doc")
    record = make_record("study", "doc", {})
    ctx.store_svc.set_placement(str(study.id), "archive")
    wf = WorkflowContext(
        record=record, dataset=ctx.dataset_svc.get("study"), _app_ctx=ctx
    )

    assert wf.store_file(b"made by a plugin", "out.txt").volume == "archive"
