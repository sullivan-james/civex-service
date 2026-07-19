"""Workflow/plugin authoring tools: list_workflows/list_plugins read full
source text via WorkflowService.list_raw()/PluginService.list_raw();
save_workflow/save_plugin validate via WorkflowService.validate()/
PluginService.validate() (no filesystem write -- these tools only ever
propose, the real write happens through the router once the user approves)."""

from __future__ import annotations

from typing import Any

from civex.domain.exceptions import ValidationError
from civex.services.ai.tools.base import AiTool, AiToolContext


class ListWorkflowsTool(AiTool):
    name = "list_workflows"
    description = (
        "Read all workflow YAML files in the project. "
        "REQUIRED: call this before answering any question that mentions a workflow by name, "
        "asks what a workflow does, or asks about fields/steps related to a workflow. "
        "Never answer from memory — always read the actual files."
    )
    input_schema = {"type": "object", "properties": {}}

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        return ctx.workflow_svc.list_raw()


class ListPluginsTool(AiTool):
    name = "list_plugins"
    description = (
        "List every available plugin (built-ins and custom). 'registered' covers all of them with "
        "structured metadata -- id, category, and config_schema (the plugin's Config fields as JSON "
        "schema) -- useful for picking the right plugin and its config keys without guessing. "
        "'custom_source' has the full Python source of custom plugin files in _civex/plugins/, for "
        "reading or editing existing custom plugin code."
    )
    input_schema = {"type": "object", "properties": {}}

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        return {
            "registered": ctx.plugin_svc.list_registered(),
            "custom_source": ctx.plugin_svc.list_raw(),
        }


class GetWorkflowAuthoringGuideTool(AiTool):
    name = "get_workflow_authoring_guide"
    description = (
        "Returns the workflow YAML format spec, the complete built-in plugin reference, the custom "
        "plugin Python template, and the loop-prevention rules. REQUIRED: call this once before your "
        "first save_workflow or save_plugin call in a conversation — do not guess the YAML format or "
        "plugin signatures from memory. No need to call it again later in the same conversation."
    )
    input_schema = {"type": "object", "properties": {}}

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        # Raw markdown, not JSON -- registry.dispatch() passes strings through
        # unchanged rather than re-encoding them.
        return WORKFLOW_AUTHORING_GUIDE


class SaveWorkflowTool(AiTool):
    name = "save_workflow"
    description = (
        "Validate a workflow YAML and propose it for saving. "
        "The user will see a confirmation UI in the browser and must click 'Save' — no file is written until they do. "
        "Call this after generating and displaying the YAML. The user does not need to say 'save' first."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "stem": {
                "type": "string",
                "description": "Filename stem (letters, numbers, hyphens, underscores only). Example: 'parse-audio-dates'",
            },
            "content": {
                "type": "string",
                "description": "Complete workflow YAML content",
            },
        },
        "required": ["stem", "content"],
    }

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        stem = tool_input["stem"]
        content = tool_input["content"]
        try:
            ctx.workflow_svc.validate(stem, content)
        except ValidationError as e:
            return {"status": "error", "message": str(e)}
        return {"status": "proposed", "stem": stem, "content": content}


class SavePluginTool(AiTool):
    name = "save_plugin"
    description = (
        "Validate a plugin Python file and propose it for saving. "
        "The user will see a confirmation UI in the browser and must click 'Save' — no file is written until they do. "
        "Call this after generating and displaying the code. The user does not need to say 'save' first."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Plugin module name (lowercase letters, digits, underscores only). Example: 'fetch_metadata'",
            },
            "code": {
                "type": "string",
                "description": "Complete Python source code for the plugin",
            },
        },
        "required": ["name", "code"],
    }

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        name = tool_input["name"]
        code = tool_input["code"]
        try:
            ctx.plugin_svc.validate(name, code)
        except ValidationError as e:
            return {"status": "error", "message": str(e)}
        return {"status": "proposed", "name": name, "code": code}


