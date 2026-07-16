from __future__ import annotations

import uuid
from typing import Any

from civex.domain.dtos import FieldDTO, ResolvedField, SchemaDTO
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.repositories.protocols import AuditRepository, SchemaRepository

VALID_DTYPES = frozenset([
    "integer", "float", "string", "boolean",
    "file", "file_list", "reference", "date", "datetime",
    "enum", "url", "reference_list", "tags",
])

# Valid `restrictions` keys per dtype — the single source of truth for what
# RecordService._check_restrictions() actually reads. Anything else is
# silently ignored at write time, which would let a field look restricted
# in the UI while enforcing nothing — so we reject unknown keys up front.
VALID_RESTRICTION_KEYS: dict[str, frozenset[str]] = {
    "integer": frozenset({"min", "max"}),
    "float": frozenset({"min", "max"}),
    "string": frozenset({"choices", "max_length"}),
    "date": frozenset({"min", "max"}),
    "datetime": frozenset({"min", "max"}),
    "file": frozenset({"accept", "max_size"}),
    "file_list": frozenset({"accept", "max_size"}),
    "reference": frozenset({"schema"}),
    "reference_list": frozenset({"schema"}),
    "enum": frozenset({"choices"}),
    "boolean": frozenset(),
    "url": frozenset(),
    "tags": frozenset(),
}


def _validate_restriction_keys(dtype: str, restrictions: dict[str, Any] | None) -> None:
    if not restrictions:
        return
    allowed = VALID_RESTRICTION_KEYS.get(dtype, frozenset())
    unknown = sorted(set(restrictions) - allowed)
    if unknown:
        valid = ", ".join(sorted(allowed)) if allowed else "(none)"
        raise ValidationError(
            f"Unknown restriction key(s) {unknown} for type '{dtype}'. Valid keys: {valid}"
        )


