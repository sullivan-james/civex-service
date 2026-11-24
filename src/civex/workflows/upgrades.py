"""Step versions and the automatic upgrade of workflow files.

A workflow names a built-in step with its version, `civex.save_records@1`. An
id with no `@` is version 0: the steps civex shipped before steps were
versioned. A version's *contract* is its id, its config keys and its
inputs/outputs; labels, descriptions and the code behind it may change freely.
When a contract changes, the step gets a new version and an upgrade function
(registered here with `@upgrade`) that rewrites a workflow using the old one,
possibly into different steps (several old steps may merge into one, the steps
after them are rewired).

Upgrades work on the workflow's raw YAML dict, before it is validated, and
touch nothing else: no database, no plugins. `load_workflow` runs them when it
reads a file and rewrites the file (the old text is kept next to it as
`<name>.yaml.bak`); a workflow pasted, shared or saved by an AI is upgraded the
same way before it is checked.

A workflow naming a version this civex doesn't know (a file synced from a
computer with a newer civex) is refused with `NeedsNewerCivex`: guessing what
it means could write the wrong data.

To change a step's contract: add the new version's plugin (`id = "civex.x@2"`),
bump `LATEST["civex.x"]`, and register `@upgrade("civex.x", 1)`. The
golden tests (`tests/workflows/test_step_upgrades.py`) hold each version's
example workflows.
"""

from __future__ import annotations

import copy
import logging
import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

#: The newest version of every built-in step this civex has.
LATEST: dict[str, int] = {
    "civex.files": 1,
    "civex.table": 1,
    "civex.value_from_filename": 1,
    "civex.save_records": 1,
    "civex.set_fields": 1,
}

INPUT_STEP = "__input__"


class WorkflowUpgradeError(ValueError):
    """A workflow that can't be upgraded by itself; the file is left as it was."""


class NeedsNewerCivex(ValueError):
    """A workflow that names a step version this civex doesn't have."""


def split_step(plugin: str) -> tuple[str, int]:
    """(`civex.save_records`, 1) for `civex.save_records@1`; version 0 when
    the id carries none (or its version isn't a number: not a built-in's)."""
    base, sep, version = plugin.partition("@")
    if sep and version.isdigit():
        return base, int(version)
    return plugin, 0


def step_id_for(base: str, version: int) -> str:
    return f"{base}@{version}"


def check_versions(raw: dict[str, Any]) -> None:
    """Raises `NeedsNewerCivex` if a step names a version beyond this civex's."""
    for step in _steps(raw):
        plugin = step.get("plugin")
        if not isinstance(plugin, str):
            continue
        base, version = split_step(plugin)
        newest = LATEST.get(base)
        if newest is not None and version > newest:
            raise NeedsNewerCivex(
                f"This workflow uses '{plugin}' in step '{step.get('id')}', "
                f"a newer version of that step than this civex knows "
                f"(it has {base}@{newest}). It needs a newer civex: update civex "
                "on this computer, or open the workflow on the computer it came from."
            )


# --- the raw workflow ------------------------------------------------------


def _steps(raw: dict[str, Any]) -> list[dict[str, Any]]:
    steps = raw.get("steps") if isinstance(raw, dict) else None
    return [s for s in steps if isinstance(s, dict)] if isinstance(steps, list) else []


def _ids(raw: dict[str, Any]) -> set[str]:
    return {str(s.get("id")) for s in _steps(raw)}


def _ref_pattern(step_id: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w.-])" + re.escape(step_id) + r"\.(\w+)")


def _referrers(raw: dict[str, Any], step_id: str) -> list[str]:
    """The ids of steps whose `inputs` or `if` refer to `step_id`'s outputs."""
    pat = _ref_pattern(step_id)
    found: list[str] = []
    for step in _steps(raw):
        if step.get("id") == step_id:
            continue
        inputs = step.get("inputs") or {}
        refs = [v for v in inputs.values() if isinstance(v, str)]
        cond = step.get("if")
        if isinstance(cond, str):
            refs.append(cond)
        if any(pat.search(r) for r in refs):
            found.append(str(step.get("id")))
    return found


def _retarget(raw: dict[str, Any], old: str, new_step: str, new_output: str) -> None:
    """Every reference to `old` (a name like `__input__.files`) becomes
    `new_step.new_output`, in inputs and `if`."""
    pat = re.compile(r"(?<![\w.-])" + re.escape(old) + r"(?![\w.-])")
    target = f"{new_step}.{new_output}"
    for step in _steps(raw):
        inputs = step.get("inputs")
        if isinstance(inputs, dict):
            for k, v in list(inputs.items()):
                if isinstance(v, str):
                    inputs[k] = pat.sub(target, v)
        if isinstance(step.get("if"), str):
            step["if"] = pat.sub(target, step["if"])


