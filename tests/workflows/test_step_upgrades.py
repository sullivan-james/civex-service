"""Step versions and the upgrade of workflow files (`workflows.upgrades`).

Golden tests: for every version-0 step, an example workflow and what it
becomes; for the version-1 steps, example workflows run with their expected
results. A step version's contract is its id, config keys and inputs/outputs; a
change to one needs a new version, an upgrade, and a golden pair here.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from civex.plugins.base import WorkflowContext
from civex.plugins.registry import all_plugins
from civex.workflows import executor
from civex.workflows.contract_validation import validate_workflow_contracts
from civex.workflows.definition import (
    WorkflowDef,
    load_workflow,
    parse_workflow,
    run_inputs,
)
from civex.workflows.upgrades import (
    LATEST,
    NeedsNewerCivex,
    WorkflowUpgradeError,
    split_step,
    upgrade_text,
)

GOLDEN = Path(__file__).parent / "golden"


def _upgraded(text: str) -> dict:
    return yaml.safe_load(upgrade_text(text)[0])


def _contract_errors(raw: dict) -> list[str]:
    wf = WorkflowDef.model_validate(raw)
    return [e.message for e in validate_workflow_contracts(wf, all_plugins())]


# -- the user's own workflows: the golden pairs ------------------------------


@pytest.mark.parametrize("name", sorted(p.name for p in (GOLDEN / "v0").glob("*.yaml")))
def test_a_version_0_workflow_upgrades_to_its_golden_version_1(name: str) -> None:
    old = (GOLDEN / "v0" / name).read_text()
    new, notes = upgrade_text(old)
    assert notes
    assert new == (GOLDEN / "v1" / name).read_text()
    # It is valid, and upgrading it again does nothing.
    assert _contract_errors(yaml.safe_load(new)) == []
    assert upgrade_text(new) == (new, [])


# -- every version-0 step ----------------------------------------------------

V0_CASES = {
    "load_file + parse_table merge into a Table step": (
        """
name: t
steps:
  - id: load
    plugin: civex.load_file
    config: {field: attachment}
  - id: parse
    plugin: civex.parse_table
    config: {delimiters: [comma, tab]}
    timeout: 90
    inputs: {bytes: load.bytes}
  - id: save
    plugin: civex.upsert_records
    config: {schema: item, key_field: sku, dataset: study}
    inputs: {table: parse.table}
""",
        [
            {
                "id": "parse",
                "plugin": "civex.table@1",
                "config": {"delimiters": ["comma", "tab"], "field": "attachment"},
                "timeout": 90,
            },
            {
                "id": "save",
                "plugin": "civex.save_records@1",
                "config": {
                    "schema": "item",
                    "if_exists": "update",
                    "match_on": ["sku"],
                    "dataset": "study",
                },
                "inputs": {"rows": "parse.table"},
            },
        ],
    ),
    "load_file_list becomes a Files step on a field": (
        """
name: t
steps:
  - id: files
    plugin: civex.load_file_list
    config: {field: attachments}
  - id: make
    plugin: civex.create_records_from_files
    config: {schema: att, file_field: f, context_record_id: abc}
    inputs: {files: files.files}
""",
        [
            {
                "id": "files",
                "plugin": "civex.files@1",
                "config": {"source": "field", "field": "attachments"},
            },
            {
                "id": "make",
                "plugin": "civex.save_records@1",
                "config": {
                    "schema": "att",
                    "if_exists": "add_new",
                    "parent_record_id": "abc",
                    "file_field": "f",
                },
                "inputs": {"files": "files.files"},
            },
        ],
    ),
    "rows_to_records keeps its match_on and mapping": (
        """
name: t
steps:
  - id: files
    plugin: civex.load_file_list
    config: {field: attachments}
  - id: t
    plugin: civex.table@1
    inputs: {files: files.files}
  - id: rows
    plugin: civex.rows_to_records
    config: {schema: item, match_on: [a, b], field_mapping: {A: a}, dataset: d}
    inputs: {table: t.table}
