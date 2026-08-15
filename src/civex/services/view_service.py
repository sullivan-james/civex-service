from __future__ import annotations

from typing import Any

from civex.domain.dtos import ViewDTO
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.domain.filters import FilterGroup, FilterNode, parse_filter_tree
from civex.domain.naming import validate_name
from civex.repositories.protocols import AuditRepository, ViewRepository
from civex.services.schema_service import SchemaService

SORT_DIRECTIONS = frozenset({"asc", "desc"})


def _filter_tree_field_names(node: FilterNode) -> set[str]:
    if isinstance(node, FilterGroup):
        names: set[str] = set()
        for child in node.conditions:
            names |= _filter_tree_field_names(child)
        return names
    return {node.field}


class ViewService:
    def __init__(
        self,
        view_repo: ViewRepository,
        schema_svc: SchemaService,
        audit_repo: AuditRepository | None = None,
    ) -> None:
        self._views = view_repo
        self._schemas = schema_svc
        self._audit = audit_repo

    def _validate_columns(self, columns: list[str] | None, known: set[str]) -> list[str]:
        cols = list(columns or [])
        unknown = sorted(set(cols) - known)
        if unknown:
            raise ValidationError(f"Unknown column field(s) {unknown} for this schema")
        return cols

    def _validate_sort(
        self, sort: list[dict[str, Any]] | None, known: set[str]
    ) -> list[dict[str, Any]]:
        validated = []
        for entry in sort or []:
            if not isinstance(entry, dict) or "field" not in entry:
                raise ValidationError(
                    "Each sort entry must be an object with a 'field' key"
                )
            field_name = entry["field"]
            if field_name not in known:
                raise ValidationError(
                    f"Unknown sort field '{field_name}' for this schema"
                )
            direction = entry.get("direction", "asc")
            if direction not in SORT_DIRECTIONS:
                raise ValidationError(
                    f"Invalid sort direction '{direction}': must be 'asc' or 'desc'"
                )
            validated.append({"field": field_name, "direction": direction})
        return validated

    def _validate_filter_tree(
        self, filter_tree: dict[str, Any] | None, known: set[str]
    ) -> dict[str, Any] | None:
        if filter_tree is None:
            return None
        node = parse_filter_tree(filter_tree)
        unknown = sorted(_filter_tree_field_names(node) - known)
        if unknown:
            raise ValidationError(f"Unknown filter field(s) {unknown} for this schema")
        return filter_tree

    def create(
        self,
        schema_name: str,
        name: str,
        columns: list[str] | None = None,
        filter_tree: dict[str, Any] | None = None,
        sort: list[dict[str, Any]] | None = None,
    ) -> ViewDTO:
        schema = self._schemas.get(schema_name)
        validate_name(name, "view name")
        if self._views.get_by_name(schema.id, name):
            raise AlreadyExistsError(
                f"View '{name}' already exists on schema '{schema_name}'"
            )
        known = {rf.field.name for rf in self._schemas.collect_fields(schema)}
        dto = self._views.create(
            schema.id,
            name,
            self._validate_columns(columns, known),
            self._validate_filter_tree(filter_tree, known),
            self._validate_sort(sort, known),
        )
        if self._audit:
            self._audit.log_change("create", "view", dto.id, None, dto.to_dict())
        return dto

    def get(self, schema_name: str, view_name: str) -> ViewDTO:
        schema = self._schemas.get(schema_name)
        dto = self._views.get_by_name(schema.id, view_name)
        if dto is None:
            raise NotFoundError(
                f"View '{view_name}' not found on schema '{schema_name}'"
            )
        return dto

    def list_all(self, schema_name: str) -> list[ViewDTO]:
        schema = self._schemas.get(schema_name)
        return self._views.list_by_schema(schema.id)

    def update(
        self,
        schema_name: str,
        view_name: str,
        new_name: str | None = None,
        columns: list[str] | None = ...,
        filter_tree: dict[str, Any] | None = ...,
        sort: list[dict[str, Any]] | None = ...,
    ) -> ViewDTO:
        schema = self._schemas.get(schema_name)
        view = self._views.get_by_name(schema.id, view_name)
        if view is None:
            raise NotFoundError(
                f"View '{view_name}' not found on schema '{schema_name}'"
            )
        if new_name and new_name != view_name:
            validate_name(new_name, "view name")
            if self._views.get_by_name(schema.id, new_name):
                raise AlreadyExistsError(
                    f"View '{new_name}' already exists on schema '{schema_name}'"
                )
        known = {rf.field.name for rf in self._schemas.collect_fields(schema)}
        extra: dict[str, Any] = {}
        if columns is not ...:
            extra["columns"] = self._validate_columns(columns, known)
        if filter_tree is not ...:
            extra["filter_tree"] = self._validate_filter_tree(filter_tree, known)
        if sort is not ...:
            extra["sort"] = self._validate_sort(sort, known)
        old_dict = view.to_dict()
        updated = self._views.update(view.id, name=new_name, **extra)
        if self._audit:
            self._audit.log_change(
                "update", "view", updated.id, old_dict, updated.to_dict()
            )
        return updated

    def delete(self, schema_name: str, view_name: str) -> None:
        view = self.get(schema_name, view_name)
        if self._audit:
            self._audit.log_change("delete", "view", view.id, view.to_dict(), None)
        self._views.delete(view.id)
