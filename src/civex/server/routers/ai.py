from __future__ import annotations

import ast
import json
import re
from typing import Annotated, Any, Literal, Union

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from fastapi import HTTPException

from civex.config import AIConfig, load_config, save_config
from civex.context import build_local_context
from civex.domain.exceptions import ConfigError, NotFoundError
from civex.services.schema_service import VALID_DTYPES, VALID_RESTRICTION_KEYS

router = APIRouter(prefix="/ai", tags=["ai"])

MAX_TOOL_ROUNDS = 10
_SAFE_PLUGIN_NAME = re.compile(r"^[a-z][a-z0-9_]*$")

# Ollama's default context window (2048-4096 tokens depending on version/model) is
# easily blown past by system prompt (~2-3k tokens with real schemas) + a single
# large tool result (get_workflow_authoring_guide alone is ~1.4k tokens) + the
# actual conversation. Ollama silently truncates from the front rather than
# erroring, which can drop the task or instructions right as the model needs them
# most -- producing a blank/degenerate reply instead of a visible failure. Request
# a larger window explicitly rather than relying on the per-install default.
OLLAMA_NUM_CTX = 8192


def _is_ollama(ai_cfg) -> bool:
    return (
        ai_cfg is not None
        and ai_cfg.provider == "openai-compat"
        and ":11434" in (ai_cfg.base_url or "")
    )


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class UserMessage(BaseModel):
    role: Literal["user"] = "user"
    content: str


class AssistantMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class ToolCallMessage(BaseModel):
    """A tool call + its result, as originally exchanged with the model.

    The frontend keeps this alongside plain text turns in conversation history
    and resends it verbatim on every later request, so a tool call made (and
    its result received) in an earlier turn is not lost across separate HTTP
    requests -- see _iter_turns()/_history_to_anthropic()/_history_to_openai().
    """

    role: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    input: dict[str, Any]
    result: str


ChatMessage = Annotated[
    Union[UserMessage, AssistantMessage, ToolCallMessage],
    Field(discriminator="role"),
]


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


# ---------------------------------------------------------------------------
# Canonical history -> provider-native multi-turn tool format.
#
# Anthropic and OpenAI each represent "assistant said X and called tools Y, Z"
# differently (content blocks vs. a tool_calls field + separate tool-role
# messages), and both require the assistant's tool calls and the matching
# tool results to be paired in adjacent messages. _iter_turns() groups a run
# of ToolCallMessages together with any AssistantMessage text that preceded
# them in the same original model turn; each provider adapter below then
# renders that group into its own native shape.
# ---------------------------------------------------------------------------


def _iter_turns(history: list):
    """Yield ("user", text) or ("assistant", text, tool_calls) tuples."""
    i, n = 0, len(history)
    while i < n:
        msg = history[i]
        if msg.role == "user":
            yield ("user", msg.content)
            i += 1
            continue

        text = ""
        if msg.role == "assistant":
            text = msg.content
            i += 1
        tool_calls = []
        while i < n and history[i].role == "tool_call":
            tool_calls.append(history[i])
            i += 1
        yield ("assistant", text, tool_calls)


def _history_to_anthropic(history: list) -> list[dict]:
    api_msgs: list[dict] = []
    for turn in _iter_turns(history):
        if turn[0] == "user":
            api_msgs.append({"role": "user", "content": turn[1]})
            continue
        _, text, tool_calls = turn
        if not tool_calls:
            if text:
                api_msgs.append({"role": "assistant", "content": text})
            continue
        content: list[dict] = []
        if text:
            content.append({"type": "text", "text": text})
        for tc in tool_calls:
            content.append(
                {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input}
            )
        api_msgs.append({"role": "assistant", "content": content})
        api_msgs.append(
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": tc.id, "content": tc.result}
                    for tc in tool_calls
                ],
            }
        )
    return api_msgs


