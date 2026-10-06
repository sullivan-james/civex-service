from __future__ import annotations

from typing import Any

from civex.domain.dtos import RecordDTO, SchemaDTO, ViewDTO
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.domain.file_access import LAYOUTS, FileSelection
from civex.domain.naming import validate_free_name
from civex.domain.query import RecordQuery
from civex.domain.tables import DEFAULT_FORMAT, TableSpec
from civex.repositories.protocols import AuditRepository, ViewRepository
from civex.services.record_service import RecordService
from civex.services.schema_service import SchemaService

SORT_DIRECTIONS = frozenset({"asc", "desc"})


class ViewService:
    def __init__(
        self,
        view_repo: ViewRepository,
        schema_svc: SchemaService,
        record_svc: RecordService,
        audit_repo: AuditRepository | None = None,
    ) -> None:
        self._views = view_repo
        self._schemas = schema_svc
        self._record_svc = record_svc
        self._audit = audit_repo

    def _validate(
        self,
        schema: SchemaDTO,
        columns: list[str] | None = None,
        filter_tree: dict[str, Any] | None = None,
        sort: list[dict[str, Any]] | None = None,
    ) -> tuple[list[str], dict[str, Any] | None, list[dict[str, Any]]]:
        """Check a column/filter/sort selection the way a query would run it
        -- the record service owns those rules, so a view can never save
        something a list of the same schema would reject."""
        cols = list(columns or [])
        self._record_svc.validate_columns(schema, cols)
        self._record_svc.resolve(
            RecordQuery(schema=schema.name, filter_tree=filter_tree, sort=sort)
        )
        normalised = []
        for entry in sort or []:
            item = {"field": entry["field"], "direction": entry.get("direction", "asc")}
            if entry.get("schema"):
                item["schema"] = entry["schema"]
            normalised.append(item)
        return cols, filter_tree, normalised

    def create(
        self,
        schema_name: str,
        name: str,
        columns: list[str] | None = None,
        filter_tree: dict[str, Any] | None = None,
        sort: list[dict[str, Any]] | None = None,
        files_layout: str = "tree",
    ) -> ViewDTO:
        schema = self._schemas.get(schema_name)
        name = validate_free_name(name, "view name")
        _check_layout(files_layout)
        if self._views.get_by_name(schema.id, name):
            raise AlreadyExistsError(
                f"View '{name}' already exists on schema '{schema_name}'"
            )
        dto = self._views.create(
            schema.id,
            name,
            *self._validate(schema, columns, filter_tree, sort),
            files_layout=files_layout,
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

    def list_across_schemas(self) -> list[ViewDTO]:
        """Every saved view across every schema, for the top-level Views
        index -- unlike `list_all`, not scoped to one schema."""
        return self._views.list_all()

    def update(
        self,
        schema_name: str,
        view_name: str,
        new_name: str | None = None,
        columns=...,
        filter_tree=...,
        sort=...,
        files_layout=...,
    ) -> ViewDTO:
        schema = self._schemas.get(schema_name)
        view = self._views.get_by_name(schema.id, view_name)
        if view is None:
            raise NotFoundError(
                f"View '{view_name}' not found on schema '{schema_name}'"
            )
        if new_name:
            new_name = validate_free_name(new_name, "view name")
        if new_name and new_name != view_name:
            if self._views.get_by_name(schema.id, new_name):
                raise AlreadyExistsError(
                    f"View '{new_name}' already exists on schema '{schema_name}'"
                )
        extra: dict[str, Any] = {}
        if columns is not ...:
            extra["columns"] = self._validate(schema, columns=columns)[0]
        if filter_tree is not ...:
            extra["filter_tree"] = self._validate(schema, filter_tree=filter_tree)[1]
        if sort is not ...:
            extra["sort"] = self._validate(schema, sort=sort)[2]
        if files_layout is not ...:
            _check_layout(files_layout)
            extra["files_layout"] = files_layout
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

    def _rows(
        self, columns: list[str], records: list[RecordDTO]
    ) -> list[dict[str, Any]]:
        """Flatten `records` into rows keyed by `columns`: a column the
        record's own data holds comes from there, the rest (inherited
        fields, `ref_field.target_field` joins) from `derived`."""
        rows = []
        for record in records:
            derived = record.derived or {}
            rows.append(
                {c: derived[c] if c in derived else record.data.get(c) for c in columns}
            )
        return rows

    def query_for(self, schema_name: str, view_name: str) -> RecordQuery:
        """The saved view as the query it stands for."""
        view = self.get(schema_name, view_name)
        return RecordQuery(
            schema=schema_name, filter_tree=view.filter_tree, sort=view.sort or None
        )

    def preview(
        self,
        schema_name: str,
        columns: list[str] | None = None,
        filter_tree: dict[str, Any] | None = None,
        sort: list[dict[str, Any]] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Rows + total count for a (possibly unsaved) column/filter/sort
        selection -- the same query a saved view runs, paged in SQL so only
        the `limit` rows shown are ever materialised."""
        schema = self._schemas.get(schema_name)
        cols, tree, norm_sort = self._validate(schema, columns, filter_tree, sort)
        query = RecordQuery(
            schema=schema_name, filter_tree=tree, sort=norm_sort or None
        )
        records = self._record_svc.query_records(
            query, limit=limit, offset=offset, columns=cols
        )
        return self._rows(cols, records), self._record_svc.count_records(query)

    def _file_columns(self, schema: SchemaDTO, columns: list[str]) -> list[str]:
        """Base-schema (non-joined) columns whose field is file/file_list --
        the ones export bundles as a zip. Joined file columns aren't
        supported: join targets are read raw, bypassing the filename-template
        resolution that only runs for the view's own base-schema records."""
        fields_by_name = {
            rf.field.name: rf.field for rf in self._schemas.collect_fields(schema)
        }
        return [
            c
            for c in columns
            if "." not in c
            and (f := fields_by_name.get(c)) is not None
            and f.dtype in ("file", "file_list")
        ]

    def file_selection(self, schema_name: str, view_name: str) -> FileSelection | None:
        """The view's files as a selection (its query, its file columns, its
        saved layout), the one description the Files menu, the folder export
        and the zip all take. None when the view has no file columns."""
        view = self.get(schema_name, view_name)
        file_columns = self._file_columns(self._schemas.get(schema_name), view.columns)
        if not file_columns:
            return None
        return FileSelection(
            query=self.query_for(schema_name, view_name),
            fields=file_columns,
            layout=view.files_layout,
        )

    def table_selection(
        self, schema_name: str, view_name: str, fmt: str = DEFAULT_FORMAT
    ) -> FileSelection:
        """The view as a table to export (its columns, filter and sort), with its
        files beside it when it has file columns: the same selection the Files
        menu takes, so the table's file cells and the folder agree. Make it with
        `FileAccessService` like any other export."""
        view = self.get(schema_name, view_name)
        selection = self.file_selection(schema_name, view_name) or FileSelection(
            query=self.query_for(schema_name, view_name), files=False
        )
        selection.tables = [TableSpec(fmt, list(view.columns), name=view.name)]
        return selection


def _check_layout(layout: str) -> None:
    if layout not in LAYOUTS:
        raise ValidationError(f"A files layout is one of: {', '.join(LAYOUTS)}.")
