"""AiService: system-prompt construction and the provider-agnostic tool-round loop.

AiService is the class the rest of the app (AppContext) talks to; it's a
thin wrapper delegating to the free functions below. Individual tool
definitions/behavior live in services/ai/tools/ (CIVEX-54, one AiTool
subclass per tool, TOOL_REGISTRY is the single source of truth). Per-provider
API shape (Anthropic vs. OpenAI-compatible) lives in services/ai/providers/
(CIVEX-51, one ChatProvider subclass per API shape) -- this module owns what's
shared across every provider: dispatching a tool call by name (_dispatch_tool,
a thin adapter onto the registry), the system prompt, and the single
MAX_TOOL_ROUNDS loop that drives whichever ChatProvider get_chat_provider()
returns. The router still owns HTTP request/response models, the /ai/config
endpoints, and the OpenRouter/Ollama proxy endpoints.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator

from civex.services.ai.providers import (
    AnthropicProvider,
    ErrorEvent,
    OpenAIProvider,
    RoundEnd,
    TextDelta,
    get_chat_provider,
)
from civex.services.ai.tools.registry import all_tools
from civex.services.ai.tools.registry import dispatch as _registry_dispatch

if TYPE_CHECKING:
    from civex.config import AIConfig
    from civex.context import AppContext
    from civex.services.dataset_service import DatasetService
    from civex.services.record_service import RecordService
    from civex.services.schema_service import SchemaService
    from civex.services.workflow_job_service import WorkflowJobService

MAX_TOOL_ROUNDS = 10


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# AiService — the public entry point AppContext wires up. A thin wrapper: it
# holds the same four services _dispatch_tool/_build_system_prompt already
# expect on a "ctx"-shaped object (schema_svc, dataset_svc, record_svc,
# job_svc) and passes itself as that ctx, so none of the free functions
# above needed to change shape for this to slot in.
# ---------------------------------------------------------------------------


class AiService:
    def __init__(
        self,
        schema_svc: SchemaService,
        dataset_svc: DatasetService,
        record_svc: RecordService,
        job_svc: WorkflowJobService,
    ) -> None:
        self.schema_svc = schema_svc
        self.dataset_svc = dataset_svc
        self.record_svc = record_svc
        self.job_svc = job_svc
        # Bound by build_local_context() right after construction (AppContext
        # itself needs a fully-built AiService to exist first) -- gives act-tool
        # proposal builders a validation_scope() without AiService needing to
        # hold a second copy of every service AppContext already has.
        self._app_ctx: AppContext | None = None

    def dispatch_tool(self, tool_name: str, tool_input: dict) -> str:
        return _dispatch_tool(tool_name, tool_input, self)

    def stream_chat(self, history: list, ai_cfg: AIConfig):
        """Async generator of SSE-frame strings (router.chat() consumes this
        directly, wrapping any pre-provider errors of its own in _sse())."""
        return _stream_chat(history, self, ai_cfg)

    @contextmanager
    def validation_scope(self) -> Iterator[None]:
        assert self._app_ctx is not None, (
            "AiService used before build_local_context() bound it to an AppContext"
        )
        with self._app_ctx.validation_scope():
            yield


# ---------------------------------------------------------------------------
# Tool definitions -- computed views over TOOL_REGISTRY (CIVEX-54), shaped by
# each ChatProvider's own render_tools() (CIVEX-51). A tool's
# name/description/input_schema/mutating lives in exactly one place, its
# AiTool subclass under services/ai/tools/builtins/; nothing here is
# hand-maintained.
# ---------------------------------------------------------------------------

TOOLS = AnthropicProvider().render_tools(all_tools().values())
TOOLS_OPENAI = OpenAIProvider().render_tools(all_tools().values())


# ---------------------------------------------------------------------------
# Streaming-loop helper: does a tool result require the user's approval?
# ---------------------------------------------------------------------------


def _is_proposal(result_str: str) -> bool:
    """True if a tool result is an approval-requiring proposal (save_* or act tool)."""
    try:
        return json.loads(result_str).get("status") == "proposed"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


def _dispatch_tool(tool_name: str, tool_input: dict, ctx) -> str:
    """`ctx` is the AiService instance (or anything exposing the same
    schema_svc/dataset_svc/record_svc/job_svc attributes plus a bound
    _app_ctx) -- builds the narrower AiToolContext the tool registry expects
    and delegates.
    """
    from civex.services.ai.tools.base import AiToolContext

    tool_ctx = AiToolContext(
        schema_svc=ctx.schema_svc,
        dataset_svc=ctx.dataset_svc,
        record_svc=ctx.record_svc,
        job_svc=ctx.job_svc,
        workflow_svc=ctx._app_ctx.workflow_svc,
        plugin_svc=ctx._app_ctx.plugin_svc,
        _app_ctx=ctx._app_ctx,
    )
    return _registry_dispatch(tool_name, tool_input, tool_ctx)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------


def _build_system_prompt(ctx, prompt_fragment: str = "") -> str:
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
   - NEVER call create_record/update_record/delete_record with a record_id you did not just receive from
     an actual list_records/query_records/get_job_log result in this conversation — never a made-up,
     placeholder, or all-zero UUID. If you don't have a real UUID in view, call list_records or
     query_records first; if that also fails, stop and tell the user instead of guessing an ID.

6. STOP once the user's request is fully answered. Do not chain additional tool calls (checking other
   collections/schemas, or proposing changes) that the user did not ask for. A "find"/"look up"/"how many"
   question is answered by reporting the result — it is not an invitation to also verify, clean up, or
   modify anything else.

## Other guidelines
- For count/aggregate questions about ONE schema, use query_records with count_only: true.
- For "how many records total" (across every schema/collection), there is no single count-everything tool —
  call list_collections and sum the `record_count` of every collection. Do this in one tool call, not a
  guess-and-retry loop.
- To find or browse records in a collection (or get a record's UUID), use list_records.
- Use descriptive kebab-case stems: "parse-audio-dates", not "workflow1".
- Ask for clarification if schema name, trigger type, or plugin logic is ambiguous.
- For civex how-to questions, answer from your knowledge of this system prompt — no tool calls needed.
- Keep responses concise.{prompt_fragment}"""