def _fresh_id(raw: dict[str, Any], wanted: str) -> str:
    taken = _ids(raw)
    candidate, n = wanted, 1
    while candidate in taken:
        n += 1
        candidate = f"{wanted}-{n}" if n > 2 else f"{wanted}-files"
    return candidate


def _drop_empty(config: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in config.items() if v not in (None, "", [], {})}


def _source_step(raw: dict[str, Any], step: dict[str, Any], input_name: str):
    """The step feeding `step`'s `input_name`, and the output used."""
    ref = (step.get("inputs") or {}).get(input_name)
    if not isinstance(ref, str) or "." not in ref:
        return None, None
    source_id, _, output = ref.partition(".")
    for candidate in _steps(raw):
        if candidate.get("id") == source_id:
            return candidate, output
    return None, None


# --- the registry ----------------------------------------------------------

#: An upgrade changes the workflow so that `step` no longer names the old
#: version, and returns what it did in a sentence. Returning None means "not
#: yet": it depends on another step being upgraded first, and is tried again.
Upgrade = Callable[[dict[str, Any], dict[str, Any]], "str | None"]

UPGRADES: dict[tuple[str, int], Upgrade] = {}


def upgrade(base: str, from_version: int) -> Callable[[Upgrade], Upgrade]:
    def register(fn: Upgrade) -> Upgrade:
        UPGRADES[(base, from_version)] = fn
        return fn

    return register


def _replace(step: dict[str, Any], plugin: str, config: dict[str, Any]) -> None:
    """Make `step` the new step in place, keeping its id, order of keys, `if`
    and `timeout`."""
    step["plugin"] = plugin
    if config:
        step["config"] = config
    else:
        step.pop("config", None)


def _remove(raw: dict[str, Any], step: dict[str, Any]) -> None:
    raw["steps"] = [s for s in raw["steps"] if s is not step]


@upgrade("civex.load_file", 0)
def _load_file(raw: dict[str, Any], step: dict[str, Any]) -> str | None:
    if _referrers(raw, str(step["id"])):
        return None  # its reader (Read a table) goes first and takes it away
    _remove(raw, step)
    return f"removed step '{step['id']}' (Read a file), which nothing used"


@upgrade("civex.parse_table", 0)
def _parse_table(raw: dict[str, Any], step: dict[str, Any]) -> str | None:
    source, output = _source_step(raw, step, "bytes")
    if source is None or split_step(str(source.get("plugin")))[0] != "civex.load_file":
        raise WorkflowUpgradeError(
            f"Step '{step['id']}' (civex.parse_table) reads its bytes from "
            f"something other than a file field. The Table step reads a table "
            "from a file field or a Files step: please edit this workflow by hand."
        )
    if split_step(str(source.get("plugin")))[1] != 0:
        return None
    if output != "bytes":
        raise WorkflowUpgradeError(
            f"Step '{step['id']}' reads '{output}' of '{source['id']}', which "
            "the Table step has no equivalent for."
        )
    others = [r for r in _referrers(raw, str(source["id"])) if r != step["id"]]
    if others:
        raise WorkflowUpgradeError(
            f"Step '{source['id']}' (civex.load_file) is also used by "
            f"{', '.join(repr(o) for o in others)}; the Table step reads the file "
            "itself, so that can't be rewired by itself. Please edit this "
            "workflow by hand."
        )
    if source.get("if") and source.get("if") != step.get("if"):
        if step.get("if"):
            raise WorkflowUpgradeError(
                f"Steps '{source['id']}' and '{step['id']}' both have an 'if'; "
                "they can't be merged by themselves."
            )
        step["if"] = source["if"]
    if source.get("timeout") and not step.get("timeout"):
        step["timeout"] = source["timeout"]
    config = copy.deepcopy(step.get("config") or {})
    config["field"] = (source.get("config") or {}).get("field")
    if "delimiter" not in config and "delimiters" not in config:
        config["delimiter"] = ","  # the old step's default; Table now auto-detects
    step.pop("inputs", None)
    _replace(step, step_id_for("civex.table", 1), _drop_empty(config))
    _remove(raw, source)
    return (
        f"merged '{source['id']}' (Read a file) and '{step['id']}' (Read a table "
        "from a file) into one Table step"
    )


@upgrade("civex.load_file_list", 0)
def _load_file_list(raw: dict[str, Any], step: dict[str, Any]) -> str | None:
    field = (step.get("config") or {}).get("field")
    _replace(
        step,
        step_id_for("civex.files", 1),
        _drop_empty({"source": "field", "field": field}),
    )
    return f"'{step['id']}' is now a Files step reading the files in '{field}'"


def _rename_inputs(step: dict[str, Any], renames: dict[str, str]) -> None:
    inputs = step.get("inputs")
    if isinstance(inputs, dict):
        step["inputs"] = {renames.get(k, k): v for k, v in inputs.items()}


