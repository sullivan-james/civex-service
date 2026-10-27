"""A bundle carries a project's data to another project: schemas, collections,
records with their ids (so parents and references survive), the files the
records cite (optional), workflows and plugins. Reading one in matches by name
and id, defers a record until what it needs is here, and is one event in
history."""

from __future__ import annotations

import hashlib
import json
import uuid
import zipfile
from pathlib import Path

import pytest

from civex.context import AppContext
from civex.domain import bundle as spec
from civex.domain.bundle import BundleError, ExportOptions, RecordLine
from civex.testing.projects import Projects


@pytest.fixture()
def other(tmp_path: Path):
    projects = Projects(tmp_path / "others")
    yield projects("other")
    projects.close()


def _study(ctx: AppContext) -> dict[str, uuid.UUID]:
    """A small project: two kinds, a reference, a child, a file."""
    ctx.schema_svc.create("species", label="Species")
    ctx.schema_svc.add_field("species", "common_name", "string", label="Common name")
    ctx.schema_svc.create("encounter")
    ctx.schema_svc.add_field(
        "encounter", "species", "reference", restrictions={"schema": "species"}
    )
    ctx.schema_svc.add_field(
        "encounter",
        "depth",
        "float",
        restrictions={"min": 0, "unit": "m"},
        default_value=1.5,
    )
    ctx.schema_svc.add_field(
        "encounter",
        "photo",
        "file",
        restrictions={"filename_template": "{depth}-{species}"},
    )
    ctx.schema_svc.update("encounter", display_template="{depth}")
    ctx.schema_svc.set_unique_keys("species", [["common_name"]])
    ctx.schema_svc.create("note", parent="encounter")
    ctx.schema_svc.add_field("note", "text", "string")
    ctx.dataset_svc.create("study", timezone="Europe/London", scope="global")
    ctx.dataset_svc.create("empty")
    ref = ctx.file_svc.store_bytes(b"photo bytes", "p.jpg")
    seal = ctx.record_svc.add("study", "species", {"common_name": "Grey seal"})
    enc = ctx.record_svc.add(
        "study",
        "encounter",
        {"species": str(seal.id), "depth": 12.5, "photo": ref.to_dict()},
    )
    note = ctx.record_svc.add(
        "study", "note", {"text": "calm"}, parent_record_id=str(enc.id)
    )
    ctx.commit()
    return {"seal": seal.id, "enc": enc.id, "note": note.id, "sha": ref.sha256}


def test_a_bundle_round_trips_structure_records_ids_and_files(
    ctx: AppContext, other: AppContext, tmp_path: Path
) -> None:
    ids = _study(ctx)
    path = tmp_path / "b.civex.zip"
    plan = ctx.bundle_svc.export(path)
    assert (plan.schemas, plan.records, plan.files) == (3, 3, 1)
    assert plan.collections == ["study", "empty"]

    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read(spec.MANIFEST))
    assert {spec.MANIFEST, spec.RECORDS, spec.FILES_DIR + ids["sha"]} <= names
    assert manifest["format"] == spec.FORMAT
    assert [s["name"] for s in manifest["schemas"]] == ["species", "encounter", "note"]
    assert manifest["files"] == {
        "included": True,
        "count": 1,
        "bytes": len(b"photo bytes"),
        "missing": [],
    }

    result = other.bundle_svc.import_bundle(path)
    other.commit()
    assert result.schemas_new == 3 and result.collections_new == 2
    assert result.records_added == 3 and result.records_skipped == 0
    assert result.files_added == 1 and result.skipped == []

    fields = {f.name: f for f in other.schema_svc.get("encounter").fields}
    assert fields["species"].restrictions == {"schema": "species"}
    assert fields["depth"].restrictions == {"min": 0, "unit": "m"}
    assert fields["depth"].default_value == 1.5
    assert fields["photo"].restrictions == {"filename_template": "{depth}-{species}"}
    assert other.schema_svc.get("encounter").display_template == "{depth}"
    assert other.schema_svc.get("species").label == "Species"
    assert other.schema_svc.get("species").fields[0].label == "Common name"
    assert other.schema_svc.get("species").unique_key_names == [["common_name"]]
    study = other.dataset_svc.get("study")
    assert (study.timezone, study.scope) == ("Europe/London", "global")

    enc = other.record_svc.get(str(ids["enc"]))  # the same id
    assert enc.data["species"] == str(ids["seal"])
    assert enc.data["photo"]["sha256"] == ids["sha"]
    note = other.record_svc.get(str(ids["note"]))
    assert note.parent_record_id == ids["enc"]
    assert enc.created_at == ctx.record_svc.get(str(ids["enc"])).created_at
    assert other.file_svc.retrieve(ids["sha"]) == b"photo bytes"


def test_records_are_written_a_page_at_a_time(
    ctx: AppContext, make_schema, make_collection, tmp_path: Path
) -> None:
    make_schema("patient", fields=[("name", "string")])
    make_collection("a")
    for i in range(520):  # more than one stream page (500)
        ctx.record_svc.add("a", "patient", {"name": f"p{i}"})
    ctx.commit()
    path = tmp_path / "b.zip"
    assert ctx.bundle_svc.export(path).records == 520
    with zipfile.ZipFile(path) as zf:
        lines = [
            RecordLine.parse(line)
            for line in zf.read(spec.RECORDS).decode().splitlines()
        ]
    assert len(lines) == 520 and {line.collection for line in lines} == {"a"}