""",
        [
            {
                "id": "files",
                "plugin": "civex.files@1",
                "config": {"source": "field", "field": "attachments"},
            },
            {"id": "t", "plugin": "civex.table@1", "inputs": {"files": "files.files"}},
            {
                "id": "rows",
                "plugin": "civex.save_records@1",
                "config": {
                    "schema": "item",
                    "if_exists": "update",
                    "match_on": ["a", "b"],
                    "field_mapping": {"A": "a"},
                    "dataset": "d",
                },
                "inputs": {"rows": "t.table"},
            },
        ],
    ),
    "extract_from_filename is renamed": (
        """
name: t
steps:
  - id: when
    plugin: civex.extract_from_filename
    config: {field: f, pattern: '(\\d+)', output_type: integer}
""",
        [
            {
                "id": "when",
                "plugin": "civex.value_from_filename@1",
                "config": {"field": "f", "pattern": "(\\d+)", "output_type": "integer"},
            }
        ],
    ),
    "get_field + save_field become a from_field setting": (
        """
name: t
steps:
  - id: read
    plugin: civex.get_field
    config: {field: seed}
  - id: save
    plugin: civex.save_field
    config: {field: out}
    inputs: {value: read.value}
""",
        [
            {
                "id": "save",
                "plugin": "civex.set_fields@1",
                "config": {
                    "fields": {"out": {"from_field": "seed", "if_empty": "clear"}}
                },
            }
        ],
    ),
    "save_field after another step keeps its input": (
        """
name: t
steps:
  - id: when
    plugin: civex.extract_from_filename
    config: {field: f}
  - id: save
    plugin: civex.save_field
    config: {field: out}
    inputs: {value: when.value}
""",
        [
            {
                "id": "when",
                "plugin": "civex.value_from_filename@1",
                "config": {"field": "f"},
            },
            {
                "id": "save",
                "plugin": "civex.set_fields@1",
                "config": {"field": "out"},
                "inputs": {"value": "when.value"},
            },
        ],
    ),
    "save_fields takes its updates": (
        """
name: t
steps:
  - id: when
    plugin: civex.extract_from_filename
    config: {field: f}
  - id: save
    plugin: civex.save_fields
    inputs: {updates: when.value}
""",
        [
            {
                "id": "when",
                "plugin": "civex.value_from_filename@1",
                "config": {"field": "f"},
            },
            {
                "id": "save",
                "plugin": "civex.set_fields@1",
                "inputs": {"updates": "when.value"},
            },
        ],
    ),
    "match_files_to_records, run-time files, and an if": (
        """
name: t
inputs:
  wavs: {type: files, label: WAV files}
  note: {type: value}
steps:
  - id: put
    plugin: civex.match_files_to_records
    if: "wavs.files"
    config: {schema: sel, key_field: n, file_field: f, pattern: 'sel_(\\d+)'}
    inputs: {files: __input__.wavs}
""",
        [
            {
                "id": "wavs",
                "plugin": "civex.files@1",
                "config": {"source": "run", "label": "WAV files"},
            },
            {
                "id": "put",
                "plugin": "civex.save_records@1",
                "if": "wavs.files",
                "config": {
                    "schema": "sel",
                    "if_exists": "update",
                    "match_on": ["n"],
                    "filename_pattern": "sel_(\\d+)",
                    "file_field": "f",
                },
                "inputs": {"files": "wavs.files"},
            },
        ],
    ),
}


@pytest.mark.parametrize("case", list(V0_CASES))
def test_every_version_0_step_upgrades(case: str) -> None:
    text, expected_steps = V0_CASES[case]
    upgraded = _upgraded(text)
    assert upgraded["steps"] == expected_steps
    assert upgrade_text(yaml.dump(upgraded))[1] == []  # nothing left to upgrade


def test_a_value_input_stays_and_a_files_input_becomes_a_step() -> None:
    upgraded = _upgraded(
        V0_CASES["match_files_to_records, run-time files, and an if"][0]
    )
    assert upgraded["inputs"] == {"note": {"type": "value"}}


def test_a_new_step_id_never_collides_with_an_existing_one() -> None:
    upgraded = _upgraded(
        """
name: t
inputs:
  put: {type: files}
