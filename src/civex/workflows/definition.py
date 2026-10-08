from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


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
    triggers: Triggers | None = None
    record_schema: str | None = (
        None  # schema the anchor record must have; enforced on manual runs
    )
    inputs: dict[str, WorkflowInput] | None = None
    steps: list[StepDef]


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


def load_workflow(path: Path) -> WorkflowDef:
    return WorkflowDef.model_validate(yaml.safe_load(path.read_text()))
