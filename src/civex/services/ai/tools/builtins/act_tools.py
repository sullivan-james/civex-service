"""The 12 mutating 'act' tools. These NEVER execute on their own -- each
validates via validate_via() (a rolled-back SAVEPOINT against the real
service, CIVEX-49) and returns a "proposed" REST request. The frontend
executes that request verbatim only after the user clicks Approve, so the
model can never mutate data on its own and can never control an arbitrary
URL. Existence/duplicate pre-checks that give the model actionable retry
guidance (e.g. "already exists -- use add_schema_field instead") are kept as
fast-fail checks ahead of the real call, not replaced by it.
"""

from __future__ import annotations

from typing import Any

from civex.services.ai.tools._shared import (
    propose,
    q,
    record_or_none,
    tool_error,
    validate_via,
)
from civex.services.ai.tools.base import AiTool, AiToolContext
from civex.services.schema_service import VALID_DTYPES

_FIELD_TYPE_DESCRIPTION = (
    "Exactly one of these values, verbatim — no brackets, no generics, no "
    "combining two types into one string. For a link to another schema use "
    "'reference' or 'reference_list', not 'string'."
)


class CreateRecordTool(AiTool):
    name = "create_record"
    description = "Propose creating a new record in a collection. Requires user approval in the UI before it is saved."
    mutating = True
    input_schema = {
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
    }

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        collection, schema = tool_input["collection"], tool_input["schema"]
        data = tool_input.get("data") or {}
        collection_names = {d.name for d in ctx.dataset_svc.list_all()}
        schema_names = {s.name for s in ctx.schema_svc.list_all()}
        if collection not in collection_names:
            return tool_error(f"Collection '{collection}' does not exist.")
        if schema not in schema_names:
            return tool_error(f"Schema '{schema}' does not exist.")
        err = validate_via(ctx, ctx.record_svc.add, collection, schema, data)
        if err:
            return err
        return propose(
            "create_record",
            f"Create a new '{schema}' record in collection '{collection}'.",
            "POST",
            f"/api/collections/{q(collection)}/records",
            body={"schema_name": schema, "data": data},
            preview={"collection": collection, "schema": schema, "data": data},
        )


class UpdateRecordTool(AiTool):
    name = "update_record"
    description = "Propose updating fields on an existing record. Requires user approval in the UI."
    mutating = True
    input_schema = {
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
    }

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        rid = tool_input["record_id"]
        data = tool_input.get("data") or {}
        rec = record_or_none(ctx, rid)
        if rec is None:
            return tool_error(f"Record '{rid}' not found.")
        if not data:
            return tool_error("No fields provided to update.")
        err = validate_via(ctx, ctx.record_svc.update, str(rec.id), data)
        if err:
            return err
        return propose(
            "update_record",
            f"Update record {str(rec.id)[:8]} ({rec.schema_name}) — set {', '.join(data.keys())}.",
            "PATCH",
            f"/api/records/{q(rec.id)}",
            body={"data": data},
            preview={"record_id": str(rec.id), "schema": rec.schema_name, "data": data},
        )