@upgrade("civex.rows_to_records", 0)
def _rows_to_records(raw: dict[str, Any], step: dict[str, Any]) -> str | None:
    old = copy.deepcopy(step.get("config") or {})
    new: dict[str, Any] = {"schema": old.pop("schema", None)}
    new["if_exists"] = "update"
    if old.get("match_on"):
        new["match_on"] = old.pop("match_on")
    old.pop("match_on", None)
    if old.get("context_record_id"):
        new["parent_record_id"] = old.pop("context_record_id")
    old.pop("context_record_id", None)
    new.update(_drop_empty(old))
    _rename_inputs(step, {"table": "rows"})
    _replace(step, step_id_for("civex.save_records", 1), new)
    return f"'{step['id']}' is now a Save as records step"


@upgrade("civex.upsert_records", 0)
def _upsert_records(raw: dict[str, Any], step: dict[str, Any]) -> str | None:
    old = copy.deepcopy(step.get("config") or {})
    new: dict[str, Any] = {"schema": old.pop("schema", None)}
    new["if_exists"] = "update"
    key = old.pop("key_field", None)
    if key:
        new["match_on"] = [key]
    new.update(_drop_empty(old))
    _rename_inputs(step, {"table": "rows"})
    _replace(step, step_id_for("civex.save_records", 1), new)
    return f"'{step['id']}' is now a Save as records step"


@upgrade("civex.create_records_from_files", 0)
def _create_records_from_files(raw: dict[str, Any], step: dict[str, Any]) -> str | None:
    old = copy.deepcopy(step.get("config") or {})
    new: dict[str, Any] = {"schema": old.pop("schema", None), "if_exists": "add_new"}
    if old.get("context_record_id"):
        new["parent_record_id"] = old.pop("context_record_id")
    old.pop("context_record_id", None)
    new.update(_drop_empty(old))
    _replace(step, step_id_for("civex.save_records", 1), new)
    return f"'{step['id']}' is now a Save as records step"


@upgrade("civex.match_files_to_records", 0)
def _match_files_to_records(raw: dict[str, Any], step: dict[str, Any]) -> str | None:
    old = copy.deepcopy(step.get("config") or {})
    new: dict[str, Any] = {"schema": old.pop("schema", None), "if_exists": "update"}
    key = old.pop("key_field", None)
    if key:
        new["match_on"] = [key]
    pattern = old.pop("pattern", None)
    if pattern:
        new["filename_pattern"] = pattern
    new.update(_drop_empty(old))
    _replace(step, step_id_for("civex.save_records", 1), new)
    return f"'{step['id']}' is now a Save as records step"


@upgrade("civex.extract_from_filename", 0)
def _extract_from_filename(raw: dict[str, Any], step: dict[str, Any]) -> str | None:
    _replace(
        step,
        step_id_for("civex.value_from_filename", 1),
        copy.deepcopy(step.get("config") or {}),
    )
    return f"'{step['id']}' is now a Value from the file name step"


@upgrade("civex.save_field", 0)
def _save_field(raw: dict[str, Any], step: dict[str, Any]) -> str | None:
    config = step.get("config") or {}
    field = config.get("field")
    source, output = _source_step(raw, step, "value")
    new: dict[str, Any] = {}
    if source is not None and split_step(str(source.get("plugin"))) == (
        "civex.get_field",
        0,
    ):
        if source.get("if"):
            raise WorkflowUpgradeError(
                f"Step '{source['id']}' (civex.get_field) has an 'if'; it can't "
                "be turned into a copy of a field by itself. Please edit this "
                "workflow by hand."
            )
        # An empty source cleared the target before: keep that.
        new["fields"] = {
            field: {
                "from_field": (source.get("config") or {}).get("field"),
                "if_empty": "clear",
            }
        }
        step.pop("inputs", None)
    else:
        new["field"] = field
    _replace(step, step_id_for("civex.set_fields", 1), new)
    return f"'{step['id']}' is now a Set fields on this record step"


@upgrade("civex.save_fields", 0)
def _save_fields(raw: dict[str, Any], step: dict[str, Any]) -> str | None:
    _replace(step, step_id_for("civex.set_fields", 1), {})
    return f"'{step['id']}' is now a Set fields on this record step"


@upgrade("civex.get_field", 0)
def _get_field(raw: dict[str, Any], step: dict[str, Any]) -> str | None:
    users = _referrers(raw, str(step["id"]))
    if users:
        return None  # a Save field that used it goes first; anything else is stuck
    _remove(raw, step)
    return (
        f"removed step '{step['id']}' (Read a field): any setting can now take "
        "a value from this record's field"
    )