def _history_to_openai(history: list) -> list[dict]:
    api_msgs: list[dict] = []
    for turn in _iter_turns(history):
        if turn[0] == "user":
            api_msgs.append({"role": "user", "content": turn[1]})
            continue
        _, text, tool_calls = turn
        if not tool_calls:
            if text:
                api_msgs.append({"role": "assistant", "content": text})
            continue
        api_msgs.append(
            {
                "role": "assistant",
                "content": text or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.input),
                        },
                    }
                    for tc in tool_calls
                ],
            }
        )
        for tc in tool_calls:
            api_msgs.append(
                {"role": "tool", "tool_call_id": tc.id, "content": tc.result}
            )
    return api_msgs


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "list_schemas",
        "description": "List all schemas in the project with their field names, types, and restrictions.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_collections",
        "description": "List all collections (datasets) with their record counts.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_workflows",
        "description": (
            "Read all workflow YAML files in the project. "
            "REQUIRED: call this before answering any question that mentions a workflow by name, "
            "asks what a workflow does, or asks about fields/steps related to a workflow. "
            "Never answer from memory — always read the actual files."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_plugins",
        "description": "List all custom plugin Python files in _civex/plugins/, including their full source code.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_workflow_authoring_guide",
        "description": (
            "Returns the workflow YAML format spec, the complete built-in plugin reference, the custom "
            "plugin Python template, and the loop-prevention rules. REQUIRED: call this once before your "
            "first save_workflow or save_plugin call in a conversation — do not guess the YAML format or "
            "plugin signatures from memory. No need to call it again later in the same conversation."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "query_records",
        "description": "Search and count records of a given schema across all collections. Use count_only: true first for aggregate questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "schema": {
                    "type": "string",
                    "description": "Schema name to query (required)",
                },
                "search": {
                    "type": "string",
                    "description": "Full-text search string across all field values",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records to return (1–20). Default 5.",
                    "default": 5,
                },
                "count_only": {
                    "type": "boolean",
                    "description": "If true, return only the total count without record data.",
                    "default": False,
                },
            },
            "required": ["schema"],
        },
    },
    {
        "name": "list_records",
        "description": (
            "List or search records within a collection. Returns each record's id, schema, and field data. "
            "Use this to find records — e.g. to get the UUID needed for update_record or delete_record, or to browse a "
            "collection. For counting or searching across all collections of one schema, use query_records instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "collection": {
                    "type": "string",
                    "description": "Collection (dataset) to list records from (required)",
                },
                "schema": {
                    "type": "string",
                    "description": "Optional: only return records of this schema",
                },
                "search": {
                    "type": "string",
                    "description": "Optional full-text search across all field values",
                },
                "filters": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional exact-match filters, each 'field=value', AND-combined. Requires 'schema' to be set.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records to return (1–25). Default 10.",
                    "default": 10,
                },
            },
            "required": ["collection"],
        },
    },
    {
        "name": "get_job_log",
        "description": "Get the status, error message, and execution log of a workflow job by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "UUID of the job"},
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "save_workflow",
        "description": (
            "Validate a workflow YAML and propose it for saving. "
            "The user will see a confirmation UI in the browser and must click 'Save' — no file is written until they do. "
            "Call this after generating and displaying the YAML. The user does not need to say 'save' first."
        ),
        "input_schema": {
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
        },
    },
    {
        "name": "save_plugin",
        "description": (
            "Validate a plugin Python file and propose it for saving. "
            "The user will see a confirmation UI in the browser and must click 'Save' — no file is written until they do. "
            "Call this after generating and displaying the code. The user does not need to say 'save' first."
        ),
        "input_schema": {
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
        },
    },
    # -- Act tools: propose a direct data change. These NEVER execute on their own;
    #    they validate and return status "proposed". The user must click Approve in
    #    the UI to actually apply the change. Use these for one-off edits; use
    #    workflows/plugins for repeatable automation. --
    {
        "name": "create_record",
        "description": "Propose creating a new record in a collection. Requires user approval in the UI before it is saved.",
        "input_schema": {
            "type": "object",
            "properties": {
                "collection": {
                    "type": "string",
                    "description": "Target collection (must exist)",
                },
                "schema": {
                    "type": "string",
                    "description": "Schema the record conforms to (must exist)",
                },
                "data": {
                    "type": "object",
                    "description": "Field name → value map for the new record",
                },
            },
            "required": ["collection", "schema", "data"],
        },
    },
    {
        "name": "update_record",
        "description": "Propose updating fields on an existing record. Requires user approval in the UI.",
        "input_schema": {
            "type": "object",
            "properties": {
                "record_id": {
                    "type": "string",
                    "description": "UUID (or unique prefix) of the record",
                },
                "data": {
                    "type": "object",
                    "description": "Field name → new value map (only the fields to change)",
                },
            },
            "required": ["record_id", "data"],
        },
    },
    {
        "name": "delete_record",
        "description": "Propose deleting a record. Destructive — requires user approval in the UI.",
        "input_schema": {
            "type": "object",
            "properties": {
                "record_id": {
                    "type": "string",
                    "description": "UUID of the record to delete",
                }
            },
            "required": ["record_id"],
        },
    },
    {
        "name": "create_schema",
        "description": (
            "Propose creating a new schema, optionally with all of its fields, in a single proposal. "
            "Requires one user approval in the UI. "
            "ALWAYS pass 'fields' here when the schema needs more than one field — this creates the schema "
            "and every field as one approval instead of forcing the user to click Approve once per field via "
            "add_schema_field. Only use add_schema_field afterward for fields added to an already-existing schema."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "parent": {
                    "type": "string",
                    "description": "Optional parent schema to inherit fields from",
                },
                "fields": {
                    "type": "array",
                    "description": "Optional: fields to create along with the schema, in one proposal.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {
                                "type": "string",
                                "enum": sorted(VALID_DTYPES),
                                "description": (
                                    "Exactly one of these values, verbatim — no brackets, no generics, no "
                                    "combining two types into one string. For a link to another schema use "
                                    "'reference' or 'reference_list', not 'string'."
                                ),
                            },
                            "required": {"type": "boolean", "default": False},
                            "restrictions": {
                                "type": "object",
                                "description": "See the restrictions reference in the system prompt for valid keys per type.",
                            },
                            "default": {"description": "Optional default value"},
                        },
                        "required": ["name", "type"],
                    },
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "update_schema",
        "description": "Propose renaming a schema, changing its description, or setting its display field. Requires user approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Current schema name (must exist)",
                },
                "rename": {"type": "string"},
                "description": {"type": "string"},
                "display_field": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "delete_schema",
        "description": "Propose deleting a schema. Destructive — requires user approval in the UI.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "add_schema_field",
        "description": "Propose adding a field to an existing schema. Requires user approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "schema": {
                    "type": "string",
                    "description": "Schema to add the field to (must exist)",
                },
                "name": {"type": "string", "description": "New field name"},
                "type": {
                    "type": "string",
                    "enum": sorted(VALID_DTYPES),
                    "description": (
                        "Exactly one of these values, verbatim — no brackets, no generics, no combining "
                        "two types into one string. For a link to another schema use 'reference' or "
                        "'reference_list', not 'string'."
                    ),
                },
                "required": {"type": "boolean", "default": False},
                "restrictions": {
                    "type": "object",
                    "description": "Optional restriction map (min/max, choices, accept, schema, ...)",
                },
                "default": {"description": "Optional default value"},
            },
            "required": ["schema", "name", "type"],
        },
    },
    {
        "name": "update_schema_field",
        "description": "Propose changing a field on a schema (rename, required, restrictions, default). Requires user approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "schema": {"type": "string"},
                "field": {
                    "type": "string",
                    "description": "Current field name (must exist on the schema)",
                },
                "rename": {"type": "string"},
                "required": {"type": "boolean"},
                "restrictions": {"type": "object"},
                "default": {"description": "New default value"},
            },
            "required": ["schema", "field"],
        },
    },
    {
        "name": "delete_schema_field",
        "description": "Propose removing a field from a schema. Destructive — requires user approval in the UI.",
        "input_schema": {
            "type": "object",
            "properties": {
                "schema": {"type": "string"},
                "field": {"type": "string"},
            },
            "required": ["schema", "field"],
        },
    },
    {
        "name": "create_collection",
        "description": "Propose creating a new collection. Requires user approval in the UI.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "update_collection",
        "description": "Propose renaming a collection or changing its description. Requires user approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Current collection name (must exist)",
                },
                "rename": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "delete_collection",
        "description": "Propose deleting a collection. Destructive — requires user approval in the UI.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        # Anthropic caches everything in `tools` up to and including whichever entry
        # carries cache_control — TOOLS is fully static, so marking the last one caches
        # the entire tool-definitions block (Claude path only; ignored by TOOLS_OPENAI,
        # which only copies name/description/input_schema out of each entry).
        "cache_control": {"type": "ephemeral"},
    },
]


# ---------------------------------------------------------------------------
# Act-tool helpers — build a "proposed" change. The REST request is constructed
# server-side from validated inputs; the frontend executes it verbatim only after
# the user clicks Approve, so the model can never mutate data on its own and can
# never control an arbitrary URL.
# ---------------------------------------------------------------------------


def _tool_error(message: str) -> str:
    return json.dumps({"status": "error", "message": message})


def _restriction_error(dtype: str, restrictions: dict[str, Any] | None) -> str | None:
    """None if restrictions are valid for dtype, else a _tool_error() string."""
    if not restrictions:
        return None
    allowed = VALID_RESTRICTION_KEYS.get(dtype, frozenset())
    unknown = sorted(set(restrictions) - allowed)
    if not unknown:
        return None
    valid = ", ".join(sorted(allowed)) if allowed else "(none)"
    return _tool_error(
        f"Unknown restriction key(s) {unknown} for type '{dtype}'. Valid keys: {valid}"
    )