# Returned by GetWorkflowAuthoringGuideTool rather than inlined in the system
# prompt on every request — it's only relevant when the model is actually
# about to draft a workflow or plugin, which is a minority of turns. Static
# (no ctx/schema data), so it's defined once at import time.
WORKFLOW_AUTHORING_GUIDE = """## Workflow YAML format
```
name: string
description: string | null
record_schema: string | null   # required for auto-triggers; restricts manual runs to this schema
triggers:
  record_created:
    schema: SchemaName
    fields: [field1]           # omit to trigger on any field
  record_updated:
    schema: SchemaName
    fields: [field1]
inputs:                        # for manual runs only
  input_name:
    type: files | value
    label: "Display label"
steps:
  - id: unique-kebab-id        # must be unique; referenced as id.output_name
    plugin: civex.plugin_id
    config:
      key: value
    inputs:
      param_name: other_step.output_name
```

## Built-in plugins (complete reference)
civex.get_field              config: {field}                           outputs: value
civex.save_field             config: {field}                           inputs:  value
civex.save_fields                                                      inputs:  updates (dict field→value)
civex.load_file              config: {field}                           outputs: bytes, filename, sha256
civex.load_file_list         config: {field}                           outputs: files (list of FileRef dicts)
civex.extract_from_filename  config: {field, pattern, output_type, date_format?}  outputs: value, filename, extracted
  output_type: "string"|"date"|"datetime"|"integer"|"float"
  date_format tokens: YYYY MM DD HH mm SS  (NOT strftime — do not use %Y etc.)
  pattern: Python regex; non-token chars are literal so [-_] matches separator alternatives
civex.create_records_from_files  config: {schema, file_field, dataset?}  inputs: files  outputs: created, skipped
civex.match_files_to_records     config: {schema, key_field, file_field, pattern, dataset?}  inputs: files  outputs: created, updated, unmatched
civex.upsert_records         config: {schema, key_field, dataset?}    inputs: table (DataFrame)  outputs: created, updated
civex.rows_to_records        config: {schema, dataset?, field_mapping?}  inputs: table (DataFrame)  outputs: created
civex.load_csv               config: {delimiter?, encoding?}           inputs: bytes  outputs: table (DataFrame)

## Custom plugin format
File: _civex/plugins/{name}.py — must define a class named Plugin subclassing BasePlugin.

```python
from pydantic import BaseModel
from civex.plugins.base import BasePlugin, WorkflowContext

class Plugin(BasePlugin):
    id = "project.my_plugin"   # convention: project.{name}
    name = "Human readable name"
    category = "general"

    class Config(BaseModel):
        my_param: str          # Pydantic model; all config comes through this

    def run(self, inputs: dict, config: Config, ctx: WorkflowContext) -> dict:
        # ctx.record           — RecordDTO (.id, .schema_name, .data dict)
        # ctx.dataset          — DatasetDTO (.id, .name)
        # ctx.get_file(sha256) → bytes
        # ctx.update_record({field: value})  — updates the trigger record
        # ctx.create_record(dataset, schema, data, parent_record_id?) → RecordDTO
        return {"output_name": value}
```

## Critical gotchas
1. Step IDs must be unique within a workflow. Use descriptive kebab-case, not "step1".
2. Input references: step_id.output_name (dot notation, no wrapping object).
3. record_updated fires on record creation too, but only for fields explicitly set to a non-null value.
   A trigger with fields: [my_field] will NOT fire on create if my_field was left null.
4. date_format in extract_from_filename uses YYYY MM DD tokens — NOT strftime (%Y %m %d).
5. Typical CSV pipeline: load_file → load_csv → (optional transform) → upsert_records or rows_to_records.
6. match_files_to_records config.pattern is a Python regex applied to the filename to extract the key.
7. dataset="" in plugin config means "use the trigger record's collection" — leave empty unless targeting a different one.
8. Custom plugins are auto-discovered on workflow run — no registration needed after saving.

## CIRCULAR LOOP PREVENTION — MANDATORY

Any workflow that uses save_field, save_fields, or any plugin that updates a record on the SAME schema
as its own trigger WILL cause an infinite loop UNLESS the record_updated trigger is field-restricted.

RULE: Whenever you generate a workflow that both:
  (a) triggers on record_updated (or record_created + record_updated), AND
  (b) writes back to the trigger record (via save_field, save_fields, update_record, or any plugin that mutates the record)

You MUST add `fields: [<input_field_name>]` to the record_updated trigger so it only fires when the
INPUT field changes — never when the OUTPUT field is written.

CORRECT (safe — loop-proof):
  triggers:
    record_updated:
      schema: MySchema
      fields: [input_field]   ← fires only when input_field changes
  steps:
    - id: compute
      ...
    - id: save-result
      plugin: civex.save_field
      config:
        field: output_field   ← writing output_field does NOT re-trigger because it's not in fields

WRONG (causes infinite loop — never generate this):
  triggers:
    record_updated:
      schema: MySchema
      # no fields filter — fires on ANY field change, including output_field writes

The runtime enforces a hard depth limit (MAX_JOB_DEPTH=10) that cuts runaway chains with a warning,
but that is a last-resort safety net — correct field scoping is the right solution.
Always apply the fields filter when a workflow writes back to its own trigger schema."""