def _inputs_to_steps(raw: dict[str, Any]) -> list[str]:
    """Workflow `inputs` of type `files` become Files steps picked at run time."""
    inputs = raw.get("inputs")
    if not isinstance(inputs, dict):
        return []
    notes: list[str] = []
    for name in list(inputs):
        decl = inputs[name] or {}
        if not isinstance(decl, dict) or decl.get("type") != "files":
            continue
        step_id = _fresh_id(raw, str(name))
        config: dict[str, Any] = {"source": "run"}
        label = decl.get("label") or decl.get("description")
        if label:
            config["label"] = label
        step = {
            "id": step_id,
            "plugin": step_id_for("civex.files", 1),
            "config": config,
        }
        raw["steps"] = [step, *raw.get("steps", [])]
        _retarget(raw, f"{INPUT_STEP}.{name}", step_id, "files")
        del inputs[name]
        notes.append(
            f"the run-time input '{name}' is now the Files step '{step_id}' "
            "(files chosen when the workflow is run)"
        )
    if not inputs:
        raw.pop("inputs", None)
    return notes


def upgrade_raw(raw: Any) -> list[str]:
    """Upgrade `raw` (a workflow as loaded from YAML) in place to the newest
    version of every step; returns what changed, one sentence each (empty:
    nothing to do). Raises `NeedsNewerCivex`, or `WorkflowUpgradeError` with
    `raw` possibly half-changed (callers work on a copy)."""
    if not isinstance(raw, dict):
        return []
    check_versions(raw)
    notes: list[str] = []
    if isinstance(raw.get("steps"), list):
        notes.extend(_inputs_to_steps(raw))
        for _ in range(10_000):
            progressed = False
            stuck: list[dict[str, Any]] = []
            for step in list(_steps(raw)):
                plugin = step.get("plugin")
                if not isinstance(plugin, str):
                    continue
                base, version = split_step(plugin)
                fn = UPGRADES.get((base, version))
                if fn is None:
                    continue
                note = fn(raw, step)
                if note is None:
                    stuck.append(step)
                    continue
                notes.append(note)
                progressed = True
                break  # the step list may have changed: look again
            if not progressed:
                if stuck:
                    names = ", ".join(f"'{s['id']}' ({s['plugin']})" for s in stuck)
                    raise WorkflowUpgradeError(
                        f"Can't upgrade {names} by itself: another step uses "
                        "its result in a way the new steps can't take over. "
                        "Please edit this workflow by hand."
                    )
                break
    return notes


# --- text and files --------------------------------------------------------


class _Dumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False):
        return super().increase_indent(flow, False)  # list items indented


def _str(dumper: yaml.SafeDumper, value: str):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _str)


def dump(raw: dict[str, Any]) -> str:
    """A workflow as YAML text: keys in the order they have, the same text for
    the same workflow on every computer."""
    return yaml.dump(
        raw,
        Dumper=_Dumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=1000,
    )


def upgrade_text(text: str) -> tuple[str, list[str]]:
    """`text` upgraded: (the new text, what changed). The text itself, as it
    was written, when nothing needed upgrading. Raises `NeedsNewerCivex` or
    `WorkflowUpgradeError` (ValueError for text that isn't YAML at all is left
    to the caller's own parsing)."""
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        return text, []
    work = copy.deepcopy(raw)
    notes = upgrade_raw(work)
    if not notes:
        return text, []
    return dump(work), notes


def _backup_path(path: Path) -> Path:
    first = path.with_name(path.name + ".bak")
    if not first.exists():
        return first
    n = 2
    while True:
        candidate = path.with_name(f"{path.name}.bak{n}")
        if not candidate.exists():
            return candidate
        n += 1


def upgrade_file(path: Path, text: str) -> tuple[Any, list[str]]:
    """The workflow in the file at `path` (whose text is `text`), upgraded:
    (the workflow as a dict, what changed). When something changed the old
    text is kept beside the file (`<name>.yaml.bak`, never overwritten, a name
    the workflow list, bundles and sync don't pick up), the new text replaces
    the file atomically, and what changed is logged. A folder that can't be
    written leaves the file as it is and the upgraded workflow is used in
    memory only. A file with nothing to upgrade is not touched."""
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        return raw, []
    work = copy.deepcopy(raw)
    notes = upgrade_raw(work)
    if not notes:
        return raw, []
    try:
        backup = _backup_path(path)
        backup.write_text(text, encoding="utf-8")
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=path.name,
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(dump(work))
            temp = Path(handle.name)
        os.replace(temp, path)
        log.warning(
            "Upgraded workflow %s to this civex's steps (the old file is kept as %s): %s",
            path.name,
            backup.name,
            "; ".join(notes),
        )
    except OSError as e:
        log.warning(
            "Upgraded workflow %s in memory only (could not write it: %s): %s",
            path.name,
            e,
            "; ".join(notes),
        )
    return work, notes