def _record_summary(r) -> dict:
    """Compact, file-safe view of a record for tool results (ids + field data)."""
    data: dict[str, Any] = {}
    for k, v in r.data.items():
        if isinstance(v, dict) and "sha256" in v:
            data[k] = f"<file: {v.get('filename', 'unknown')}>"
        elif isinstance(v, list) and v and isinstance(v[0], dict) and "sha256" in v[0]:
            data[k] = [f"<file: {f.get('filename', 'unknown')}>" for f in v]
        else:
            data[k] = v
    return {"id": str(r.id), "schema": r.schema_name, "data": data}


def _is_proposal(result_str: str) -> bool:
    """True if a tool result is an approval-requiring proposal (save_* or act tool)."""
    try:
        return json.loads(result_str).get("status") == "proposed"
    except Exception:
        return False


def _propose(
    action: str,
    summary: str,
    method: str,
    path: str,
    *,
    body: dict | None = None,
    destructive: bool = False,
    preview: dict | None = None,
) -> str:
    request: dict[str, Any] = {"method": method, "path": path}
    if body is not None:
        request["body"] = body
    out: dict[str, Any] = {
        "status": "proposed",
        "action": action,
        "summary": summary,
        "destructive": destructive,
        "request": request,
    }
    if preview is not None:
        out["preview"] = preview
    return json.dumps(out)


def _dispatch_act_tool(tool_name: str, ti: dict, ctx) -> str | None:
    """Handle the mutating 'act' tools. Returns None if tool_name isn't an act tool."""
    from urllib.parse import quote

    def q(v: str) -> str:
        return quote(str(v), safe="")

    schema_names = {s.name for s in ctx.schema_svc.list_all()}
    collection_names = {d.name for d in ctx.dataset_svc.list_all()}

    def record_or_none(rid: str):
        try:
            return ctx.record_svc.get(str(rid))
        except Exception:
            return None

    if tool_name == "create_record":
        collection, schema = ti["collection"], ti["schema"]
        data = ti.get("data") or {}
        if collection not in collection_names:
            return _tool_error(f"Collection '{collection}' does not exist.")
        if schema not in schema_names:
            return _tool_error(f"Schema '{schema}' does not exist.")
        return _propose(
            "create_record",
            f"Create a new '{schema}' record in collection '{collection}'.",
            "POST",
            f"/api/collections/{q(collection)}/records",
            body={"schema_name": schema, "data": data},
            preview={"collection": collection, "schema": schema, "data": data},
        )

    if tool_name == "update_record":
        rid = ti["record_id"]
        data = ti.get("data") or {}
        rec = record_or_none(rid)
        if rec is None:
            return _tool_error(f"Record '{rid}' not found.")
        if not data:
            return _tool_error("No fields provided to update.")
        return _propose(
            "update_record",
            f"Update record {str(rec.id)[:8]} ({rec.schema_name}) — set {', '.join(data.keys())}.",
            "PATCH",
            f"/api/records/{q(rec.id)}",
            body={"data": data},
            preview={"record_id": str(rec.id), "schema": rec.schema_name, "data": data},
        )

    if tool_name == "delete_record":
        rid = ti["record_id"]
        rec = record_or_none(rid)
        if rec is None:
            return _tool_error(f"Record '{rid}' not found.")
        return _propose(
            "delete_record",
            f"Delete record {str(rec.id)[:8]} ({rec.schema_name}). This cannot be undone.",
            "DELETE",
            f"/api/records/{q(rec.id)}",
            destructive=True,
            preview={
                "record_id": str(rec.id),
                "schema": rec.schema_name,
                "data": rec.data,
            },
        )

    if tool_name == "create_schema":
        name = ti["name"]
        parent = ti.get("parent")
        fields = ti.get("fields") or []
        if name in schema_names:
            return _tool_error(
                f"Schema '{name}' already exists — do not retry create_schema for it. "
                "If it's missing fields, call add_schema_field for each one instead; "
                "to change an existing field, use update_schema_field."
            )
        if parent and parent not in schema_names:
            return _tool_error(f"Parent schema '{parent}' does not exist.")
        seen_fields: set[str] = set()
        for f in fields:
            fname, ftype = f.get("name"), f.get("type")
            if not fname or not ftype:
                return _tool_error("Each field needs a 'name' and 'type'.")
            if fname in seen_fields:
                return _tool_error(f"Duplicate field name '{fname}'.")
            if ftype not in VALID_DTYPES:
                return _tool_error(
                    f"Unknown type '{ftype}' for field '{fname}'. Valid types: {', '.join(sorted(VALID_DTYPES))}"
                )
            err = _restriction_error(ftype, f.get("restrictions"))
            if err:
                return err
            seen_fields.add(fname)
        body: dict[str, Any] = {"name": name}
        if ti.get("description"):
            body["description"] = ti["description"]
        if parent:
            body["parent"] = parent
        if fields:
            body["fields"] = fields
        extra = f" inheriting from '{parent}'" if parent else ""
        field_note = (
            f" with {len(fields)} field{'s' if len(fields) != 1 else ''}"
            if fields
            else ""
        )
        return _propose(
            "create_schema",
            f"Create schema '{name}'{extra}{field_note}.",
            "POST",
            "/api/schemas",
            body=body,
            preview=body,
        )

    if tool_name == "update_schema":
        name = ti["name"]
        if name not in schema_names:
            return _tool_error(f"Schema '{name}' does not exist.")
        body = {
            k: ti[k]
            for k in ("rename", "description", "display_field")
            if ti.get(k) is not None
        }
        if not body:
            return _tool_error(
                "Nothing to change (provide rename, description, or display_field)."
            )
        return _propose(
            "update_schema",
            f"Update schema '{name}'.",
            "PATCH",
            f"/api/schemas/{q(name)}",
            body=body,
            preview={"name": name, **body},
        )

    if tool_name == "delete_schema":
        name = ti["name"]
        if name not in schema_names:
            return _tool_error(f"Schema '{name}' does not exist.")
        return _propose(
            "delete_schema",
            f"Delete schema '{name}'. This cannot be undone.",
            "DELETE",
            f"/api/schemas/{q(name)}",
            destructive=True,
            preview={"name": name},
        )

    if tool_name == "add_schema_field":
        schema, fname, ftype = ti["schema"], ti["name"], ti["type"]
        if schema not in schema_names:
            return _tool_error(f"Schema '{schema}' does not exist.")
        if ftype not in VALID_DTYPES:
            return _tool_error(
                f"Unknown type '{ftype}' for field '{fname}'. Valid types: {', '.join(sorted(VALID_DTYPES))}"
            )
        err = _restriction_error(ftype, ti.get("restrictions"))
        if err:
            return err
        body: dict[str, Any] = {
            "name": fname,
            "type": ftype,
            "required": bool(ti.get("required", False)),
        }
        if ti.get("restrictions"):
            body["restrictions"] = ti["restrictions"]
        if ti.get("default") is not None:
            body["default"] = ti["default"]
        return _propose(
            "add_schema_field",
            f"Add field '{fname}' ({ftype}) to schema '{schema}'.",
            "POST",
            f"/api/schemas/{q(schema)}/fields",
            body=body,
            preview={"schema": schema, **body},
        )

    if tool_name == "update_schema_field":
        schema, field = ti["schema"], ti["field"]
        if schema not in schema_names:
            return _tool_error(f"Schema '{schema}' does not exist.")
        if ti.get("restrictions"):
            existing = next(
                (f for f in ctx.schema_svc.get(schema).fields if f.name == field), None
            )
            if existing is None:
                return _tool_error(f"Field '{field}' not found on schema '{schema}'.")
            err = _restriction_error(existing.dtype, ti["restrictions"])
            if err:
                return err
        body = {
            k: ti[k]
            for k in ("rename", "required", "restrictions", "default")
            if ti.get(k) is not None
        }
        if not body:
            return _tool_error("Nothing to change on the field.")
        return _propose(
            "update_schema_field",
            f"Update field '{field}' on schema '{schema}'.",
            "PATCH",
            f"/api/schemas/{q(schema)}/fields/{q(field)}",
            body=body,
            preview={"schema": schema, "field": field, **body},
        )

    if tool_name == "delete_schema_field":
        schema, field = ti["schema"], ti["field"]
        if schema not in schema_names:
            return _tool_error(f"Schema '{schema}' does not exist.")
        return _propose(
            "delete_schema_field",
            f"Remove field '{field}' from schema '{schema}'. This cannot be undone.",
            "DELETE",
            f"/api/schemas/{q(schema)}/fields/{q(field)}",
            destructive=True,
            preview={"schema": schema, "field": field},
        )

    if tool_name == "create_collection":
        name = ti["name"]
        if name in collection_names:
            return _tool_error(
                f"Collection '{name}' already exists — do not retry create_collection for it. "
                "To change it, use update_collection instead."
            )
        body = {"name": name}
        if ti.get("description"):
            body["description"] = ti["description"]
        return _propose(
            "create_collection",
            f"Create collection '{name}'.",
            "POST",
            "/api/collections",
            body=body,
            preview=body,
        )

    if tool_name == "update_collection":
        name = ti["name"]
        if name not in collection_names:
            return _tool_error(f"Collection '{name}' does not exist.")
        body = {k: ti[k] for k in ("rename", "description") if ti.get(k) is not None}
        if not body:
            return _tool_error("Nothing to change (provide rename or description).")
        return _propose(
            "update_collection",
            f"Update collection '{name}'.",
            "PATCH",
            f"/api/collections/{q(name)}",
            body=body,
            preview={"name": name, **body},
        )

    if tool_name == "delete_collection":
        name = ti["name"]
        if name not in collection_names:
            return _tool_error(f"Collection '{name}' does not exist.")
        return _propose(
            "delete_collection",
            f"Delete collection '{name}' and its records. This cannot be undone.",
            "DELETE",
            f"/api/collections/{q(name)}",
            destructive=True,
            preview={"name": name},
        )

    return None


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

