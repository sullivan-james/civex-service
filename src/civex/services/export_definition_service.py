"""Exports saved with a schema: the kind of record that holds the files, which
file fields, a filter, a layout.

An export is part of how a schema is set up, like its fields and its naming; it is
*run* from a collection or a record. So a definition says nothing about which
collection or record: `selection()` turns it into the `FileSelection` for one
run. It is offered on records of its own schema and of the schemas below it, as
far down as the kind that holds the files, and on collections that use its
schema.
"""

from __future__ import annotations

from typing import Any

from civex.domain.dtos import ExportDefinitionDTO, SchemaDTO
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.domain.file_access import LAYOUTS, FileSelection
from civex.domain.naming import validate_free_name
from civex.domain import templating
from civex.domain.query import RecordQuery
from civex.domain.tables import META_COLUMNS, TableSpec
from civex.repositories.protocols import ExportDefinitionRepository
from civex.services.record_service import RecordService
from civex.services.schema_service import SchemaService

_FILE_DTYPES = ("file", "file_list")


class ExportDefinitionService:
    def __init__(
        self,
        repo: ExportDefinitionRepository,
        schema_svc: SchemaService,
        record_svc: RecordService,
    ) -> None:
        self._repo = repo
        self._schemas = schema_svc
        self._records = record_svc

    # -- the rules --------------------------------------------------------------

    def _scope(self, schema: SchemaDTO) -> list[SchemaDTO]:
        """The schema and every schema beneath it."""
        return [schema, *(d for d, _ in self._schemas.descendants(schema))]

    def _file_fields(self, schema: SchemaDTO) -> list[str]:
        """The file fields records of `schema` carry, own and inherited."""
        return [
            rf.field.name
            for rf in self._schemas.collect_fields(schema)
            if rf.field.dtype in _FILE_DTYPES
        ]

    def _check(
        self,
        schema: SchemaDTO,
        holder: str | None,
        fields: list[str],
        filter_tree: dict[str, Any] | None,
        layout: str,
        include_files: bool = True,
        tables: list[dict[str, Any]] | None = None,
    ) -> SchemaDTO | None:
        """Everything a definition has to satisfy at once, or a ValidationError
        saying which part doesn't. Returns the holder's schema (None for "any
        kind beneath")."""
        if layout not in LAYOUTS:
            raise ValidationError(f"A files layout is one of: {', '.join(LAYOUTS)}.")
        if not include_files and not tables:
            raise ValidationError("An export takes files, tables, or both.")
        if not include_files and fields:
            raise ValidationError("File fields only apply when files are exported.")
        specs = TableSpec.from_list(tables)  # checks each one's own rules
        scope = self._scope(schema)
        holder_schema: SchemaDTO | None = None
        if holder:
            if holder not in {s.name for s in scope}:
                raise ValidationError(
                    f"'{holder}' isn't '{schema.name}' or a kind beneath it, so "
                    f"records of '{schema.name}' can't hold files of that kind."
                )
            holder_schema = self._schemas.get(holder)
            available = self._file_fields(holder_schema)
            where = f"records of '{holder}'"
        else:
            available = list(
                dict.fromkeys(f for s in scope for f in self._own_file_fields(s))
            )
            where = f"'{schema.name}' or the kinds beneath it"
        for spec in specs:
            self._check_table(spec, schema, holder_schema, where, layout)
        if not include_files:
            available = []
        elif not available:
            raise ValidationError(f"Nothing in {where} can hold a file.")
        for name in fields:
            if name not in available:
                raise ValidationError(
                    f"'{name}' isn't a file field of {where}"
                    f" (they have: {', '.join(available)})."
                )
        if filter_tree is not None:
            if holder_schema is None:
                raise ValidationError(
                    "A filter tests one kind of record: choose which kind holds "
                    "the files first."
                )
            # The same check a list of those records applies to the filter.
            self._records.resolve(
                RecordQuery(schema=holder_schema.name, filter_tree=filter_tree)
            )
        return holder_schema

    def _check_table(
        self,
        spec: TableSpec,
        schema: SchemaDTO,
        holder_schema: SchemaDTO | None,
        where: str,
        layout: str,
    ) -> None:
        """One table against the schemas it names: the kind of its rows and the
        kind whose folder it goes in must be in this export's tree (the schema,
        what is beneath it, or what is above it), a folder's record is the
        row's own or an ancestor of it, its columns are fields of the rows' kind,
        and a name template uses fields of the folder's record."""
        if spec.general:
            if spec.columns and holder_schema is not None:
                have = {
                    rf.field.name for rf in self._schemas.collect_fields(holder_schema)
                }
                for column in spec.columns:
                    if (
                        column not in META_COLUMNS
                        and column.partition(".")[0] not in have
                    ):
                        raise ValidationError(f"'{column}' isn't a field of {where}.")
            return
        if spec.where and layout != "tree":
            raise ValidationError(
                "A table written in each folder needs the layout with a folder per "
                "record (tree)."
            )
        reachable = {
            s.name
            for s in [
                *self._scope(schema),
                *(a for a in self._schemas.ancestors(schema)),
            ]
        }
        kind = self._table_schema(spec.kind, reachable, schema)
        if spec.where:
            holder = self._table_schema(spec.where, reachable, schema)
            above = {a.name for a in self._schemas.ancestors(kind)}
            if holder.name != kind.name and holder.name not in above:
                raise ValidationError(
                    f"A table of '{kind.name}' can only be written in the folder of "
                    f"'{kind.name}' itself or of a kind above it, not '{holder.name}'."
                )
            if spec.name:
                known = {rf.field.name for rf in self._schemas.collect_fields(holder)}
                templating.validate(spec.name, known, ("schema", "id"))
        elif spec.name:
            templating.validate(spec.name, set(), ("schema", "id"))
        have = {rf.field.name for rf in self._schemas.collect_fields(kind)}
        for column in spec.columns or []:
            if column not in META_COLUMNS and column.partition(".")[0] not in have:
                raise ValidationError(f"'{column}' isn't a field of '{kind.name}'.")

    def _table_schema(
        self, name: str | None, reachable: set[str], schema: SchemaDTO
    ) -> SchemaDTO:
        if not name or name not in reachable:
            raise ValidationError(
                f"'{name}' isn't '{schema.name}', a kind beneath it or one above it, "
                "so a table can't be made of it here."
            )
        return self._schemas.get(name)

    def _own_file_fields(self, schema: SchemaDTO) -> list[str]:
        return [f.name for f in schema.fields if f.dtype in _FILE_DTYPES]

    # -- definitions -------------------------------------------------------------

    def create(
        self,
        schema_name: str,
        name: str,
        holder: str | None = None,
        fields: list[str] | None = None,
        filter_tree: dict[str, Any] | None = None,
        files_layout: str = "tree",
        include_files: bool = True,
        tables: list[dict[str, Any]] | None = None,
    ) -> ExportDefinitionDTO:
        schema = self._schemas.get(schema_name)
        name = validate_free_name(name, "export name")
        if self._repo.get_by_name(schema.id, name):
            raise AlreadyExistsError(
                f"An export called '{name}' already exists on '{schema_name}'."
            )
        fields = list(dict.fromkeys(fields or []))
        holder_schema = self._check(
            schema, holder, fields, filter_tree, files_layout, include_files, tables
        )
        return self._repo.create(
            schema.id,
            name,
            holder_schema.id if holder_schema else None,
            fields,
            filter_tree,
            files_layout,
            include_files,
            tables,
        )

    def get(self, schema_name: str, name: str) -> ExportDefinitionDTO:
        schema = self._schemas.get(schema_name)
        dto = self._repo.get_by_name(schema.id, name)
        if dto is None:
            raise NotFoundError(f"Export '{name}' not found on '{schema_name}'.")
        return dto

    def list_all(self) -> list[ExportDefinitionDTO]:
        """Every saved export, whatever schema it is saved with."""
        return self._repo.list_all()

    def list_for(self, schema_name: str) -> list[ExportDefinitionDTO]:
        """The exports saved with this schema, oldest first."""
        return self._repo.list_by_schema(self._schemas.get(schema_name).id)

    def update(
        self,
        schema_name: str,
        name: str,
        new_name: str | None = None,
        holder=...,
        fields=...,
        filter_tree=...,
        files_layout=...,
        include_files=...,
        tables=...,
    ) -> ExportDefinitionDTO:
        """Change any part of a definition; what isn't given is left as it was.
        The result is checked as a whole, since parts depend on each other (the
        fields on the kind, the filter on the kind)."""
        schema = self._schemas.get(schema_name)
        current = self.get(schema_name, name)
        if new_name:
            new_name = validate_free_name(new_name, "export name")
            if new_name != name and self._repo.get_by_name(schema.id, new_name):
                raise AlreadyExistsError(
                    f"An export called '{new_name}' already exists on '{schema_name}'."
                )
        new_holder = current.holder if holder is ... else holder
        new_fields = current.fields if fields is ... else list(dict.fromkeys(fields))
        new_filter = current.filter_tree if filter_tree is ... else filter_tree
        new_layout = current.files_layout if files_layout is ... else files_layout
        new_include = (
            current.include_files if include_files is ... else bool(include_files)
        )
        new_tables = current.tables if tables is ... else tables
        if not new_include and fields is ...:
            new_fields = []  # file fields only mean something with files
        holder_schema = self._check(
            schema,
            new_holder,
            new_fields,
            new_filter,
            new_layout,
            new_include,
            new_tables,
        )
        return self._repo.update(
            current.id,
            name=new_name or None,
            holder_id=holder_schema.id if holder_schema else None,
            fields=new_fields,
            filter_tree=new_filter,
            files_layout=new_layout,
            include_files=new_include,
            tables=new_tables,
        )

    def delete(self, schema_name: str, name: str) -> None:
        self._repo.delete(self.get(schema_name, name).id)

    # -- where it is offered ------------------------------------------------------

    def available_on(self, schema_name: str) -> list[ExportDefinitionDTO]:
        """The exports that can run within a record of `schema_name`: those saved
        with it or with a schema above it, whose files (the kind that holds them,
        or any kind beneath) can be at or below it. An export saved with an
        Encounter and holding Selection files is offered on an Encounter, on a
        Recording, and on a Selection."""
        schema = self._schemas.get(schema_name)
        below = {s.name for s in self._scope(schema)}
        out = []
        for d in self._repo.list_all():
            attached = self._schemas.get(d.schema_name)
            if schema.name not in {s.name for s in self._scope(attached)}:
                continue
            if d.holder is None or d.holder in below:
                out.append(d)
        return out

    def for_collection(self, schema_names: list[str]) -> list[ExportDefinitionDTO]:
        """The exports to offer on a collection that is for these schemas: those
        saved with any of them, in one query."""
        ids = []
        for name in schema_names:
            try:
                ids.append(self._schemas.get(name).id)
            except NotFoundError:
                continue
        return self._repo.list_for_schemas(ids)

    # -- running -----------------------------------------------------------------

    def selection(
        self,
        definition: ExportDefinitionDTO,
        collection: str | None = None,
        within: str | None = None,
    ) -> FileSelection:
        """The files one run of this export takes: everything it describes, in
        the collection and/or within the record it is run on."""
        scope = None
        if definition.holder is None:
            attached = self._schemas.get(definition.schema_name)
            scope = [s.name for s in self._scope(attached)]
        return FileSelection(
            query=RecordQuery(
                dataset=collection,
                schema=definition.holder,
                within=within,
                filter_tree=definition.filter_tree,
            ),
            fields=definition.fields or None,
            layout=definition.files_layout,
            schemas=scope,
            tables=TableSpec.from_list(definition.tables),
            files=definition.include_files,
        )
