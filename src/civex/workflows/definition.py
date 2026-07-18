from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class StepDef(BaseModel):
    id: str
    plugin: str
    config: dict = {}
    inputs: dict[str, str] = {}  # input_name → "step_id.output_name"


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


def load_workflow(path: Path) -> WorkflowDef:
    return WorkflowDef.model_validate(yaml.safe_load(path.read_text()))