_ACT_TOOL_NAMES = frozenset(
    {
        "create_record",
        "update_record",
        "delete_record",
        "create_schema",
        "update_schema",
        "delete_schema",
        "add_schema_field",
        "update_schema_field",
        "delete_schema_field",
        "create_collection",
        "update_collection",
        "delete_collection",
    }
)


def _dispatch_tool(tool_name: str, tool_input: dict, ctx) -> str:
    try:
        if tool_name in _ACT_TOOL_NAMES:
            result = _dispatch_act_tool(tool_name, tool_input, ctx)
            if result is not None:
                return result

        if tool_name == "list_schemas":
            schemas = ctx.schema_svc.list_all()
            result = []
            for s in schemas:
                fields = [
                    {
                        k: v
                        for k, v in {
                            "name": f.name,
                            "type": f.dtype,
                            "restrictions": f.restrictions or None,
                        }.items()
                        if v
                    }
                    for f in s.fields
                ]
                result.append({"name": s.name, "fields": fields})
            return json.dumps(result)

        if tool_name == "list_collections":
            datasets = ctx.dataset_svc.list_all()
            return json.dumps(
                [{"name": d.name, "record_count": d.record_count} for d in datasets]
            )

        if tool_name == "list_workflows":
            try:
                config = load_config()
                workflows_dir = config.civex_dir / "workflows"
                if not workflows_dir.exists():
                    return json.dumps([])
                results = []
                for path in sorted(workflows_dir.glob("*.yaml")):
                    try:
                        content = path.read_text(encoding="utf-8")
                        results.append({"filename": path.name, "content": content})
                    except Exception as e:
                        results.append({"filename": path.name, "error": str(e)})
                return json.dumps(results)
            except Exception as e:
                return json.dumps({"error": str(e)})

        if tool_name == "list_plugins":
            try:
                config = load_config()
                plugins_dir = config.civex_dir / "plugins"
                if not plugins_dir.exists():
                    return json.dumps([])
                results = []
                for path in sorted(plugins_dir.glob("*.py")):
                    try:
                        code = path.read_text(encoding="utf-8")
                        results.append({"filename": path.name, "code": code})
                    except Exception as e:
                        results.append({"filename": path.name, "error": str(e)})
                return json.dumps(results)
            except Exception as e:
                return json.dumps({"error": str(e)})

        if tool_name == "get_workflow_authoring_guide":
            return WORKFLOW_AUTHORING_GUIDE

        if tool_name == "query_records":
            schema = tool_input["schema"]
            search = tool_input.get("search")
            limit = min(int(tool_input.get("limit", 5)), 20)
            count_only = bool(tool_input.get("count_only", False))

            all_records = ctx.record_svc.find_by_schema(
                schema, search=search, limit=1000
            )
            total = len(all_records)
            suffix = "" if total < 1000 else "+"

            if count_only:
                return json.dumps({"total": f"{total}{suffix}"})

            records_out = [_record_summary(r) for r in all_records[:limit]]
            return json.dumps({"total": f"{total}{suffix}", "records": records_out})

        if tool_name == "list_records":
            collection = tool_input["collection"]
            if collection not in {d.name for d in ctx.dataset_svc.list_all()}:
                return _tool_error(f"Collection '{collection}' does not exist.")
            schema = tool_input.get("schema") or None
            search = tool_input.get("search") or None
            filters = tool_input.get("filters") or None
            # Exact-field filters resolve field names via the schema (records are
            # stored keyed by field id), so a schema is required to use them.
            if filters and not schema:
                return _tool_error(
                    "To filter by a specific field, also pass 'schema'. "
                    "Otherwise use 'search' for a free-text match across all fields."
                )
            limit = min(max(int(tool_input.get("limit", 10)), 1), 25)
            total = ctx.record_svc.count(
                collection, schema_name=schema, filters=filters, search=search
            )
            records = ctx.record_svc.find(
                collection,
                schema_name=schema,
                filters=filters,
                search=search,
                limit=limit,
            )
            return json.dumps(
                {"total": total, "records": [_record_summary(r) for r in records]}
            )

        if tool_name == "get_job_log":
            import uuid

            try:
                job = ctx.job_svc.get_job(uuid.UUID(tool_input["job_id"]))
                return json.dumps(
                    {"status": job.status, "error": job.error, "log": job.log}
                )
            except (NotFoundError, ValueError):
                return json.dumps({"error": "job not found"})

        if tool_name == "save_workflow":
            stem = tool_input["stem"]
            content = tool_input["content"]
            if not re.match(r"^[\w-]+$", stem):
                return json.dumps(
                    {
                        "status": "error",
                        "message": "stem must contain only letters, numbers, hyphens, and underscores",
                    }
                )
            try:
                import yaml as _yaml

                raw = _yaml.safe_load(content)
                from civex.workflows.definition import WorkflowDef

                WorkflowDef.model_validate(raw)
            except Exception as e:
                return json.dumps(
                    {"status": "error", "message": f"Invalid workflow YAML: {e}"}
                )
            return json.dumps({"status": "proposed", "stem": stem, "content": content})

        if tool_name == "save_plugin":
            name = tool_input["name"]
            code = tool_input["code"]
            if not _SAFE_PLUGIN_NAME.match(name):
                return json.dumps(
                    {
                        "status": "error",
                        "message": "name must be lowercase letters, digits, and underscores only",
                    }
                )
            try:
                tree = ast.parse(code)
            except SyntaxError as e:
                return json.dumps({"status": "error", "message": f"Syntax error: {e}"})
            has_plugin_class = any(
                isinstance(node, ast.ClassDef) and node.name == "Plugin"
                for node in ast.walk(tree)
            )
            if not has_plugin_class:
                return json.dumps(
                    {
                        "status": "error",
                        "message": "Code must define a class named 'Plugin'",
                    }
                )
            return json.dumps({"status": "proposed", "name": name, "code": code})

    except Exception as e:
        return json.dumps({"error": str(e)})

    return json.dumps({"error": f"unknown tool: {tool_name}"})


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_OPENROUTER_FREE_DAILY_LIMIT = 50