# ---------------------------------------------------------------------------
# Streaming generator — provider-agnostic tool-round loop (CIVEX-51). Drives
# whichever ChatProvider get_chat_provider() returns; the round-loop shape
# (dispatch tool calls, stop immediately on a pending proposal, error out
# past MAX_TOOL_ROUNDS) is identical for every provider, so it lives here
# exactly once instead of once per provider as it used to.
# ---------------------------------------------------------------------------


def _stream_chat(history: list, ctx, ai_cfg):
    provider = get_chat_provider(ai_cfg)
    return _run_stream(history, ctx, provider)


def _tool_call_key(name: str, tool_input: dict) -> str:
    return f"{name}:{json.dumps(tool_input, sort_keys=True, default=str)}"


async def _run_stream(history: list, ctx, provider):
    system = provider.render_system(
        _build_system_prompt(ctx, prompt_fragment=provider.prompt_fragment())
    )
    tools = provider.render_tools(all_tools().values())
    # Reconstructs any tool calls/results from earlier turns into this
    # provider's native multi-turn shape, so the model still has them in
    # view even though they were made in a previous, separate HTTP request.
    messages = provider.parse_history(history)
    rounds = 0
    # Weaker models (small local/Ollama models especially) sometimes respond
    # to an error by blindly repeating the exact same call instead of fixing
    # it, burning every remaining round on an identical, deterministically-
    # failing dispatch. State can't change mid-turn (mutations only ever
    # happen via the user's separate approve-time REST call), so a repeat
    # call with byte-identical arguments would just return the same result
    # again -- short-circuit it with an explicit "stop repeating" signal
    # instead of re-dispatching.
    seen_calls: dict[str, str] = {}

    while rounds < MAX_TOOL_ROUNDS:
        round_end: RoundEnd | None = None
        async for event in provider.stream_round(
            system=system, tools=tools, messages=messages
        ):
            if isinstance(event, TextDelta):
                yield _sse({"type": "text_delta", "delta": event.text})
            elif isinstance(event, ErrorEvent):
                yield _sse({"type": "error", "message": event.message})
                return
            elif isinstance(event, RoundEnd):
                round_end = event

        assert round_end is not None
        if round_end.is_final:
            break

        rounds += 1
        results: list[tuple] = []
        proposal_pending = False

        for tc in round_end.tool_calls:
            yield _sse(
                {
                    "type": "tool_use_start",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.input,
                }
            )
            key = _tool_call_key(tc.name, tc.input)
            if key in seen_calls:
                result_str = json.dumps(
                    {
                        "status": "error",
                        "message": (
                            f"You already called {tc.name} with these exact same "
                            "arguments earlier in this conversation and got the same "
                            "result. Calling it again will not produce a different "
                            "outcome. Stop repeating this call -- either use different "
                            "arguments based on what you've already learned, or tell "
                            "the user you're unable to complete this."
                        ),
                    }
                )
            else:
                result_str = _dispatch_tool(tc.name, tc.input, ctx)
                seen_calls[key] = result_str
            yield _sse(
                {"type": "tool_result", "tool_use_id": tc.id, "content": result_str}
            )
            results.append((tc, result_str))
            if _is_proposal(result_str):
                proposal_pending = True

        provider.append_tool_results(messages, round_end, results)

        # A proposed change needs the user's approval in the UI. Stop streaming here
        # so the approval prompt is the last thing shown (chronological); the model
        # continues on the next turn once the change has been approved/applied.
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