class DeleteRecordTool(AiTool):
    name = "delete_record"
    description = (
        "Propose deleting a record. Destructive — requires user approval in the UI."
    )
    mutating = True
    input_schema = {
        "type": "object",
        "properties": {
            "record_id": {
                "type": "string",
                "description": "UUID of the record to delete",
            }
        },
        "required": ["record_id"],
    }

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        rid = tool_input["record_id"]
        rec = record_or_none(ctx, rid)
        if rec is None:
            return tool_error(f"Record '{rid}' not found.")
        return propose(
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


class CreateSchemaTool(AiTool):
    name = "create_schema"
    description = (
        "Propose creating a new schema, optionally with all of its fields, in a single proposal. "
        "Requires one user approval in the UI. "
        "ALWAYS pass 'fields' here when the schema needs more than one field — this creates the schema "
        "and every field as one approval instead of forcing the user to click Approve once per field via "
        "add_schema_field. Only use add_schema_field afterward for fields added to an already-existing schema."
    )
    mutating = True
    input_schema = {
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
                            "description": _FIELD_TYPE_DESCRIPTION,
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
    }

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        name = tool_input["name"]
        parent = tool_input.get("parent")
        fields = tool_input.get("fields") or []
        schema_names = {s.name for s in ctx.schema_svc.list_all()}
        if name in schema_names:
            return tool_error(
                f"Schema '{name}' already exists — do not retry create_schema for it. "
                "If it's missing fields, call add_schema_field for each one instead; "
                "to change an existing field, use update_schema_field."
            )
        if parent and parent not in schema_names:
            return tool_error(f"Parent schema '{parent}' does not exist.")
        for f in fields:
            if not f.get("name") or not f.get("type"):
                return tool_error("Each field needs a 'name' and 'type'.")
        err = validate_via(
            ctx,
            ctx.schema_svc.create_with_fields,
            name,
            tool_input.get("description"),
            parent,
            fields,
        )
        if err:
            return err
        body: dict[str, Any] = {"name": name}
        if tool_input.get("description"):
            body["description"] = tool_input["description"]
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
        return propose(
            "create_schema",
            f"Create schema '{name}'{extra}{field_note}.",
            "POST",
            "/api/schemas",
            body=body,
            preview=body,
        )


class UpdateSchemaTool(AiTool):
    name = "update_schema"
    description = "Propose renaming a schema, changing its description, or setting its display field. Requires user approval."
    mutating = True
    input_schema = {
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
    }

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        name = tool_input["name"]
        schema_names = {s.name for s in ctx.schema_svc.list_all()}
        if name not in schema_names:
            return tool_error(f"Schema '{name}' does not exist.")
        body = {
            k: tool_input[k]
            for k in ("rename", "description", "display_field")
            if tool_input.get(k) is not None
        }
        if not body:
            return tool_error(
                "Nothing to change (provide rename, description, or display_field)."
            )
        update_kwargs: dict[str, Any] = {}
        if "rename" in body:
            update_kwargs["new_name"] = body["rename"]
        if "description" in body:
            update_kwargs["description"] = body["description"]
        if "display_field" in body:
            update_kwargs["display_field"] = body["display_field"]
        err = validate_via(ctx, ctx.schema_svc.update, name, **update_kwargs)
        if err:
            return err
        summary = (
            f"Rename schema '{name}' to '{body['rename']}'."
            if "rename" in body
            else f"Update schema '{name}'."
        )
        return propose(
            "update_schema",
            summary,
            "PATCH",
            f"/api/schemas/{q(name)}",
            body=body,
            preview={"name": name, **body},
        )


class DeleteSchemaTool(AiTool):
    name = "delete_schema"
    description = (
        "Propose deleting a schema. Destructive — requires user approval in the UI."
    )
    mutating = True
    input_schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        name = tool_input["name"]
        schema_names = {s.name for s in ctx.schema_svc.list_all()}
        if name not in schema_names:
            return tool_error(f"Schema '{name}' does not exist.")
        err = validate_via(ctx, ctx.schema_svc.delete, name)
        if err:
            return err
        return propose(
            "delete_schema",
            f"Delete schema '{name}'. This cannot be undone.",
            "DELETE",
            f"/api/schemas/{q(name)}",
            destructive=True,
            preview={"name": name},
        )


class AddSchemaFieldTool(AiTool):
    name = "add_schema_field"
    description = (
        "Propose adding a field to an existing schema. Requires user approval."
    )
    mutating = True
    input_schema = {
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
                "description": _FIELD_TYPE_DESCRIPTION,
            },
            "required": {"type": "boolean", "default": False},
            "restrictions": {
                "type": "object",
                "description": "Optional restriction map (min/max, choices, accept, schema, ...)",
            },
            "default": {"description": "Optional default value"},
        },
        "required": ["schema", "name", "type"],
    }

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        schema, fname, ftype = (
            tool_input["schema"],
            tool_input["name"],
            tool_input["type"],
        )
        schema_names = {s.name for s in ctx.schema_svc.list_all()}
        if schema not in schema_names:
            return tool_error(f"Schema '{schema}' does not exist.")
        err = validate_via(
            ctx,
            ctx.schema_svc.add_field,
            schema,
            fname,
            ftype,
            required=bool(tool_input.get("required", False)),
            restrictions=tool_input.get("restrictions"),
            default_value=tool_input.get("default"),
        )
        if err:
            return err
        body = {
            "name": fname,
            "type": ftype,
            "required": bool(tool_input.get("required", False)),
        }
        if tool_input.get("restrictions"):
            body["restrictions"] = tool_input["restrictions"]
        if tool_input.get("default") is not None:
            body["default"] = tool_input["default"]
        return propose(
            "add_schema_field",
            f"Add field '{fname}' ({ftype}) to schema '{schema}'.",
            "POST",
            f"/api/schemas/{q(schema)}/fields",
            body=body,
            preview={"schema": schema, **body},
        )