class SchemaService:
    def __init__(self, repo: SchemaRepository, audit_repo: AuditRepository | None = None) -> None:
        self._repo = repo
        self._audit = audit_repo

    def create(
        self,
        name: str,
        description: str | None = None,
        parent: str | None = None,
    ) -> SchemaDTO:
        if self._repo.get_by_name(name):
            raise AlreadyExistsError(f"Schema '{name}' already exists")

        parent_id: uuid.UUID | None = None
        if parent:
            parent_dto = self._repo.get_by_name(parent)
            if not parent_dto:
                raise NotFoundError(f"Parent schema '{parent}' not found")
            parent_id = parent_dto.id

        dto = self._repo.create(name=name, description=description, parent_id=parent_id)
        if self._audit:
            self._audit.log_change("create", "schema", dto.id, None, dto.to_dict())
        return dto

    def create_with_fields(
        self,
        name: str,
        description: str | None = None,
        parent: str | None = None,
        fields: list[dict[str, Any]] | None = None,
    ) -> SchemaDTO:
        """Create a schema and all of its fields as one unit.

        Lets a single caller (e.g. the AI assistant's create_schema tool) produce
        one proposal/approval instead of one per field.
        """
        self.create(name, description=description, parent=parent)
        for f in fields or []:
            self.add_field(
                name,
                f["name"],
                f["type"],
                required=f.get("required", False),
                restrictions=f.get("restrictions"),
                default_value=f.get("default"),
            )
        return self.get(name)

    def get(self, name: str) -> SchemaDTO:
        dto = self._repo.get_by_name(name)
        if not dto:
            raise NotFoundError(f"Schema '{name}' not found")
        return dto

    def list_all(self) -> list[SchemaDTO]:
        return self._repo.list_all()

    def add_field(
        self,
        schema_name: str,
        field_name: str,
        dtype: str,
        required: bool = False,
        restrictions: dict[str, Any] | None = None,
        default_value: Any = None,
    ) -> FieldDTO:
        if dtype not in VALID_DTYPES:
            raise ValueError(f"Unknown dtype '{dtype}'. Choose from: {', '.join(sorted(VALID_DTYPES))}")
        _validate_restriction_keys(dtype, restrictions)

        schema = self.get(schema_name)

        if any(f.name == field_name for f in schema.fields):
            raise AlreadyExistsError(f"Field '{field_name}' already exists on schema '{schema_name}'")

        field = self._repo.add_field(
            schema_id=schema.id,
            name=field_name,
            dtype=dtype,
            required=required,
            restrictions=restrictions or {},
            default_value=default_value,
        )
        if self._audit:
            self._audit.log_change("create", "field", field.id, None, field.to_dict())
        return field

    def update(
        self,
        name: str,
        new_name: str | None = None,
        description: str | None = None,
        display_field=...,
    ) -> SchemaDTO:
        schema = self.get(name)
        if new_name and new_name != name:
            if self._repo.get_by_name(new_name):
                raise AlreadyExistsError(f"Schema '{new_name}' already exists")
        if display_field is not ... and display_field is not None:
            all_fields = self.collect_fields(schema)
            names = {rf.field.name for rf in all_fields}
            if display_field not in names:
                raise NotFoundError(f"Field '{display_field}' not found on schema '{name}'")
        old_dict = schema.to_dict()
        extra = {} if display_field is ... else {"display_field": display_field}
        updated = self._repo.update(schema.id, name=new_name, description=description, **extra)
        if self._audit:
            self._audit.log_change("update", "schema", updated.id, old_dict, updated.to_dict())
        return updated

    def delete_field(self, schema_name: str, field_name: str) -> None:
        schema = self.get(schema_name)
        field = next((f for f in schema.fields if f.name == field_name), None)
        if field is None:
            raise NotFoundError(f"Field '{field_name}' not found on schema '{schema_name}'")
        if self._audit:
            self._audit.log_change("delete", "field", field.id, field.to_dict(), None)
        self._repo.delete_field(field.id)

    def update_field(
        self,
        schema_name: str,
        field_name: str,
        *,
        new_name: str | None = None,
        required: bool | None = None,
        restrictions: dict | None = None,
        default_value: Any = ...,
    ) -> FieldDTO:
        schema = self.get(schema_name)
        field = next((f for f in schema.fields if f.name == field_name), None)
        if field is None:
            raise NotFoundError(f"Field '{field_name}' not found on schema '{schema_name}'")
        if new_name and new_name != field_name:
            if any(f.name == new_name for f in schema.fields):
                raise AlreadyExistsError(f"Field '{new_name}' already exists on schema '{schema_name}'")
        if restrictions is not None:
            _validate_restriction_keys(field.dtype, restrictions)
        old_dict = field.to_dict()
        kwargs: dict[str, Any] = dict(name=new_name, required=required, restrictions=restrictions)
        if default_value is not ...:
            kwargs["default_value"] = default_value
        updated = self._repo.update_field(field.id, **kwargs)
        if self._audit:
            self._audit.log_change("update", "field", updated.id, old_dict, updated.to_dict())
        return updated

    def reorder_fields(self, schema_name: str, field_ids: list[uuid.UUID]) -> list[FieldDTO]:
        schema = self.get(schema_name)
        own_field_ids = {f.id for f in schema.fields}
        invalid = [fid for fid in field_ids if fid not in own_field_ids]
        if invalid:
            raise ValidationError(
                f"Field IDs not found on schema '{schema_name}': "
                + ", ".join(str(i) for i in invalid)
            )
        return self._repo.reorder_fields(schema.id, field_ids)

    def delete(self, name: str) -> None:
        schema = self.get(name)
        if self._audit:
            self._audit.log_change("delete", "schema", schema.id, schema.to_dict(), None)
        self._repo.delete(schema.id)

    def name_to_id_map(self, schema: SchemaDTO) -> dict[str, str]:
        """field name → str(field.id), including inherited fields."""
        return {rf.field.name: str(rf.field.id) for rf in self.collect_fields(schema)}

    def id_to_name_map(self, schema: SchemaDTO) -> dict[str, str]:
        """str(field.id) → field name, including inherited fields."""
        return {str(rf.field.id): rf.field.name for rf in self.collect_fields(schema)}

    def collect_fields(self, schema: SchemaDTO) -> list[ResolvedField]:
        """
        Return all fields for a schema, including inherited ones.
        Own fields come first; parent fields follow (depth-first).
        Own fields shadow parent fields with the same name.
        """
        own = [ResolvedField(field=f, source_schema_name=schema.name) for f in schema.fields]
        seen_names = {f.field.name for f in own}

        inherited: list[ResolvedField] = []
        if schema.parent_id:
            parent = self._repo.get_by_id(schema.parent_id)
            if parent:
                for resolved in self.collect_fields(parent):
                    if resolved.field.name not in seen_names:
                        inherited.append(resolved)
                        seen_names.add(resolved.field.name)

        return own + inherited
