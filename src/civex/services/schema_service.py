from __future__ import annotations

import uuid
from typing import Any

from civex.domain.dtos import FieldDTO, ResolvedField, SchemaDTO
from civex.domain.exceptions import AlreadyExistsError, NotFoundError
from civex.repositories.protocols import SchemaRepository

VALID_DTYPES = frozenset(["integer", "float", "string", "boolean", "file"])


class SchemaService:
    def __init__(self, repo: SchemaRepository) -> None:
        self._repo = repo

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

        return self._repo.create(name=name, description=description, parent_id=parent_id)

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
    ) -> FieldDTO:
        if dtype not in VALID_DTYPES:
            raise ValueError(f"Unknown dtype '{dtype}'. Choose from: {', '.join(sorted(VALID_DTYPES))}")

        schema = self.get(schema_name)

        if any(f.name == field_name for f in schema.fields):
            raise AlreadyExistsError(f"Field '{field_name}' already exists on schema '{schema_name}'")

        return self._repo.add_field(
            schema_id=schema.id,
            name=field_name,
            dtype=dtype,
            required=required,
            restrictions=restrictions or {},
        )

    def delete(self, name: str) -> None:
        schema = self.get(name)
        self._repo.delete(schema.id)

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