class UpdateSchemaFieldTool(AiTool):
    name = "update_schema_field"
    description = "Propose changing a field on a schema (rename, required, restrictions, default). Requires user approval."
    mutating = True
    input_schema = {
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
    }

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        schema, field = tool_input["schema"], tool_input["field"]
        schema_names = {s.name for s in ctx.schema_svc.list_all()}
        if schema not in schema_names:
            return tool_error(f"Schema '{schema}' does not exist.")
        body = {
            k: tool_input[k]
            for k in ("rename", "required", "restrictions", "default")
            if tool_input.get(k) is not None
        }
        if not body:
            return tool_error("Nothing to change on the field.")
        update_field_kwargs: dict[str, Any] = {}
        if "rename" in body:
            update_field_kwargs["new_name"] = body["rename"]
        if "required" in body:
            update_field_kwargs["required"] = body["required"]
        if "restrictions" in body:
            update_field_kwargs["restrictions"] = body["restrictions"]
        if "default" in body:
            update_field_kwargs["default_value"] = body["default"]
        err = validate_via(
            ctx, ctx.schema_svc.update_field, schema, field, **update_field_kwargs
        )
        if err:
            return err
        summary = (
            f"Rename field '{field}' to '{body['rename']}' on schema '{schema}'."
            if "rename" in body
            else f"Update field '{field}' on schema '{schema}'."
        )
        return propose(
            "update_schema_field",
            summary,
            "PATCH",
            f"/api/schemas/{q(schema)}/fields/{q(field)}",
            body=body,
            preview={"schema": schema, "field": field, **body},
        )


class DeleteSchemaFieldTool(AiTool):
    name = "delete_schema_field"
    description = "Propose removing a field from a schema. Destructive — requires user approval in the UI."
    mutating = True
    input_schema = {
        "type": "object",
        "properties": {"schema": {"type": "string"}, "field": {"type": "string"}},
        "required": ["schema", "field"],
    }

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        schema, field = tool_input["schema"], tool_input["field"]
        schema_names = {s.name for s in ctx.schema_svc.list_all()}
        if schema not in schema_names:
            return tool_error(f"Schema '{schema}' does not exist.")
        err = validate_via(ctx, ctx.schema_svc.delete_field, schema, field)
        if err:
            return err
        return propose(
            "delete_schema_field",
            f"Remove field '{field}' from schema '{schema}'. This cannot be undone.",
            "DELETE",
            f"/api/schemas/{q(schema)}/fields/{q(field)}",
            destructive=True,
            preview={"schema": schema, "field": field},
        )


class CreateCollectionTool(AiTool):
    name = "create_collection"
    description = "Propose creating a new collection. Requires user approval in the UI."
    mutating = True
    input_schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "description": {"type": "string"}},
        "required": ["name"],
    }

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        name = tool_input["name"]
        collection_names = {d.name for d in ctx.dataset_svc.list_all()}
        if name in collection_names:
            return tool_error(
                f"Collection '{name}' already exists — do not retry create_collection for it. "
                "To change it, use update_collection instead."
            )
        err = validate_via(
            ctx, ctx.dataset_svc.create, name, tool_input.get("description")
        )
        if err:
            return err
        body = {"name": name}
        if tool_input.get("description"):
            body["description"] = tool_input["description"]
        return propose(
            "create_collection",
            f"Create collection '{name}'.",
            "POST",
            "/api/collections",
            body=body,
            preview=body,
        )


class UpdateCollectionTool(AiTool):
    name = "update_collection"
    description = "Propose renaming a collection or changing its description. Requires user approval."
    mutating = True
    input_schema = {
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
    }

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        name = tool_input["name"]
        collection_names = {d.name for d in ctx.dataset_svc.list_all()}
        if name not in collection_names:
            return tool_error(f"Collection '{name}' does not exist.")
        body = {
            k: tool_input[k]
            for k in ("rename", "description")
            if tool_input.get(k) is not None
        }
        if not body:
            return tool_error("Nothing to change (provide rename or description).")
        err = validate_via(
            ctx,
            ctx.dataset_svc.update,
            name,
            new_name=body.get("rename"),
            description=body.get("description"),
        )
        if err:
            return err
        summary = (
            f"Rename collection '{name}' to '{body['rename']}'."
            if "rename" in body
            else f"Update collection '{name}'."
        )
        return propose(
            "update_collection",
            summary,
            "PATCH",
            f"/api/collections/{q(name)}",
            body=body,
            preview={"name": name, **body},
        )


class DeleteCollectionTool(AiTool):
    name = "delete_collection"
    description = (
        "Propose deleting a collection. Destructive — requires user approval in the UI."
    )
    mutating = True
    input_schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    def run(self, tool_input: dict, ctx: AiToolContext) -> Any:
        name = tool_input["name"]
        collection_names = {d.name for d in ctx.dataset_svc.list_all()}
        if name not in collection_names:
            return tool_error(f"Collection '{name}' does not exist.")
        err = validate_via(ctx, ctx.dataset_svc.delete, name)
        if err:
            return err
        return propose(
            "delete_collection",
            f"Delete collection '{name}' and its records. This cannot be undone.",
            "DELETE",
            f"/api/collections/{q(name)}",
            destructive=True,
            preview={"name": name},
        )