# Returned by the get_workflow_authoring_guide tool rather than inlined in the system
# prompt on every request — it's only relevant when the model is actually about to draft
# a workflow or plugin, which is a minority of turns. Static (no ctx/schema data), so it's
# defined once at import time instead of rebuilt per-request like _build_system_prompt.
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


def _build_system_prompt(ctx, ai_cfg=None) -> str:
    schemas = ctx.schema_svc.list_all()
    collections = ctx.dataset_svc.list_all()

    schema_compact = []
    total_chars = 0
    for s in schemas:
        fields = [
            {
                k: v
                for k, v in {
                    "name": f.name,
                    "type": f.dtype,
                    "restrictions": f.restrictions or None,
                }.items()
                if v
            }
            for f in s.fields
        ]
        entry = {"name": s.name, "fields": fields}
        entry_str = json.dumps(entry)
        total_chars += len(entry_str)
        if total_chars > 8000:
            schema_compact.append(
                {
                    "name": "...",
                    "note": "additional schemas truncated — use list_schemas tool",
                }
            )
            break
        schema_compact.append(entry)

    collections_csv = ", ".join(d.name for d in collections) or "(none yet)"

    is_openrouter = ai_cfg is not None and "openrouter.ai" in (ai_cfg.base_url or "")
    openrouter_note = (
        f"""

## REQUEST BUDGET — READ CAREFULLY
You are running on OpenRouter free tier: {_OPENROUTER_FREE_DAILY_LIMIT} requests per day TOTAL.
Every tool call costs 1 additional API request on top of the base conversation request.
A single user message that triggers 3 tool calls uses 4 requests.

STRICT rules to conserve budget:
- Answer from the schemas/collections already in this system prompt — do NOT call list_schemas unless the user explicitly asks to refresh or mentions a schema not listed above.
- Do NOT call list_workflows or list_plugins unless the user directly references a specific workflow or plugin by name and you need its content to answer correctly.
- Do NOT call query_records for general questions — only when the user explicitly asks about their data.
- If multiple tool calls are unavoidable, make them all in a SINGLE response (parallel), never sequentially across multiple rounds.
- Prefer concise answers over exhaustive ones to reduce follow-up questions.
- Re-reading rules 1-3 above: do not ask for confirmation before act/save tools, do not preview schema/field/record
  changes as YAML, and put every field into create_schema's `fields` array in one call. Smaller free models tend to
  skip these — follow them exactly."""
        if is_openrouter
        else ""
    )

    is_local_model = _is_ollama(ai_cfg)
    local_model_note = (
        """

## RUNNING ON A SMALL LOCAL MODEL — READ CAREFULLY
You are running as a small (~7B) locally-hosted model via Ollama, not a large hosted model. You are more
prone to two specific mistakes than a larger model — watch for them explicitly:
1. Inventing field type strings. The `type` field on create_schema/add_schema_field is a closed set of
   exact values (see that tool's schema) — copy one value verbatim. Never combine two types, add
   brackets, or invent generic-looking syntax like "reference_list[tags]". If unsure which type fits,
   use "string" and say so in your reply — do not guess a fancier-looking type name.
2. Abandoning the task after a tool error. If a call returns status "error", the error message names the
   exact problem — fix only that, and retry with the SAME schema/field name the user asked for. Never
   switch to a different, new, or invented name to work around an error."""
        if is_local_model
        else ""
    )

    return f"""You are an AI assistant embedded in civex, a local-first research data management tool.
You help with five things: (1) explaining how civex works, (2) querying data, (3) building workflow
automations, (4) writing custom plugins, (5) making direct one-off changes to records, schemas, and
collections via the "act" tools — every such change is only a PROPOSAL that the user must approve in the UI.

## Four rules that override everything else below
1. Never ask "would you like me to proceed?" or "should I go ahead?" before calling a save_* or act tool.
   Just call it. The UI's Approve/Cancel card IS the confirmation step — asking first is a redundant
   extra round-trip and is treated as a bug in this assistant.
2. Never draft a schema, field, or record change as a YAML/JSON preview block in your text reply.
   YAML is ONLY the on-disk format for workflows and plugins — schemas, fields, and records are created
   by calling the tool directly (create_schema, add_schema_field, create_record, ...), not by describing
   them in prose first.
3. When a schema needs more than one field, pass them all in create_schema's `fields` array in the SAME
   call. Do not call create_schema and then add_schema_field once per field — that forces one manual
   approval click per field, which is exactly the kind of task that gets abandoned halfway.
4. When a field represents a link to another schema — the user says "relates to", "linked to", "belongs
   to", "references", "for each <X>", or otherwise describes one record pointing at another — you MUST
   use `type: "reference"` (one target) or `type: "reference_list"` (many targets) with
   `restrictions: {{"schema": "<TargetSchemaName>"}}`. NEVER model a relationship as a plain `string`
   field holding a name — that silently drops referential integrity and breaks reference-aware UI. If the
   target schema doesn't exist yet in "Current project schemas" below, create it first (or in the same
   turn), then add the reference field pointing at it.

## What civex is
civex organises research data into Schemas (field definitions) and Collections (named containers for records).
Records belong to a Collection and conform to a Schema. Field types: integer, float, string, boolean,
date, datetime, file, file_list, reference (UUID of another record), enum (string with choices list),
url, reference_list, tags (list of strings). Fields can have restrictions (min/max, choices, max_size, etc.)
and default values. Schemas support inheritance — parent schema fields are appended automatically.
Every record has an automatic UUID `id` assigned by civex — never define a user-facing field named `id`.

Workflows automate actions triggered by record events or run manually. Each workflow is a YAML file
in _civex/workflows/. Custom plugins extend the built-in plugin set and live in _civex/plugins/*.py.
Their exact format (YAML spec, built-in plugin signatures, plugin template, loop-prevention rules) is
NOT included below — call get_workflow_authoring_guide once before drafting either.

## Field restrictions reference (valid `restrictions` keys by field type — do not invent other keys)
integer, float        → min, max
string                 → choices (list of allowed values), max_length
date, datetime         → min, max (ISO strings, e.g. "2024-01-01")
file, file_list        → accept (comma-separated MIME types/extensions), max_size (bytes)
reference, reference_list → schema (name of the target schema)
enum                   → choices (list of allowed values)
boolean, url, tags     → (no restriction keys)

Example — a field that must accept CSV, XLSX, or TXT files (a "file that can be one of several formats"
is still ONE field of type "file", never a made-up combined type):
  {{"name": "selection_table_file", "type": "file", "restrictions": {{"accept": ".csv,.xlsx,.txt"}}}}

Same rule for a SINGLE extension — still the `accept` key, comma-separated with just one entry.
Never invent a key like "format", "extension", or "ext" for this:
  {{"name": "recording_file", "type": "file", "restrictions": {{"accept": ".wav"}}}}

## Current project schemas
{json.dumps(schema_compact, indent=2)}

Available collections: {collections_csv}

## MANDATORY tool-use rules (follow before every response)

1. WORKFLOW MENTIONED → call list_workflows FIRST, unconditionally.
   Any time the user's message contains a workflow name or asks about a workflow, you MUST call list_workflows
   before saying anything. Do not paraphrase, guess, or answer from memory. Read the actual YAML.

2. SCHEMA QUESTION → use the "Current project schemas" section above FIRST.
   The schemas are already injected above. Reference them explicitly. If asked about fields on an existing schema,
   quote the actual field names and types from the injection. Do not invent fields or suggest ones that already exist.
   If you need fresher data, call list_schemas.

3. PLUGIN MENTIONED → call list_plugins FIRST before answering.

4. SAVE FLOW — call get_workflow_authoring_guide first if you haven't already this conversation (it
   has the YAML format, plugin reference, and loop-prevention rules — do not guess them). Then, after
   generating content, call save_workflow or save_plugin immediately.
   The UI shows the user a confirmation dialog before anything is written to disk.
   You do not need to ask the user first — the guardrail is in the UI, not in your response.

5. ACT TOOLS (create/update/delete records, schemas, fields, collections) — these DO NOT execute.
   They validate the change and return status "proposed"; the UI then shows the user an Approve/Cancel
   card, and nothing happens until the user clicks Approve. So:
   - When the user asks to change data, call the matching act tool directly — do NOT build a workflow or
     plugin for a one-off edit, and do NOT ask "are you sure?" first (the approval card IS the confirmation).
   - Prefer act tools for one-off changes; use workflows/plugins only for repeatable automation.
   - Creating a schema with fields is ONE call: create_schema with a `fields` array. Never split it into
     create_schema followed by N separate add_schema_field calls.
   - BEFORE calling create_schema or create_collection, check whether the name already appears in
     "Current project schemas" / "Available collections" above. If it does, it was already created
     (possibly in an earlier turn of this same conversation) — do not call create_schema/create_collection
     again. Use add_schema_field to add any fields it's still missing, or update_schema/update_schema_field
     to change existing ones.
   - Never claim the change was made. After proposing, say what you proposed and that it awaits approval.
   - Deletes are destructive and shown with a red confirmation card — propose them only when clearly asked.
   - For update_record/delete_record you must know the record's UUID. If you only have a description, first call
     list_records (to search within a collection) or query_records (to search a schema across collections) to find it.
   - If a tool call returns status "error", fix the SPECIFIC problem named in the message and retry the SAME
     call — same schema name, same field name, same intent. Never respond to an error by inventing a
     different, new, or unrelated schema/field name; that abandons what the user actually asked for.

## Other guidelines
- For count/aggregate questions about ONE schema, use query_records with count_only: true.
- For "how many records total" (across every schema/collection), there is no single count-everything tool —
  call list_collections and sum the `record_count` of every collection. Do this in one tool call, not a
  guess-and-retry loop.
- To find or browse records in a collection (or get a record's UUID), use list_records.
- Use descriptive kebab-case stems: "parse-audio-dates", not "workflow1".
- Ask for clarification if schema name, trigger type, or plugin logic is ambiguous.
- For civex how-to questions, answer from your knowledge of this system prompt — no tool calls needed.
- Keep responses concise.{openrouter_note}{local_model_note}"""