steps:
  - id: put
    plugin: civex.match_files_to_records
    config: {schema: s, key_field: k, file_field: f, pattern: '(\\d+)'}
    inputs: {files: __input__.put}
""".replace("__input__.put", "__input__.put.files")
    )
    # the input `put` clashes with the step `put`; the Files step gets a new id
    ids = [s["id"] for s in upgraded["steps"]]
    assert len(ids) == len(set(ids)) == 2


def test_run_inputs_lists_what_a_person_is_asked_for() -> None:
    wf = parse_workflow(
        V0_CASES["match_files_to_records, run-time files, and an if"][0]
    )
    asked = run_inputs(wf)
    assert asked["wavs"].type == "files" and asked["wavs"].label == "WAV files"
    assert asked["note"].type == "value"


# -- shapes that can't be upgraded by themselves ------------------------------


@pytest.mark.parametrize(
    "text,says",
    [
        (
            """
name: t
steps:
  - id: load
    plugin: civex.load_file
    config: {field: a}
  - id: parse
    plugin: civex.parse_table
    inputs: {bytes: load.bytes}
  - id: other
    plugin: project.something
    inputs: {name: load.filename}
""",
            "also used by 'other'",
        ),
        (
            """
name: t
steps:
  - id: mine
    plugin: project.make_bytes
  - id: parse
    plugin: civex.parse_table
    inputs: {bytes: mine.bytes}
""",
            "reads its bytes from something other than a file field",
        ),
        (
            """
name: t
steps:
  - id: read
    plugin: civex.get_field
    config: {field: a}
  - id: other
    plugin: project.something
    inputs: {x: read.value}
""",
            "Can't upgrade 'read'",
        ),
    ],
)
def test_an_upgrade_that_cannot_be_done_by_itself_is_refused_clearly(
    text: str, says: str
) -> None:
    with pytest.raises(WorkflowUpgradeError, match=says):
        upgrade_text(text)


def test_a_file_that_cannot_be_upgraded_is_left_untouched(tmp_path: Path) -> None:
    text = """
name: t
steps:
  - id: read
    plugin: civex.get_field
    config: {field: a}
  - id: other
    plugin: project.something
    inputs: {x: read.value}
"""
    path = tmp_path / "w.yaml"
    path.write_text(text)
    with pytest.raises(WorkflowUpgradeError):
        load_workflow(path)
    assert path.read_text() == text
    assert not list(tmp_path.glob("*.bak*"))


# -- versions ------------------------------------------------------------------


def test_a_step_version_this_civex_does_not_know_needs_a_newer_civex() -> None:
    text = """
name: t
steps:
  - id: s
    plugin: civex.save_records@99
    config: {schema: x}
