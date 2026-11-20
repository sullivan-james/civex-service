"""Read-only tools: list/query schemas, collections, and records; summarise
records; describe a schema; fetch a job log. Each is thin -- a call to the
service methods the explorer, CLI and API use (`RecordQuery`,
`RecordService.summarise`) plus JSON shaping. A query the service refuses (a
bad filter, an unknown field) comes back as a `tool_error` the model can
correct from, not an exception."""

from __future__ import annotations

import json
from typing import Any

from civex.domain import summary
from civex.domain.exceptions import CivexError, NotFoundError, ValidationError
from civex.domain.field_descriptors import FIELD_TYPES
from civex.domain.query import RecordQuery
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


_FILTER_DESCRIPTION = (
    "Optional filter tree (a JSON object). A condition is "
    '{"field": "<field name>", "op": "<op>", "value": <value>}, with op one of '
    "eq, ne, gt, gte, lt, lte, contains, in (value is a list) or is_null (no "
    "value); dates and times are ISO strings. Combine with "
    '{"and": [...]} or {"or": [...]}, nested as deep as needed. A condition '
    'may add "schema": "<kind>" to test a field of a kind ABOVE the records '
    "(their parent, grandparent, ...) or BELOW them (true when any record "
    "beneath matches). Example, samples deeper than 5 m from sites in the "
    'north or with no region: {"and": [{"field": "depth", "op": "gt", '
    '"value": 5}, {"or": [{"field": "region", "schema": "site", "op": "eq", '
    '"value": "north"}, {"field": "region", "schema": "site", "op": '
    '"is_null"}]}]}. Field names are the keys describe_schema gives.'
)


def _filter_tree(raw: Any) -> dict | None:
    """The `filter` input as a tree: an object, or the same as JSON text
    (some models send it as a string)."""
    if raw in (None, "", {}):
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValidationError(f"'filter' is not valid JSON: {e}") from None
    if not isinstance(raw, dict):
        raise ValidationError("'filter' must be an object (a condition or a group)")
    return raw


def _record_query(tool_input: dict[str, Any], schema: str | None) -> RecordQuery:
    """The tool's inputs as the `RecordQuery` the explorer, the CLI and the
    API all list from."""
    search_field = tool_input.get("search_field")
    return RecordQuery(
        dataset=tool_input.get("collection") or None,
        schema=schema,
        within=tool_input.get("within") or None,
        filter_tree=_filter_tree(tool_input.get("filter")),
        search=tool_input.get("search") or None,
        search_fields=[search_field] if search_field else None,
        sort=tool_input.get("sort") or None,
    )


class QueryRecordsTool(AiTool):
    name = "query_records"
    description = (
        "Find and count records of one schema, in one collection or across "
        "all of them, narrowed by a filter tree, a text search and/or a record "
        "they sit beneath. Use count_only: true when only the number matters. "
        "Returns at most 20 records: for counts per group, averages, "
        "min/max or distributions use summarise_records instead."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "schema": {
                "type": "string",
                "description": "Schema name to query (required)",
            },
            "collection": {
                "type": "string",
                "description": "Optional: only this collection (omit for every "
                "collection)",
            },
            "filter": {"type": "object", "description": _FILTER_DESCRIPTION},
            "search": {
                "type": "string",
                "description": "Text to look for, ignoring case, in the records' "
                "field values (text, numbers, list items, file names)",
            },
            "search_field": {
                "type": "string",
                "description": "Optional: look for 'search' only in this field",
            },
            "within": {
                "type": "string",
                "description": "Optional: a record id (or its first 4+ "
                "characters); only records beneath it, at any depth",
            },
            "sort": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "direction": {"type": "string", "enum": ["asc", "desc"]},
                        "schema": {
                            "type": "string",
                            "description": "A kind above, for its field",
                        },
                    },
                    "required": ["field"],
                },
                "description": "Optional order, e.g. "
                '[{"field": "depth", "direction": "desc"}] for the deepest first',
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
        limit = min(max(int(tool_input.get("limit", 5)), 1), 20)
        count_only = bool(tool_input.get("count_only", False))
        try:
            query = _record_query(tool_input, tool_input["schema"])
            total = ctx.record_svc.count_records(query)
            if count_only:
                return {"total": str(total)}
            records = ctx.record_svc.query_records(query, limit=limit)
        except (CivexError, ValueError) as e:
            return tool_error(str(e))
        return {
            "total": str(total),
            "records": [
                {
                    **record_summary(r),
                    "name": r.natural_name,
                    "collection": r.dataset_name,
                }
                for r in records
            ],
        }


#: The most groups summarise_records hands the model.
MAX_SUMMARY_GROUPS = 50