# ---------------------------------------------------------------------------
# Tool definitions in OpenAI format (for openai-compat providers)
# ---------------------------------------------------------------------------

TOOLS_OPENAI = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in TOOLS
]


# ---------------------------------------------------------------------------
# Streaming generator — Anthropic path
# ---------------------------------------------------------------------------


async def _stream_chat_anthropic(history: list, ctx, ai_cfg):
    try:
        import anthropic
    except ImportError:
        yield _sse(
            {
                "type": "error",
                "message": "anthropic package not installed. Run: pip install 'civex[ai]'",
            }
        )
        return

    client = anthropic.AsyncAnthropic(api_key=ai_cfg.api_key)
    # cache_control on the system block caches the whole (static-per-project) prompt
    # server-side for ~5 min, so every extra tool round in this turn — and every
    # follow-up message in the conversation within that window — reuses it instead of
    # re-processing ~1.7k tokens of instructions from scratch.
    system = [
        {
            "type": "text",
            "text": _build_system_prompt(ctx, ai_cfg=ai_cfg),
            "cache_control": {"type": "ephemeral"},
        }
    ]
    # Reconstructs any tool calls/results from earlier turns into Anthropic's
    # native tool_use/tool_result shape, so the model still has them in view
    # even though they were made in a previous, separate HTTP request.
    api_msgs = _history_to_anthropic(history)
    rounds = 0

    while rounds < MAX_TOOL_ROUNDS:
        async with client.messages.stream(
            model=ai_cfg.model,
            system=system,
            messages=api_msgs,
            tools=TOOLS,
            max_tokens=4096,
        ) as stream:
            async for delta in stream.text_stream:
                yield _sse({"type": "text_delta", "delta": delta})
            final = await stream.get_final_message()

        if final.stop_reason == "end_turn":
            break

        rounds += 1
        api_msgs.append(
            {"role": "assistant", "content": [b.model_dump() for b in final.content]}
        )
        tool_results = []
        proposal_pending = False

        for block in final.content:
            if block.type != "tool_use":
                continue
            yield _sse(
                {
                    "type": "tool_use_start",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            )
            result_str = _dispatch_tool(block.name, block.input, ctx)
            yield _sse(
                {"type": "tool_result", "tool_use_id": block.id, "content": result_str}
            )
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": result_str}
            )
            if _is_proposal(result_str):
                proposal_pending = True

        # A proposed change needs the user's approval in the UI. Stop streaming here
        # so the approval prompt is the last thing shown (chronological); the model
        # continues on the next turn once the change has been approved/applied.
        if proposal_pending:
            break

        api_msgs.append({"role": "user", "content": tool_results})

    if rounds >= MAX_TOOL_ROUNDS:
        yield _sse(
            {
                "type": "error",
                "message": "Maximum tool rounds exceeded — please try a simpler request.",
            }
        )
        return

    yield _sse({"type": "done"})