def test_without_files_or_data(ctx: AppContext, other: AppContext, tmp_path: Path):
    ids = _study(ctx)
    path = tmp_path / "nofiles.zip"
    plan = ctx.bundle_svc.export(path, ExportOptions(include_files=False))
    assert plan.files == 1 and not plan.include_files
    with zipfile.ZipFile(path) as zf:
        assert not any(n.startswith(spec.FILES_DIR) for n in zf.namelist())
        assert json.loads(zf.read(spec.MANIFEST))["files"]["included"] is False
    result = other.bundle_svc.import_bundle(path)
    other.commit()
    # The record keeps citing its file; the file itself isn't here.
    assert result.records_added == 3 and result.files_missing == 1
    assert other.record_svc.get(str(ids["enc"])).data["photo"]["sha256"] == ids["sha"]
    assert not other.file_svc.exists(ids["sha"])

    structure = tmp_path / "structure.zip"
    plan = ctx.bundle_svc.export(structure, ExportOptions(include_records=False))
    assert plan.records == 0 and plan.collections == []
    with zipfile.ZipFile(structure) as zf:
        assert spec.RECORDS not in zf.namelist()


def test_only_some_collections(ctx: AppContext, make_schema, tmp_path: Path):
    make_schema("patient", fields=[("name", "string")])
    for name in ("a", "b"):
        ctx.dataset_svc.create(name)
        ctx.record_svc.add(name, "patient", {"name": name})
    ctx.commit()
    plan = ctx.bundle_svc.plan_export(ExportOptions(collections=["b"]))
    assert plan.collections == ["b"] and plan.records == 1
    with pytest.raises(Exception, match="not found"):
        ctx.bundle_svc.plan_export(ExportOptions(collections=["nope"]))


def test_a_child_listed_before_its_parent_still_links(
    ctx: AppContext, other: AppContext, tmp_path: Path
) -> None:
    ids = _study(ctx)
    path = tmp_path / "b.zip"
    ctx.bundle_svc.export(path, ExportOptions(include_files=False))
    shuffled = tmp_path / "shuffled.zip"
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(shuffled, "w") as dst:
        for name in src.namelist():
            data = src.read(name)
            if name == spec.RECORDS:
                lines = data.decode().splitlines()
                # note, encounter, species: each needs the one after it
                order = {str(ids["note"]): 0, str(ids["enc"]): 1, str(ids["seal"]): 2}
                lines.sort(key=lambda line: order[json.loads(line)["id"]])
                data = ("\n".join(lines) + "\n").encode()
            dst.writestr(name, data)
    result = other.bundle_svc.import_bundle(shuffled)
    other.commit()
    assert result.records_added == 3 and result.records_skipped == 0
    assert other.record_svc.get(str(ids["note"])).parent_record_id == ids["enc"]


def test_what_is_already_here_is_left_alone(
    ctx: AppContext, other: AppContext, tmp_path: Path
) -> None:
    ids = _study(ctx)
    path = tmp_path / "b.zip"
    ctx.bundle_svc.export(path)
    # The other project already has part of it: a schema with one field, the
    # collection, and one record, edited.
    other.schema_svc.create("species")
    other.schema_svc.add_field("species", "common_name", "string")
    other.dataset_svc.create("study")
    other.commit()
    other.bundle_svc.import_bundle(path)
    other.commit()
    other.record_svc.update(str(ids["seal"]), {"common_name": "Harbour seal"})
    other.commit()

    result = other.bundle_svc.import_bundle(path)
    other.commit()
    assert result.schemas_new == 0 and result.schemas_existing == [
        "species",
        "encounter",
        "note",
    ]
    assert result.collections_new == 0 and result.collections_existing == [
        "study",
        "empty",
    ]
    assert result.records_added == 0 and result.records_existing == 3
    assert other.record_svc.get(str(ids["seal"])).data["common_name"] == "Harbour seal"


def test_a_record_whose_parent_is_nowhere_is_skipped_and_named(
    ctx: AppContext, other: AppContext, tmp_path: Path
) -> None:
    ids = _study(ctx)
    path = tmp_path / "b.zip"
    ctx.bundle_svc.export(path, ExportOptions(include_files=False))
    without_parent = tmp_path / "orphan.zip"
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(without_parent, "w") as dst:
        for name in src.namelist():
            data = src.read(name)
            if name == spec.RECORDS:
                lines = [
                    line
                    for line in data.decode().splitlines()
                    if json.loads(line)["id"] != str(ids["enc"])
                ]
                data = ("\n".join(lines) + "\n").encode()
            dst.writestr(name, data)
    result = other.bundle_svc.import_bundle(without_parent)
    other.commit()
    assert result.records_added == 1  # the species
    assert result.records_skipped == 1
    assert result.skipped[0].id == str(ids["note"])
    assert "not found" in result.skipped[0].reason
    assert not other.record_svc.exists(str(ids["note"]))