class SummariseRecordsTool(AiTool):
    name = "summarise_records"
    description = (
        "Work out counts, averages, totals, min/max and distributions over "
        "records of one schema, worked out by the database over EVERY "
        "matching record, optionally per group (by a field's value, a date's "
        "year/month/week/day, a number in ranges, or a field of a kind above). "
        "Use it for any 'how many per', 'average', 'total', 'largest', "
        "'distribution' question; never compute these from listed records, "
        "which are only a sample. Call describe_schema first to see which "
        "measures and groupings each field allows."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "schema": {
                "type": "string",
                "description": "The kind of record to summarise (required)",
            },
            "collection": {
                "type": "string",
                "description": "Optional: only this collection (omit for every "
                "collection)",
            },
            "filter": {"type": "object", "description": _FILTER_DESCRIPTION},
            "search": {
                "type": "string",
                "description": "Optional: only records whose values contain this text",
            },
            "search_field": {
                "type": "string",
                "description": "Optional: look for 'search' only in this field",
            },
            "within": {
                "type": "string",
                "description": "Optional: only records beneath this record id",
            },
            "group_by": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Up to 3 groupings, each 'field', or "
                "'kind.field' for a field of a kind above (e.g. 'site.region'); "
                "add ':year', ':month', ':week' or ':day' for a date, or ':5' "
                "for a number in ranges 5 wide. Omit for one row over all records.",
            },
            "measures": {
                "type": "array",
                "items": {"type": "string"},
                "description": "What to work out: 'count' (records; the "
                "default), or 'filled', 'distinct', 'min', 'max', 'mean' or "
                "'sum' then ':field', e.g. ['count', 'mean:depth', "
                "'max:site.elevation'].",
            },
            "limit": {
                "type": "integer",
                "description": f"Most groups to return (1–{MAX_SUMMARY_GROUPS}). "
                "Default 20; 'truncated' says when there were more.",
                "default": 20,
            },
        },
        "required": ["schema"],
    }

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        limit = min(max(int(tool_input.get("limit", 20)), 1), MAX_SUMMARY_GROUPS)
        try:
            request = summary.SummaryRequest(
                group_by=[
                    summary.parse_group_by(g) for g in tool_input.get("group_by") or []
                ],
                measures=[
                    summary.parse_measure(m)
                    for m in tool_input.get("measures") or ["count"]
                ],
                limit=limit,
            )
            result = ctx.record_svc.summarise(
                _record_query(tool_input, tool_input["schema"]), request
            )
        except (CivexError, ValueError) as e:
            return tool_error(str(e))
        columns, rows = summary.table_of(result)
        cells = [[row[c] for c in columns] for row in rows]
        column_units = [c.unit for c in result.group_columns] + [
            m.unit for m in result.measure_columns
        ]
        units = {name: u for name, u in zip(columns, column_units) if u}
        out: dict[str, Any] = {
            "columns": columns,
            "rows": cells[:-1],
            "total": cells[-1],
            "truncated": result.truncated,
        }
        if units:
            out["units"] = units
        if result.timezone:
            out["timezone"] = result.timezone
        return out


class DescribeSchemaTool(AiTool):
    name = "describe_schema"
    description = (
        "Describe one schema for building filters and summaries: the kinds "
        "above and below it, and each field (its own and inherited) with its "
        "key, type, unit, choices, the measures summarise_records can work "
        "out over it and how it can be grouped."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "schema": {"type": "string", "description": "Schema name (required)"},
        },
        "required": ["schema"],
    }

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        try:
            schema = ctx.schema_svc.get(tool_input["schema"])
        except CivexError as e:
            return tool_error(str(e))
        fields = []
        for resolved in ctx.schema_svc.collect_fields(schema):
            f = resolved.field
            r = f.restrictions or {}
            d = FIELD_TYPES.get(f.dtype)
            entry: dict[str, Any] = {"name": f.name, "type": f.dtype}
            if f.display_name != f.name:
                entry["label"] = f.display_name
            if resolved.source_schema_name != schema.name:
                entry["from"] = resolved.source_schema_name
            for key, out_key in (
                ("unit", "unit"),
                ("choices", "choices"),
                ("schema", "links_to"),
                ("timezone", "timezone"),
            ):
                if r.get(key):
                    entry[out_key] = r[key]
            if d is not None:
                entry["measures"] = list(d.measures)
                if d.grouping == "bucket":
                    entry["group_by"] = ["value", *d.buckets]
                elif d.grouping == "bin":
                    entry["group_by"] = ["value", "ranges"]
                elif d.grouping:
                    entry["group_by"] = [
                        "each item" if d.grouping == "each" else "value"
                    ]
            fields.append(entry)
        out: dict[str, Any] = {"name": schema.name}
        if schema.display_name != schema.name:
            out["label"] = schema.display_name
        above = [a.name for a in ctx.schema_svc.ancestors(schema)]
        if above:
            out["inside"] = above  # nearest first
        below = [s.name for s in ctx.schema_svc.list_all() if s.parent_id == schema.id]
        if below:
            out["contains"] = below
        out["fields"] = fields
        return out


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
                "description": "Optional text to look for, ignoring case, in "
                "the records' field values",
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
        if collection not in {
            d.name for d in ctx.dataset_svc.list_all(with_count=False)
        }:
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
