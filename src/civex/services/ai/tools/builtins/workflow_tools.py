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
        # unchanged rather than re-encoding them. The built-in plugin
        # reference table is generated per call from the live registry
        # (CIVEX-144) rather than baked into the static template below, so
        # the AI can never be handed a stale signature for a plugin that
        # changed -- it's the same describe-derived contract list_plugins
        # and every other surface reads.
        reference = _format_builtin_reference(ctx.plugin_svc.list_registered())
        return WORKFLOW_AUTHORING_GUIDE.replace(
            "{{BUILTIN_PLUGIN_REFERENCE}}", reference
        )


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


def _format_builtin_reference(registered: list[dict]) -> str:
    """One line per built-in plugin: id, config keys (with a trailing `?` on
    any key that has a default, i.e. isn't in the schema's `required` list),
    and declared input/output names -- generated from
    PluginService.list_registered() rather than hand-maintained, so this
    table can't silently drift from what a plugin's Config/inputs/outputs
    actually are the way the old hardcoded version could (CIVEX-144). Prose
    detail that isn't part of any plugin's declared contract (date_format
    token syntax, the loop-prevention rules, ...) stays hand-written below in
    ## Critical gotchas -- there's no other source of truth for those."""
    builtins = [p for p in registered if p["builtin"]]
    id_width = max((len(p["id"]) for p in builtins), default=0)
    lines = []
    for p in builtins:
        schema = p["config_schema"]
        required = set(schema.get("required") or [])
        config_keys = list((schema.get("properties") or {}).keys())
        segments = [p["id"].ljust(id_width)]
        if config_keys:
            rendered = [k if k in required else f"{k}?" for k in config_keys]
            segments.append("config: {" + ", ".join(rendered) + "}")
        if p["inputs"]:
            segments.append("inputs: " + ", ".join(s["name"] for s in p["inputs"]))
        if p["outputs"]:
            segments.append("outputs: " + ", ".join(s["name"] for s in p["outputs"]))
        lines.append("  ".join(segments))
    return "\n".join(lines)


# Returned by GetWorkflowAuthoringGuideTool rather than inlined in the system
# prompt on every request — it's only relevant when the model is actually
# about to draft a workflow or plugin, which is a minority of turns. The
# {{BUILTIN_PLUGIN_REFERENCE}} placeholder is filled in per call by
# _format_builtin_reference() (CIVEX-144); everything else here is static
# process/format documentation with no other source of truth to read from.
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
{{BUILTIN_PLUGIN_REFERENCE}}

Notes not captured in the table above:
  civex.extract_from_filename: output_type is "string"|"date"|"datetime"|"integer"|"float".
    date_format tokens: YYYY MM DD HH mm SS (NOT strftime — do not use %Y etc.).
    pattern is a Python regex; non-token chars are literal so [-_] matches separator alternatives.
  civex.parse_table / civex.upsert_records / civex.rows_to_records: `table` is a pandas DataFrame.

## Custom plugin format
File: _civex/plugins/{name}.py — a real OS-process script (Tier 1, uv-managed subprocess),
NOT imported into civex-service's own process. Must:
  1. Start with a PEP 723 inline metadata block declaring `civex-plugin-sdk` as a dependency
     (uv resolves/caches an isolated venv for it automatically — no pyproject.toml edits, ever).
  2. Define a class named exactly `Plugin` (subclassing the SDK's own `Plugin` ABC, imported
     under an alias to avoid the name collision).
  3. Declare every `ctx.*` RPC method it calls in `capabilities` — undeclared calls are refused
     at run time with a capability_denied error, even if the method exists on Ctx.
  4. Call `serve(Plugin)` under an `if __name__ == "__main__":` guard.

```python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["civex-plugin-sdk"]
# ///
from pydantic import BaseModel
from civex_plugin_sdk import Ctx, Plugin as PluginBase, serve

class Plugin(PluginBase):
    id = "project.my_plugin"   # convention: project.{name}
    name = "Human readable name"
    category = "general"
    capabilities = ["update_record"]   # every ctx.* call this plugin makes, by name

    class Config(BaseModel):
        my_param: str          # Pydantic model; all config comes through this

    def invoke(self, inputs: dict, config: Config, ctx: Ctx) -> dict:
        # ctx.get_context_record() → dict   — the trigger record (id, schema_id, data, ...)
        # ctx.get_context_dataset() → dict  — Ctx has NO ambient .record/.dataset like the
        #                                      old in-process contract; these are the only
        #                                      way to learn what triggered the workflow.
        # ctx.get_file(sha256) → bytes
        # ctx.update_record(record_id, data)  — writes any record by id, not just the trigger
        # ctx.create_record(dataset_name, schema_name, data, context_record_id=None) → dict
        #   (context_record_id defaults to the trigger record when omitted)
        return {"output_name": value}

if __name__ == "__main__":
    serve(Plugin)
```

Each `uv run` invocation is a fresh, sandboxed subprocess: its own process group (killed as a
unit if it exceeds its timeout — default 60s from [plugins].default_timeout_seconds in
config.toml, or override per-step with `timeout: <seconds>` on the workflow step), a scratch
cwd with no ambient path into the real project, and a minimal environment — it can only reach
project data through the declared `ctx.*` capability calls, nothing else.

## Critical gotchas
1. Step IDs must be unique within a workflow. Use descriptive kebab-case, not "step1".
2. Input references: step_id.output_name (dot notation, no wrapping object).
3. record_updated fires on record creation too, but only for fields explicitly set to a non-null value.
   A trigger with fields: [my_field] will NOT fire on create if my_field was left null.
4. date_format in extract_from_filename uses YYYY MM DD tokens — NOT strftime (%Y %m %d).
5. Typical table pipeline (CSV, TSV, ...): load_file → parse_table → (optional transform) → upsert_records or rows_to_records.
6. match_files_to_records config.pattern is a Python regex applied to the filename to extract the key.
7. dataset="" in plugin config means "use the trigger record's collection" — leave empty unless targeting a different one.
8. Custom plugins are auto-discovered on workflow run — no registration needed after saving.
9. A custom plugin's `capabilities` list must name every `ctx.*` method it calls (by method
   name, e.g. "find_records", not the literal string "call_tool") — an omitted one fails at
   run time with capability_denied, not at save time.

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