def test_a_parent_in_another_collection_is_refused_not_written(
    ctx: AppContext, other: AppContext, tmp_path: Path
) -> None:
    """CIVEX-168: a crafted bundle can't put a child under a parent in a
    different collection."""
    ctx.schema_svc.create("trigger")
    ctx.schema_svc.create("child", parent="trigger")
    ctx.dataset_svc.create("ds1")
    ctx.dataset_svc.create("ds2")
    trigger = ctx.record_svc.add("ds1", "trigger", {})
    ctx.commit()
    path = tmp_path / "b.zip"
    ctx.bundle_svc.export(path)
    crafted = tmp_path / "crafted.zip"
    child = RecordLine(uuid.uuid4(), "ds2", "child", trigger.id, {})
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(crafted, "w") as dst:
        for name in src.namelist():
            data = src.read(name)
            if name == spec.RECORDS:
                data += (child.to_json() + "\n").encode()
            dst.writestr(name, data)
    result = other.bundle_svc.import_bundle(crafted)
    other.commit()
    assert result.records_added == 1 and result.records_skipped == 1
    assert result.skipped[0].id == str(child.id)
    assert other.record_svc.find("ds2", schema_name="child", filters=[]) == []


def test_a_file_whose_bytes_do_not_match_is_refused(
    ctx: AppContext, other: AppContext, tmp_path: Path
) -> None:
    ids = _study(ctx)
    path = tmp_path / "b.zip"
    ctx.bundle_svc.export(path)
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(tampered, "w") as dst:
        for name in src.namelist():
            data = src.read(name)
            if name == spec.FILES_DIR + ids["sha"]:
                data = b"something else"
            dst.writestr(name, data)
    result = other.bundle_svc.import_bundle(tampered)
    other.commit()
    assert result.files_added == 0 and result.files_refused == 1
    assert not other.file_svc.exists(ids["sha"])
    assert not other.file_svc.exists(hashlib.sha256(b"something else").hexdigest())


def test_an_import_is_one_event_in_history(
    ctx: AppContext, other: AppContext, tmp_path: Path
) -> None:
    _study(ctx)
    path = tmp_path / "study.civex.zip"
    ctx.bundle_svc.export(path)
    other.bundle_svc.import_bundle(path)
    other.commit()
    events, total = other.history_svc.events(
        {"field": "kind", "op": "eq", "value": "record"}
    )
    assert total == 1
    assert events[0].batch is not None
    assert (events[0].batch.kind, events[0].batch.label) == (
        "import",
        "study.civex.zip",
    )
    assert events[0].count == 3


def test_workflows_and_plugins_travel_as_files(
    ctx: AppContext, other: AppContext, project_dir: Path, tmp_path: Path
) -> None:
    civex_dir = project_dir / "_civex"
    (civex_dir / "workflows").mkdir(exist_ok=True)
    (civex_dir / "plugins").mkdir(exist_ok=True)
    (civex_dir / "workflows" / "tidy.yaml").write_text("name: tidy\nsteps: []\n")
    (civex_dir / "plugins" / "mine.py").write_text("class Plugin: ...\n")
    (civex_dir / "plugins" / "notes.txt").write_text("not a plugin")
    path = tmp_path / "b.zip"
    plan = ctx.bundle_svc.export(path)
    assert (plan.workflows, plan.plugins) == (1, 1)
    # A member with a path in its name is never written anywhere.
    with zipfile.ZipFile(path, "a") as zf:
        zf.writestr(spec.PLUGINS_DIR + "../escape.py", "x")
        zf.writestr(spec.PLUGINS_DIR + ".hidden.py", "x")
    result = other.bundle_svc.import_bundle(path)
    other.commit()
    assert (result.workflows, result.plugins) == (1, 1)
    assert {s.id for s in result.members_skipped} == {
        "plugins/../escape.py",
        "plugins/.hidden.py",
    }
    other_dir = other.config.civex_dir
    assert (
        other_dir / "workflows" / "tidy.yaml"
    ).read_text() == "name: tidy\nsteps: []\n"
    assert (other_dir / "plugins" / "mine.py").exists()
    assert not (other_dir / "escape.py").exists()


def test_what_is_not_a_bundle_is_refused(ctx: AppContext, tmp_path: Path) -> None:
    text = tmp_path / "x.zip"
    text.write_text("not a zip")
    with pytest.raises(BundleError, match="not a civex bundle"):
        ctx.bundle_svc.inspect(text)
    no_manifest = tmp_path / "y.zip"
    with zipfile.ZipFile(no_manifest, "w") as zf:
        zf.writestr("other.txt", "x")
    with pytest.raises(BundleError, match="bundle.json"):
        ctx.bundle_svc.inspect(no_manifest)
    newer = tmp_path / "z.zip"
    with zipfile.ZipFile(newer, "w") as zf:
        zf.writestr(spec.MANIFEST, json.dumps({"format": spec.FORMAT + 1}))
    with pytest.raises(BundleError, match="newer civex"):
        ctx.bundle_svc.inspect(newer)
