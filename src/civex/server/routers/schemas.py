from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from civex.context import AppContext
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.server.deps import get_ctx
from civex.server.models import (
    AddFieldRequest,
    CreateSchemaRequest,
    FieldResponse,
    FieldTypesResponse,
    NameIssueResponse,
    PreviewNameRequest,
    PreviewNameResponse,
    ReorderFieldsRequest,
    RestorePlanResponse,
    SchemaDeleteImpactResponse,
    SchemaResponse,
    SetUniqueKeysRequest,
    UpdateFieldRequest,
    UpdateSchemaRequest,
)

router = APIRouter(prefix="/schemas", tags=["schemas"])


@router.get("", response_model=list[SchemaResponse])
def list_schemas(ctx: AppContext = Depends(get_ctx)):
    return [SchemaResponse.from_dto(s) for s in ctx.schema_svc.list_all()]


@router.get("/deleted", response_model=list[SchemaResponse])
def list_deleted_schemas(ctx: AppContext = Depends(get_ctx)):
    """Schemas currently in Recently Deleted, most recently deleted first."""
    return [SchemaResponse.from_dto(s) for s in ctx.schema_svc.list_deleted()]


@router.get("/lint", response_model=list[NameIssueResponse])
def lint_schema_names(ctx: AppContext = Depends(get_ctx)):
    """Schema and field names that predate slug validation -- the same
    report `civex schema lint` prints, exposed for the analytics
    naming-health widget. Nothing is broken; these names still resolve."""
    return [NameIssueResponse.from_dto(i) for i in ctx.schema_svc.lint_names()]


@router.get("/field-types", response_model=FieldTypesResponse)
def field_types():
    """Every field type, the rules each can carry and how to present them,
    plus the field-kind picker. The web UI builds its field editor and its
    record-form guidance from this, so a new type or rule appears there
    without a frontend change."""
    return FieldTypesResponse.build()


@router.post("/{name}/preview-name", response_model=PreviewNameResponse)
def preview_name(
    name: str, body: PreviewNameRequest, ctx: AppContext = Depends(get_ctx)
):
    """Render a name template against sample values without saving it. An
    invalid template is answered with `error` set, not an HTTP error, so an
    editor can show the problem as the person types."""
    try:
        rendered = ctx.schema_svc.preview_name(
            name, body.template, body.values, body.kind
        )
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        return PreviewNameResponse(name=None, error=str(e))
    return PreviewNameResponse(name=rendered)


@router.post("", response_model=SchemaResponse, status_code=201)
def create_schema(body: CreateSchemaRequest, ctx: AppContext = Depends(get_ctx)):
    fields = [f.model_dump() for f in body.fields] if body.fields else None
    try:
        dto = ctx.schema_svc.create_with_fields(
            body.name,
            description=body.description,
            parent=body.parent,
            fields=fields,
            label=body.label,
        )
    except AlreadyExistsError as e:
        raise HTTPException(409, detail=str(e))
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    except ValueError as e:
        raise HTTPException(422, detail=str(e))
    return SchemaResponse.from_dto(dto)


@router.get("/{name_or_id}", response_model=SchemaResponse)
def get_schema(name_or_id: str, ctx: AppContext = Depends(get_ctx)):
    try:
        uid = uuid.UUID(name_or_id)
        dto = ctx.schema_svc._repo.get_by_id(uid)
        if dto:
            return SchemaResponse.from_dto(dto)
    except ValueError:
        pass
    try:
        return SchemaResponse.from_dto(ctx.schema_svc.get(name_or_id))
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))


@router.patch("/{name}", response_model=SchemaResponse)
def update_schema(
    name: str, body: UpdateSchemaRequest, ctx: AppContext = Depends(get_ctx)
):
    display_template = (
        body.display_template if "display_template" in body.model_fields_set else ...
    )
    label = body.label if "label" in body.model_fields_set else ...
    try:
        dto = ctx.schema_svc.update(
            name,
            new_name=body.rename,
            description=body.description,
            display_template=display_template,
            label=label,
        )
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except AlreadyExistsError as e:
        raise HTTPException(409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return SchemaResponse.from_dto(dto)


@router.get("/{name}/delete-impact", response_model=SchemaDeleteImpactResponse)
def get_schema_delete_impact(name: str, ctx: AppContext = Depends(get_ctx)):
    """What deleting this schema would take with it, so the caller can warn
    before the delete happens rather than after it fails or silently loses data."""
    try:
        impact = ctx.schema_svc.get_delete_impact(name)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    return SchemaDeleteImpactResponse.from_dto(impact)


@router.delete("/{name}", status_code=204)
def delete_schema(name: str, ctx: AppContext = Depends(get_ctx)):
    try:
        ctx.schema_svc.delete(name)
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    ctx.commit()


@router.get("/{name}/restore-plan", response_model=RestorePlanResponse)
def restore_schema_plan(name: str, ctx: AppContext = Depends(get_ctx)):
    """What restoring a deleted schema would bring back: it and the records
    deleted with it, not records deleted on their own earlier."""
    try:
        return RestorePlanResponse.from_dto(ctx.schema_svc.restore_plan(name))
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))


