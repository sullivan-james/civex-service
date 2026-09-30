"""Read-only tools: list/query schemas, collections, and records; fetch a
job log. Each is already thin -- a straight call to one service method plus
JSON shaping, no validation logic to route through validate_via()."""

from __future__ import annotations

from typing import Any

from civex.domain.exceptions import NotFoundError
from civex.services.ai.tools._shared import record_summary, tool_error
from civex.services.ai.tools.base import AiTool, AiToolContext


class ListSchemasTool(AiTool):
    name = "list_schemas"
    description = "List all schemas in the project with their field names, types, and restrictions."
    input_schema = {"type": "object", "properties": {}}

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        schema_results = []
        for s in ctx.schema_svc.list_all():
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
            schema_results.append({"name": s.name, "fields": fields})
        return schema_results


class ListCollectionsTool(AiTool):
    name = "list_collections"
    description = "List all collections (datasets) with their record counts."
    input_schema = {"type": "object", "properties": {}}

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        return [
            {"name": d.name, "record_count": d.record_count}
            for d in ctx.dataset_svc.list_all()
        ]


class QueryRecordsTool(AiTool):
    name = "query_records"
    description = "Search and count records of a given schema across all collections. Use count_only: true first for aggregate questions."
    input_schema = {
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
    }

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        schema = tool_input["schema"]
        search = tool_input.get("search")
        limit = min(int(tool_input.get("limit", 5)), 20)
        count_only = bool(tool_input.get("count_only", False))

        total = ctx.record_svc.count_by_schema_search(schema, search=search)

        if count_only:
            return {"total": str(total)}

        records = ctx.record_svc.find_by_schema(schema, search=search, limit=limit)
        return {"total": str(total), "records": [record_summary(r) for r in records]}


class ListRecordsTool(AiTool):
    name = "list_records"
    description = (
        "List or search records within a collection. Returns each record's id, schema, and field data. "
        "Use this to find records — e.g. to get the UUID needed for update_record or delete_record, or to browse a "
        "collection. For counting or searching across all collections of one schema, use query_records instead."
    )
    input_schema = {
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
    }

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        collection = tool_input["collection"]
        if collection not in {d.name for d in ctx.dataset_svc.list_all()}:
            return tool_error(f"Collection '{collection}' does not exist.")
        schema = tool_input.get("schema") or None
        search = tool_input.get("search") or None
        filters = tool_input.get("filters") or None
        # Exact-field filters resolve field names via the schema (records are
        # stored keyed by field id), so a schema is required to use them.
        if filters and not schema:
            return tool_error(
                "To filter by a specific field, also pass 'schema'. "
                "Otherwise use 'search' for a free-text match across all fields."
            )
        limit = min(max(int(tool_input.get("limit", 10)), 1), 25)
        total = ctx.record_svc.count(
            collection, schema_name=schema, filters=filters, search=search
        )
        records = ctx.record_svc.find(
            collection, schema_name=schema, filters=filters, search=search, limit=limit
        )
        return {"total": total, "records": [record_summary(r) for r in records]}


class GetJobLogTool(AiTool):
    name = "get_job_log"
    description = (
        "Get the status, error message, and execution log of a workflow job by ID."
    )
    input_schema = {
        "type": "object",
        "properties": {"job_id": {"type": "string", "description": "UUID of the job"}},
        "required": ["job_id"],
    }

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        import uuid

        try:
            job = ctx.job_svc.get_job(uuid.UUID(tool_input["job_id"]))
        except (NotFoundError, ValueError):
            return {"error": "job not found"}
        if job is None:
            return {"error": "job not found"}
        return {"status": job.status, "error": job.error, "log": job.log}