"""
    with pytest.raises(NeedsNewerCivex, match="needs a newer civex"):
        upgrade_text(text)
    with pytest.raises(NeedsNewerCivex, match="civex.save_records@99"):
        parse_workflow(text)


def test_other_plugins_with_an_at_sign_are_not_ours_to_judge() -> None:
    text = "name: t\nsteps:\n  - id: s\n    plugin: project.thing@7\n"
    assert upgrade_text(text) == (text, [])


def test_the_versions_are_known_and_an_unversioned_id_is_version_0() -> None:
    assert split_step("civex.table@1") == ("civex.table", 1)
    assert split_step("civex.table") == ("civex.table", 0)
    assert split_step("project.x") == ("project.x", 0)
    assert all(v >= 1 for v in LATEST.values())


def test_an_unversioned_new_step_says_which_versions_exist() -> None:
    wf = WorkflowDef.model_validate(
        yaml.safe_load("name: t\nsteps:\n  - id: s\n    plugin: civex.save_records\n")
    )
    (error,) = validate_workflow_contracts(wf, all_plugins())
    assert "civex.save_records@1" in error.message


# -- the file on disk ------------------------------------------------------------


def test_loading_a_file_upgrades_it_and_keeps_the_old_text(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    old = (GOLDEN / "v0" / "upsert-sequences-from-wav-files.yaml").read_text()
    path = tmp_path / "w.yaml"
    path.write_text(old)

    with caplog.at_level(logging.WARNING, logger="civex.workflows.upgrades"):
        wf = load_workflow(path)

    assert [s.plugin for s in wf.steps] == ["civex.files@1", "civex.save_records@1"]
    assert (
        path.read_text()
        == (GOLDEN / "v1" / "upsert-sequences-from-wav-files.yaml").read_text()
    )
    assert (tmp_path / "w.yaml.bak").read_text() == old
    assert "Upgraded workflow w.yaml" in caplog.text and "w.yaml.bak" in caplog.text

    # A second load touches nothing, and an existing backup is never overwritten.
    stamp = path.stat().st_mtime_ns
    load_workflow(path)
    assert path.stat().st_mtime_ns == stamp
    path.write_text(old)
    load_workflow(path)
    assert (tmp_path / "w.yaml.bak").read_text() == old
    assert (tmp_path / "w.yaml.bak2").read_text() == old


def test_a_backup_is_not_taken_for_a_workflow(ctx) -> None:
    folder = ctx.workflow_svc._dir
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "w.yaml").write_text(
        (GOLDEN / "v0" / "upsert-units-from-wav-files.yaml").read_text()
    )
    assert [p.stem for p, _ in ctx.workflow_svc.list_defs()] == ["w"]
    assert (folder / "w.yaml.bak").exists()
    assert [p.stem for p, _ in ctx.workflow_svc.list_defs()] == ["w"]  # not 2
    assert [p.name for p in folder.glob("*.yaml")] == ["w.yaml"]


def test_an_unwritable_folder_still_loads_the_upgraded_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import civex.workflows.upgrades as upgrades

    old = (GOLDEN / "v0" / "upsert-units-from-wav-files.yaml").read_text()
    path = tmp_path / "w.yaml"
    path.write_text(old)

    def refuse(*a, **k):
        raise PermissionError("read-only")

    monkeypatch.setattr(upgrades.os, "replace", refuse)
    wf = load_workflow(path)
    assert wf.steps[0].plugin == "civex.files@1"
    assert path.read_text() == old


def test_a_workflow_needing_a_newer_civex_is_not_silently_hidden(
    ctx, caplog: pytest.LogCaptureFixture
) -> None:
    folder = ctx.workflow_svc._dir
    folder.mkdir(parents=True, exist_ok=True)
    text = "name: later\nsteps:\n  - id: s\n    plugin: civex.table@2\n"
    (folder / "later.yaml").write_text(text)

    with caplog.at_level(logging.WARNING):
        assert ctx.workflow_svc.list_defs() == []
    assert "needs a newer civex" in caplog.text
    from civex.domain.exceptions import ValidationError

    with pytest.raises(ValidationError, match="needs a newer civex"):
        ctx.workflow_svc.find_by_name("later")

    with pytest.raises(ValidationError, match="needs a newer civex"):
        ctx.workflow_svc.get("later")
    assert (folder / "later.yaml").read_text() == text  # never rewritten


def test_saving_an_old_workflow_saves_it_upgraded(ctx) -> None:
    old = (GOLDEN / "v0" / "parse-selection-table-to-units.yaml").read_text()
    path, wf = ctx.workflow_svc.save("units", old)
    assert wf.steps[0].plugin == "civex.table@1"
    assert (
        path.read_text()
        == (GOLDEN / "v1" / "parse-selection-table-to-units.yaml").read_text()
    )


# -- version 1 steps, run -----------------------------------------------------------


@pytest.fixture()
def selections(ctx, make_collection, make_schema, make_record):
    """A recording holding a selection table, with sequence selections below it."""
    dataset = make_collection("study")
    make_schema("recording", fields=[("rec_selection_table", "file")])
    ctx.schema_svc.create("sequence_selection", parent="recording")
    for name, dtype in (
        ("selection_number", "integer"),
        ("view", "string"),
        ("begin_time_s", "float"),
        ("seq_wav_file", "file"),
    ):
        ctx.schema_svc.add_field("sequence_selection", name, dtype)
    # The user's workflows leave match_on empty: the kind's unique key decides.
    ctx.schema_svc.set_unique_keys("sequence_selection", [["selection_number"]])
    ctx.commit()
    table = (
        b"Selection,View,Begin Time (s)\n"
        b"1,Spectrogram 1,0.5\n2,Spectrogram 1,1.5\n3,Spectrogram 1,2.5\n"
    )
    ref = ctx.file_svc.store_bytes(table, "sel.txt")
    record = make_record("study", "recording", {"rec_selection_table": ref.to_dict()})
    return WorkflowContext(record=record, dataset=dataset, _app_ctx=ctx), record


def _children(ctx, record) -> dict[int, dict]:
    found = ctx.record_svc.find(
        "study",
        schema_name="sequence_selection",
        parent_record_id=str(record.id),
        limit=100,
    )
    return {r.data["selection_number"]: r.data for r in found}


def test_the_selection_table_workflow_runs_and_a_second_run_changes_nothing(
    ctx, selections
) -> None:
    wf_ctx, record = selections
    wf = load_golden_v0("parse-selection-table-to-sequences.yaml")
    wf = WorkflowDef.model_validate(wf)
    # The golden table has more columns than this scratch kind: map only some.
    for step in wf.steps:
        if step.plugin == "civex.save_records@1":
            step.config["field_mapping"] = {
                "Selection": "selection_number",
                "View": "view",
                "Begin Time (s)": "begin_time_s",
            }

    first = executor.run(wf, wf_ctx, all_plugins())
    ctx.commit()
    assert first[-1]["outputs"]["created"] == 3
    assert _children(ctx, record)[2]["begin_time_s"] == 1.5

    again = executor.run(wf, wf_ctx, all_plugins())
    assert again[-1]["outputs"]["created"] == 0
    assert again[-1]["outputs"]["unchanged"] == 3
    assert len(_children(ctx, record)) == 3


def test_without_a_unique_key_an_upgraded_table_workflow_inserts_every_time_as_before(
    ctx, selections
) -> None:
    """The old rows_to_records with no match_on and no unique key on the kind
    made a new record per row on every run. The upgrade must not change that
    (it can't see the schema, so it keeps match_on empty: unique key if any,
    else insert)."""
    wf_ctx, record = selections
    ctx.schema_svc.set_unique_keys("sequence_selection", [])
    ctx.commit()
    wf = WorkflowDef.model_validate(
        load_golden_v0("parse-selection-table-to-sequences.yaml")
    )
    for step in wf.steps:
        if step.plugin == "civex.save_records@1":
            assert "match_on" not in step.config
            step.config["field_mapping"] = {"Selection": "selection_number"}
    executor.run(wf, wf_ctx, all_plugins())
    again = executor.run(wf, wf_ctx, all_plugins())
    ctx.commit()
    assert again[-1]["outputs"]["created"] == 3
    found = ctx.record_svc.find(
        "study",
        schema_name="sequence_selection",
        parent_record_id=str(record.id),
        limit=100,
    )
    assert len(found) == 6


def test_the_wav_workflow_runs_from_chosen_files_and_a_second_run_changes_nothing(
    ctx, selections
) -> None:
    wf_ctx, record = selections
    wf = WorkflowDef.model_validate(
        load_golden_v0("upsert-sequences-from-wav-files.yaml")
    )
    (asked,) = [k for k, v in run_inputs(wf).items() if v.type == "files"]
    assert asked == "seq_wav_files"
    refs = [
        ctx.file_svc.store_bytes(name.encode(), name).to_dict()
        for name in ("sel_01_a.wav", "sel_02_b.wav", "other.wav")
    ]
    seed = {"__input__": {asked: refs}}

    first = executor.run(wf, wf_ctx, all_plugins(), initial_outputs=seed)
    ctx.commit()
    out = first[-1]["outputs"]
    assert (out["created"], out["updated"], out["unmatched"]) == (2, 0, ["other.wav"])
    assert _children(ctx, record)[1]["seq_wav_file"]["filename"] == "sel_01_a.wav"

    again = executor.run(wf, wf_ctx, all_plugins(), initial_outputs=seed)
    out = again[-1]["outputs"]
    assert (out["created"], out["updated"], out["unchanged"]) == (0, 0, 2)


def test_a_files_step_with_nothing_chosen_says_so(ctx, selections) -> None:
    wf_ctx, _ = selections
    wf = WorkflowDef.model_validate(
        load_golden_v0("upsert-sequences-from-wav-files.yaml")
    )
    with pytest.raises(Exception, match="No files were chosen"):
        executor.run(wf, wf_ctx, all_plugins())


def test_a_setting_can_take_its_value_from_a_field_of_the_record(
    ctx, make_collection, make_schema, make_record
) -> None:
    dataset = make_collection("study")
    make_schema(
        "doc", fields=[("seed", "float"), ("out", "float"), ("other", "string")]
    )
    record = make_record("study", "doc", {"seed": 2.5, "other": "keep"})
    wf_ctx = WorkflowContext(record=record, dataset=dataset, _app_ctx=ctx)
    wf = WorkflowDef.model_validate(
        yaml.safe_load(
            """