# ---------------------------------------------------------------------------
# Streaming generator — OpenAI-compatible path (Groq, Gemini, Ollama, etc.)
# ---------------------------------------------------------------------------


async def _stream_chat_openai(history: list, ctx, ai_cfg):
    try:
        from openai import AsyncOpenAI
    except ImportError:
        yield _sse(
            {
                "type": "error",
                "message": "openai package not installed. Run: pip install 'civex[ai]'",
            }
        )
        return

    is_openrouter = "openrouter.ai" in (ai_cfg.base_url or "")
    extra_headers = (
        {"HTTP-Referer": "http://localhost:8000", "X-Title": "civex"}
        if is_openrouter
        else {}
    )
    client = AsyncOpenAI(
        api_key=ai_cfg.api_key, base_url=ai_cfg.base_url, default_headers=extra_headers
    )
    system = _build_system_prompt(ctx, ai_cfg=ai_cfg)
    # Reconstructs any tool calls/results from earlier turns into OpenAI's
    # native tool_calls/tool-role-message shape (see _stream_chat_anthropic).
    api_msgs: list[dict] = [{"role": "system", "content": system}] + _history_to_openai(
        history
    )
    # See OLLAMA_NUM_CTX above -- request a larger context window than Ollama's
    # default so a big tool result (e.g. the workflow authoring guide) doesn't
    # silently push the task/instructions out of the model's view mid-turn.
    extra_body = (
        {"options": {"num_ctx": OLLAMA_NUM_CTX}} if _is_ollama(ai_cfg) else None
    )
    rounds = 0

    while rounds < MAX_TOOL_ROUNDS:
        # Accumulate tool call chunks while streaming text
        tool_calls_acc: dict[int, dict] = {}

        stream = await client.chat.completions.create(
            model=ai_cfg.model,
            messages=api_msgs,  # type: ignore[arg-type]
            tools=TOOLS_OPENAI,  # type: ignore[arg-type]
            stream=True,
            extra_body=extra_body,
        )

        finish_reason: str | None = None
        assistant_text = ""

        try:
            async for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if not choice:
                    continue
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
                delta = choice.delta
                if delta.content:
                    assistant_text += delta.content
                    yield _sse({"type": "text_delta", "delta": delta.content})
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": "",
                                "name": "",
                                "arguments": "",
                            }
                        if tc.id:
                            tool_calls_acc[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_acc[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_calls_acc[idx]["arguments"] += (
                                    tc.function.arguments
                                )
        except Exception as api_err:
            yield _sse(
                {
                    "type": "error",
                    "message": f"Provider error: {api_err}. Try rephrasing your request.",
                }
            )
            return

        if finish_reason != "tool_calls" or not tool_calls_acc:
            break

        rounds += 1

        # Build assistant message with tool_calls for history
        assistant_msg: dict = {
            "role": "assistant",
            "content": assistant_text or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in tool_calls_acc.values()
            ],
        }
        api_msgs.append(assistant_msg)

        proposal_pending = False
        for tc in tool_calls_acc.values():
            try:
                tool_input = json.loads(tc["arguments"])
                if not isinstance(tool_input, dict):
                    tool_input = {}
            except json.JSONDecodeError:
                tool_input = {}
            yield _sse(
                {
                    "type": "tool_use_start",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tool_input,
                }
            )
            result_str = _dispatch_tool(tc["name"], tool_input, ctx)
            yield _sse(
                {"type": "tool_result", "tool_use_id": tc["id"], "content": result_str}
            )
            api_msgs.append(
                {"role": "tool", "tool_call_id": tc["id"], "content": result_str}
            )
            if _is_proposal(result_str):
                proposal_pending = True

        # Stop at a proposed change so the approval prompt is the last thing shown.
        if proposal_pending:
            break

    if rounds >= MAX_TOOL_ROUNDS:
        yield _sse(
            {
                "type": "error",
                "message": "Maximum tool rounds exceeded — please try a simpler request.",
            }
        )
        return

    yield _sse({"type": "done"})


def _stream_chat(history: list, ctx, ai_cfg):
    if ai_cfg.provider == "openai-compat":
        return _stream_chat_openai(history, ctx, ai_cfg)
    return _stream_chat_anthropic(history, ctx, ai_cfg)


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------


class AiConfigResponse(BaseModel):
    configured: bool
    source: str  # "config" | "env" | "none"
    model: str
    provider: str  # "anthropic" | "openai-compat"
    base_url: str | None
    key_hint: str | None  # last 6 chars of key, or None


class AiConfigUpdate(BaseModel):
    api_key: str | None = None
    model: str | None = None
    provider: str | None = None
    base_url: str | None = None


ANTHROPIC_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-opus-4-8",
]


@router.get("/config", response_model=AiConfigResponse)
def get_ai_config():
    try:
        config = load_config()
    except ConfigError as e:
        raise HTTPException(503, detail=str(e))
    if not config.ai:
        return AiConfigResponse(
            configured=False,
            source="none",
            model="claude-sonnet-4-6",
            provider="anthropic",
            base_url=None,
            key_hint=None,
        )
    key = config.ai.api_key
    hint = f"...{key[-6:]}" if len(key) >= 6 else "***"
    return AiConfigResponse(
        configured=True,
        source="env" if config.ai.from_env else "config",
        model=config.ai.model,
        provider=config.ai.provider,
        base_url=config.ai.base_url,
        key_hint=hint,
    )