@router.post("/{name}/restore", response_model=SchemaResponse)
def restore_schema(name: str, ctx: AppContext = Depends(get_ctx)):
    try:
        dto = ctx.schema_svc.restore(name)
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return SchemaResponse.from_dto(dto)


@router.delete("/{name}/purge", status_code=204)
def purge_schema(name: str, ctx: AppContext = Depends(get_ctx)):
    try:
        ctx.schema_svc.purge(name)
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))


@router.post("/{name}/fields", response_model=FieldResponse, status_code=201)
def add_field(name: str, body: AddFieldRequest, ctx: AppContext = Depends(get_ctx)):
    try:
        field = ctx.schema_svc.add_field(
            name,
            body.name,
            body.type,
            required=body.required,
            restrictions=body.restrictions,
            default_value=body.default,
            label=body.label,
        )
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except (AlreadyExistsError, ValidationError, ValueError) as e:
        raise HTTPException(422, detail=str(e))
    return FieldResponse.from_dto(field)


@router.delete("/{name}/fields/{field_name}", status_code=204)
def delete_field(name: str, field_name: str, ctx: AppContext = Depends(get_ctx)):
    try:
        ctx.schema_svc.delete_field(name, field_name)
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))


@router.get(
    "/{name}/fields/{field_id}/restore-plan", response_model=RestorePlanResponse
)
def restore_field_plan(
    name: str, field_id: uuid.UUID, ctx: AppContext = Depends(get_ctx)
):
    """What restoring a deleted field would do: it returns to the schema with
    the values records still hold for it. Blocked while the schema is deleted,
    or when a live field has since taken its name."""
    try:
        return RestorePlanResponse.from_dto(
            ctx.schema_svc.restore_field_plan(name, field_id)
        )
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))


@router.post("/{name}/fields/{field_id}/restore", response_model=FieldResponse)
def restore_field(name: str, field_id: uuid.UUID, ctx: AppContext = Depends(get_ctx)):
    """Bring a deleted field back, with every value records still hold for it."""
    try:
        dto = ctx.schema_svc.restore_field(name, field_id)
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return FieldResponse.from_dto(dto)


@router.patch("/{name}/fields/{field_name}", response_model=FieldResponse)
def update_field(
    name: str,
    field_name: str,
    body: UpdateFieldRequest,
    ctx: AppContext = Depends(get_ctx),
):
    if (
        body.rename is None
        and body.required is None
        and body.restrictions is None
        and "default" not in body.model_fields_set
        and "label" not in body.model_fields_set
    ):
        raise HTTPException(
            422,
            detail=(
                "Provide at least one of: rename, label, required, "
                "restrictions, default"
            ),
        )
    # Pass default_value/label only if explicitly included in the request —
    # an absent key means "leave unchanged", an explicit null means "clear".
    optional_kwargs: dict = {}
    if "default" in body.model_fields_set:
        optional_kwargs["default_value"] = body.default
    if "label" in body.model_fields_set:
        optional_kwargs["label"] = body.label
    try:
        field = ctx.schema_svc.update_field(
            name,
            field_name,
            new_name=body.rename,
            required=body.required,
            restrictions=body.restrictions,
            **optional_kwargs,
        )
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except AlreadyExistsError as e:
        raise HTTPException(409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return FieldResponse.from_dto(field)


@router.put("/{name}/unique-keys", response_model=SchemaResponse)
def set_unique_keys(
    name: str, body: SetUniqueKeysRequest, ctx: AppContext = Depends(get_ctx)
):
    """Replace a schema's uniqueness policies.

    Each key is a set of the schema's own fields that no two records may
    share the values of, within the same parent record (top-level records:
    the same collection). Refused with 422 when existing records already
    break a key being added. Records with a blank in a key's fields are not
    constrained by it.
    """
    try:
        dto = ctx.schema_svc.set_unique_keys(name, body.keys)
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    return SchemaResponse.from_dto(dto)


@router.put("/{name}/fields/reorder", response_model=SchemaResponse)
def reorder_fields(
    name: str, body: ReorderFieldsRequest, ctx: AppContext = Depends(get_ctx)
):
    try:
        ctx.schema_svc.reorder_fields(name, [uuid.UUID(i) for i in body.order])
        ctx.commit()
    except NotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(422, detail=str(e))
    schema = ctx.schema_svc.get(name)
    return SchemaResponse.from_dto(schema)
