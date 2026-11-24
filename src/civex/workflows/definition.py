from __future__ import annotations

import copy
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from civex.workflows import upgrades


class StepDef(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    plugin: str
    config: dict = {}
    inputs: dict[str, str] = {}  # input_name → "step_id.output_name"
    # Wall-clock budget in seconds for this step's plugin run; overrides
    # [plugins].default_timeout_seconds from config.toml when set. Only
    # consulted for subprocess/container-tier plugins.
    timeout: int | None = None
    # Restricted boolean expression (see workflows/conditions.py) gating
    # whether the executor dispatches this step at all. "if" is a Python
    # keyword, hence the alias.
    if_: str | None = Field(default=None, alias="if")


class RecordEventTrigger(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    schema_name: str = Field(alias="schema")
    fields: list[str] | None = (
        None  # record_updated only: trigger only if one of these fields changed
    )


class Triggers(BaseModel):
    record_created: RecordEventTrigger | None = None
    record_updated: RecordEventTrigger | None = None


class WorkflowInput(BaseModel):
    """Declares a named input that can be supplied when running a workflow manually.

    type: "files"  → list of FileRef dicts (resolved from paths/globs by the caller)
          "value"  → arbitrary scalar passed through as-is
    """

    type: str  # "files" | "value"
    label: str | None = None
    description: str | None = None


class WorkflowDef(BaseModel):
    name: str
    description: str | None = None
    # Whether its triggers start runs. Off, it runs only when someone starts
    # it (or tries it): a new workflow is made off, so its first run on real
    # data is one someone chose, after trying it. A file without the key is
    # on, as every workflow was before the key existed.
    enabled: bool = True
    triggers: Triggers | None = None
    record_schema: str | None = (
        None  # schema the anchor record must have; enforced on manual runs
    )
    inputs: dict[str, WorkflowInput] | None = None
    steps: list[StepDef]


def run_inputs(wf: WorkflowDef) -> dict[str, WorkflowInput]:
    """What a person is asked for when starting the workflow: the Files steps
    set to be chosen at run time (named by their step id, whose files they
    become), then any plain `inputs` the workflow declares."""
    asked: dict[str, WorkflowInput] = {}
    for step in wf.steps:
        if upgrades.split_step(step.plugin)[0] != "civex.files":
            continue
        if step.config.get("source", "run") != "run":
            continue
        asked[step.id] = WorkflowInput(
            type="files", label=step.config.get("label") or step.id
        )
    return {**asked, **(wf.inputs or {})}


def trigger_summaries(wf: WorkflowDef) -> list[str]:
    """What starts a workflow by itself, one line per trigger ("record_created
    on sample (site, depth)"): what the list and the library show."""
    out = []
    for event in ("record_created", "record_updated"):
        trigger = getattr(wf.triggers, event, None) if wf.triggers else None
        if trigger is None:
            continue
        text = f"{event} on {trigger.schema_name}"
        if trigger.fields:
            text += f" ({', '.join(trigger.fields)})"
        out.append(text)
    return out


def set_enabled_text(content: str, enabled: bool) -> str:
    """`content` with its top-level `enabled:` set, every other line (and so
    every comment) as it was: the one way a workflow is switched on or off, so
    a hand-written file keeps its layout. The key goes just before `name:` when
    the file has none."""
    value = "true" if enabled else "false"
    lines = content.splitlines(keepends=True)
    key = re.compile(r"^enabled\s*:")
    for i, line in enumerate(lines):
        if key.match(line):
            lines[i] = f"enabled: {value}\n"
            return "".join(lines)
    # Just before `name:`, which every workflow has at the top level: a key
    # put before another top-level key is valid whatever follows `name:`
    # (a folded block, a comment).
    at = next((i for i, line in enumerate(lines) if re.match(r"^name\s*:", line)), 0)
    lines.insert(at, f"enabled: {value}\n")
    return "".join(lines)


def parse_workflow(text: str) -> WorkflowDef:
    """A workflow from its YAML text, upgraded in memory to this civex's steps
    first (`workflows.upgrades`), nothing written. Raises `NeedsNewerCivex` for
    a step version this civex doesn't have, `WorkflowUpgradeError` for an old
    workflow that can't be upgraded by itself."""
    raw = yaml.safe_load(text)
    if isinstance(raw, dict):
        raw = copy.deepcopy(raw)
        upgrades.upgrade_raw(raw)
    return WorkflowDef.model_validate(raw)


def load_workflow(path: Path) -> WorkflowDef:
    """The workflow in a file. A file written for older steps is upgraded and
    rewritten here (its old text kept as `<name>.yaml.bak`): see
    `workflows.upgrades`."""
    raw, _ = upgrades.upgrade_file(path, path.read_text(encoding="utf-8"))
    return WorkflowDef.model_validate(raw)