@router.patch("/config", response_model=AiConfigResponse)
def update_ai_config(body: AiConfigUpdate):
    try:
        config = load_config()
    except ConfigError as e:
        raise HTTPException(503, detail=str(e))

    current = config.ai
    new_provider = (
        body.provider
        if body.provider is not None
        else (current.provider if current else "anthropic")
    )
    new_base_url = (
        body.base_url
        if body.base_url is not None
        else (current.base_url if current else None)
    )

    if new_provider not in ("anthropic", "openai-compat"):
        raise HTTPException(
            422, detail="provider must be 'anthropic' or 'openai-compat'"
        )
    if new_provider == "openai-compat" and not new_base_url:
        raise HTTPException(
            422, detail="base_url is required for openai-compat provider"
        )

    new_model = (
        body.model
        if body.model is not None
        else (current.model if current else "claude-sonnet-4-6")
    )
    if new_provider == "anthropic" and new_model not in ANTHROPIC_MODELS:
        raise HTTPException(
            422,
            detail=f"Unsupported Anthropic model. Choose one of: {', '.join(ANTHROPIC_MODELS)}",
        )

    current_key = current.api_key if current else ""
    new_key = body.api_key if body.api_key is not None else current_key
    if not new_key:
        raise HTTPException(422, detail="api_key is required")

    config.ai = AIConfig(
        api_key=new_key,
        model=new_model,
        provider=new_provider,
        base_url=new_base_url or None,
        from_env=False,
    )
    try:
        save_config(config)
    except Exception as e:
        raise HTTPException(500, detail=str(e))

    hint = f"...{new_key[-6:]}" if len(new_key) >= 6 else "***"
    return AiConfigResponse(
        configured=True,
        source="config",
        model=new_model,
        provider=new_provider,
        base_url=new_base_url or None,
        key_hint=hint,
    )


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------


@router.post("/chat")
async def chat(body: ChatRequest):
    try:
        config = load_config()
    except ConfigError as e:

        async def no_project():
            yield _sse({"type": "error", "message": str(e)})

        return StreamingResponse(
            no_project(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if not config.ai:

        async def no_key():
            yield _sse(
                {
                    "type": "error",
                    "message": (
                        "AI assistant not configured. Click the ⚙ gear icon to set up a provider.\n\n"
                        "Free option: use Groq (no credit card, generous free tier).\n"
                        "Get a free key at console.groq.com → API Keys.\n\n"
                        "Or set ANTHROPIC_API_KEY environment variable for Claude."
                    ),
                }
            )

        return StreamingResponse(
            no_key(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    ctx = build_local_context(config)

    async def gen():
        try:
            async for chunk in _stream_chat(body.messages, ctx, config.ai):
                yield chunk
        except Exception as e:
            yield _sse({"type": "error", "message": f"Unexpected error: {e}"})
        finally:
            ctx.close()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# OpenRouter OAuth + limits endpoints
# ---------------------------------------------------------------------------


@router.get("/openrouter/auth-url")
async def openrouter_auth_url(request: Request):
    """Return the OAuth URL for the OpenRouter login flow."""
    base = str(request.base_url).rstrip("/")
    callback = f"{base}/api/ai/openrouter/callback"
    return {"url": f"https://openrouter.ai/auth?callback_url={callback}"}


@router.get("/openrouter/callback")
async def openrouter_callback(code: str):
    """Receive OAuth code from OpenRouter, exchange for key, save to config."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                "https://openrouter.ai/api/v1/auth/keys",
                json={"code": code},
            )
        if not resp.is_success:
            raise ValueError(
                f"OpenRouter returned {resp.status_code}: {resp.text[:200]}"
            )
        key = resp.json().get("key")
        if not key:
            raise ValueError("No key in OpenRouter response")
    except Exception as e:
        return HTMLResponse(
            f"<html><body style='font-family:sans-serif;padding:2rem'>"
            f"<h2 style='color:#d1242f'>Login failed</h2><p>{e}</p></body></html>",
            status_code=400,
        )

    try:
        config = load_config()
        default_model = (
            config.ai.model
            if config.ai and "openrouter" not in (config.ai.base_url or "")
            else "meta-llama/llama-3.1-8b-instruct:free"
        )
        config.ai = AIConfig(
            api_key=key,
            model=default_model,
            provider="openai-compat",
            base_url=OPENROUTER_BASE_URL,
            from_env=False,
        )
        save_config(config)
    except Exception as e:
        return HTMLResponse(
            f"<html><body style='font-family:sans-serif;padding:2rem'>"
            f"<h2 style='color:#d1242f'>Could not save config</h2><p>{e}</p></body></html>",
            status_code=500,
        )

    return HTMLResponse("""<html><head><title>civex — OpenRouter connected</title></head>
<body style="font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#f6f8fa">
<div style="text-align:center;padding:2rem">
  <div style="font-size:2.5rem">✓</div>
  <h2 style="margin:.5rem 0;color:#1a7f37">Connected to OpenRouter</h2>
  <p style="color:#656d76;margin:0">You can close this tab and return to civex.</p>
</div>
<script>setTimeout(()=>window.close(),1500)</script>
</body></html>""")


@router.get("/ollama/models")
async def ollama_models(base_url: str = "http://localhost:11434/v1"):
    """List models installed in a running Ollama instance."""
    import httpx
    from urllib.parse import urlparse

    # SSRF guard: this endpoint fetches base_url server-side, so restrict it to a
    # local Ollama instance — never let a caller point the server at arbitrary URLs.
    if (urlparse(base_url).hostname or "").lower() not in (
        "localhost",
        "127.0.0.1",
        "::1",
    ):
        raise HTTPException(
            400, detail="base_url must point to a local Ollama instance (localhost)."
        )

    tags_url = base_url.rstrip("/").removesuffix("/v1") + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5) as http:
            resp = await http.get(tags_url)
        if not resp.is_success:
            raise HTTPException(
                resp.status_code, detail=f"Ollama error: {resp.text[:200]}"
            )
        raw = resp.json().get("models", [])
        return {"models": [{"name": m["name"], "size": m.get("size", 0)} for m in raw]}
    except httpx.ConnectError:
        raise HTTPException(
            503, detail=f"Ollama is not running at {base_url.removesuffix('/v1')}"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/openrouter/limits")
async def openrouter_limits():
    """Proxy GET https://openrouter.ai/api/v1/key to expose usage/rate-limit info."""
    try:
        config = load_config()
    except ConfigError as e:
        raise HTTPException(400, detail=str(e))
    if not config.ai or "openrouter.ai" not in (config.ai.base_url or ""):
        raise HTTPException(400, detail="Not configured for OpenRouter")

    import httpx

    async with httpx.AsyncClient(timeout=10) as http:
        resp = await http.get(
            "https://openrouter.ai/api/v1/key",
            headers={"Authorization": f"Bearer {config.ai.api_key}"},
        )
    if not resp.is_success:
        raise HTTPException(resp.status_code, detail=f"OpenRouter: {resp.text[:200]}")
    return resp.json()