name: t
steps:
  - id: copy
    plugin: civex.set_fields@1
    config: {fields: {out: {from_field: seed}}}
"""
        )
    )
    assert _contract_errors(wf.model_dump(by_alias=True)) == []
    executor.run(wf, wf_ctx, all_plugins())
    ctx.commit()
    data = ctx.record_svc.get(str(record.id)).data
    assert data["out"] == 2.5 and data["other"] == "keep"

    empty = make_record("study", "doc", {})
    with pytest.raises(Exception, match="The field 'seed' is empty"):
        executor.run(
            wf,
            WorkflowContext(record=empty, dataset=dataset, _app_ctx=ctx),
            all_plugins(),
        )


def test_a_from_field_setting_passes_contract_validation_whatever_its_type() -> None:
    raw = yaml.safe_load(
        """
name: t
steps:
  - id: s
    plugin: civex.save_records@1
    config: {schema: {from_field: kind}, match_on: [a]}
    inputs: {files: x.files}
  - id: x
    plugin: civex.files@1
    config: {source: field, field: f}
"""
    )
    assert _contract_errors(raw) == []


def load_golden_v0(name: str) -> dict:
    """A golden version-0 workflow, upgraded in memory the way a load does."""
    return parse_workflow((GOLDEN / "v0" / name).read_text()).model_dump(by_alias=True)


# -- reading a folder ----------------------------------------------------------------


def test_a_folder_is_read_by_the_server_skipping_what_is_stored(
    ctx, selections, tmp_path: Path
) -> None:
    wf_ctx, _ = selections
    folder = tmp_path / "audio"
    (folder / "sub").mkdir(parents=True)
    (folder / "sel_01.wav").write_bytes(b"one")
    (folder / "sel_02.wav").write_bytes(b"two")
    (folder / "notes.txt").write_bytes(b"x")
    (folder / "sub" / "sel_03.wav").write_bytes(b"three")
    (folder / ".hidden.wav").write_bytes(b"h")

    wf = WorkflowDef.model_validate(
        yaml.safe_load(
            f"""
name: t
steps:
  - id: wavs
    plugin: civex.files@1
    config: {{source: folder, folder: {folder}, glob: '*.wav', subfolders: true}}
"""
        )
    )
    first = executor.run(wf, wf_ctx, all_plugins())
    names = sorted(f["filename"] for f in first[0]["outputs"]["files"])
    assert names == ["sel_01.wav", "sel_02.wav", "sel_03.wav"]

    again = wf_ctx.store_folder(str(folder), "*.wav", True)
    assert (again["stored"], again["already_stored"]) == (0, 3)


def test_a_host_that_does_not_read_folders_refuses(
    ctx, selections, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dataclasses

    from civex.domain import features
    from civex.domain.exceptions import FeatureUnavailableError

    wf_ctx, _ = selections
    hosted = dataclasses.replace(
        ctx.project, features=features.LOCAL_FEATURES - {features.SERVER_PATH_IMPORT}
    )
    monkeypatch.setattr(ctx, "project", hosted)
    with pytest.raises(FeatureUnavailableError):
        wf_ctx.store_folder(str(tmp_path))


def test_a_plugin_not_named_for_it_cannot_read_a_folder() -> None:
    from civex.plugins.host_api import granted

    assert "store_folder" not in granted(["read", "manage_files", "write_records"])


# -- review fixes ---------------------------------------------------------------


def test_an_input_name_that_prefixes_another_is_rewired_exactly() -> None:
    up = _upgraded(
        """
name: t
inputs:
  wav: {type: files}
  wav-extra: {type: files}
steps:
  - id: put
    plugin: civex.create_records_from_files
    config: {schema: s, file_field: f}
    inputs: {files: __input__.wav-extra}
"""
    )
    put = next(s for s in up["steps"] if s["id"] == "put")
    assert put["inputs"]["files"] == "wav-extra.files"


def test_an_upgraded_parse_table_keeps_its_comma_default() -> None:
    up = _upgraded(
        "name: t\nsteps:\n  - id: l\n    plugin: civex.load_file\n    config: {field: a}\n"
        "  - id: p\n    plugin: civex.parse_table\n    inputs: {bytes: l.bytes}\n"
    )
    assert up["steps"][0]["config"]["delimiter"] == ","


def test_copying_an_empty_field_still_clears_the_target(
    ctx, make_collection, make_schema, make_record
) -> None:
    dataset = make_collection("study")
    make_schema("doc", fields=[("a", "string"), ("b", "string")])
    record = make_record("study", "doc", {"b": "old"})
    wf_ctx = WorkflowContext(record=record, dataset=dataset, _app_ctx=ctx)
    wf = parse_workflow(
        "name: t\nsteps:\n  - id: g\n    plugin: civex.get_field\n    config: {field: a}\n"
        "  - id: s\n    plugin: civex.save_field\n    config: {field: b}\n"
        "    inputs: {value: g.value}\n"
    )
    executor.run(wf, wf_ctx, all_plugins())
    ctx.commit()
    assert ctx.record_svc.get(str(record.id)).data.get("b") is None


def test_a_from_field_error_names_its_step(
    ctx, make_collection, make_schema, make_record
) -> None:
    dataset = make_collection("study")
    make_schema("doc", fields=[("a", "string"), ("b", "string")])
    record = make_record("study", "doc", {})
    wf_ctx = WorkflowContext(record=record, dataset=dataset, _app_ctx=ctx)
    wf = parse_workflow(
        "name: t\nsteps:\n  - id: s\n    plugin: civex.set_fields@1\n"
        "    config: {fields: {b: {from_field: a}}}\n"
    )
    with pytest.raises(Exception) as e:
        executor.run(wf, wf_ctx, all_plugins())
    assert e.value.envelope.step == "s"  # type: ignore[attr-defined]


def test_what_a_files_step_reads_cannot_come_from_data() -> None:
    raw = yaml.safe_load(
        """
name: t
steps:
  - id: a
    plugin: civex.files@1
    config: {source: folder, folder: {from_field: path}}
  - id: b
    plugin: civex.files@1
    config: {source: run}
    inputs: {provided: a.files}
"""
    )
    errors = _contract_errors(raw)
    assert any("can't take 'folder' from a field" in e for e in errors)
    assert any("filled in by civex" in e for e in errors)


def test_a_non_builtin_plugin_cannot_name_its_way_to_reading_a_folder() -> None:
    from civex.plugins.base import PluginTier
    from civex.plugins.launchers import Launcher
    from civex.plugins.registry import _registration
    from civex_plugin_sdk.protocol import DescribeResult

    class L(Launcher):
        tier = PluginTier.SUBPROCESS
        bounded = True
        key = "x"
        label = "x"

        def start(self, mode, run_dir=None):  # pragma: no cover
            raise NotImplementedError

    described = DescribeResult(
        id="project.sneaky",
        name="s",
        category="x",
        capabilities=["read", "store_folder"],
        config_schema={},
    )
    assert _registration(L(), described).capabilities == ["read"]


def test_a_workflow_that_cannot_be_loaded_is_a_clear_error_not_a_500(ctx) -> None:
    from civex.domain.exceptions import ValidationError

    folder = ctx.workflow_svc._dir
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "later.yaml").write_text(
        "name: later\nsteps:\n  - id: s\n    plugin: civex.table@2\n"
    )
    with pytest.raises(ValidationError, match="needs a newer civex"):
        ctx.workflow_svc.find_by_name("later")
