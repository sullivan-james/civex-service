from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any, Iterator

from civex.domain.dtos import FileRef, RecordDTO, SchemaDTO, ViewDTO
from civex.domain.exceptions import AlreadyExistsError, NotFoundError
from civex.domain.naming import validate_free_name
from civex.domain.query import RecordQuery
from civex.repositories.protocols import AuditRepository, ViewRepository
from civex.services.record_service import RecordService
from civex.services.schema_service import SchemaService

SORT_DIRECTIONS = frozenset({"asc", "desc"})

# Records per page when an export walks a view's full result set.
EXPORT_PAGE_SIZE = 500


@dataclass
class ExportBatch:
    """One page of an export: flattened rows plus the files to bundle."""

    rows: list[dict[str, Any]]
    # (zip entry path, blob) for every file/file_list value in a file-bearing
    # column of these rows -- empty when the view has no such columns.
    file_entries: list[tuple[str, FileRef]]


@dataclass
class ViewExportStream:
    """A view export that yields its rows page by page, so neither the rows
    nor the record DTOs behind them are ever all in memory at once."""

    view: ViewDTO
    batches: Iterator[ExportBatch]


@dataclass
class ViewExport:
    """Fully materialised export -- convenient for small views and tests;
    large exports should consume `ViewExportStream` instead."""

    view: ViewDTO
    rows: list[dict[str, Any]]
    # (zip entry path, blob) for every file/file_list value in a file-bearing
    # column -- empty when the view has no such columns.
    file_entries: list[tuple[str, FileRef]]


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
    ) -> ViewDTO:
        schema = self._schemas.get(schema_name)
        name = validate_free_name(name, "view name")
        if self._views.get_by_name(schema.id, name):
            raise AlreadyExistsError(
                f"View '{name}' already exists on schema '{schema_name}'"
            )
        dto = self._views.create(
            schema.id, name, *self._validate(schema, columns, filter_tree, sort)
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

    def export_stream(self, schema_name: str, view_name: str) -> ViewExportStream:
        """Every record the view matches (across all datasets -- a view isn't
        dataset-scoped), flattened into `columns` and yielded in pages of
        EXPORT_PAGE_SIZE. When any column is a file/file_list field, its row
        value is swapped for the same `resolved_filename` the record API
        stamps on file values (falling back to the original filename), and
        each batch's `file_entries` carries the matching zip path (record id +
        collision-suffixed name, via RecordService.files_for_zip) and FileRef
        for every file to bundle alongside the CSV/JSON."""
        view = self.get(schema_name, view_name)
        schema = self._schemas.get(schema_name)
        file_columns = self._file_columns(schema, view.columns)

        def batches() -> Iterator[ExportBatch]:
            for records in self._record_svc.stream_records(
                self.query_for(schema_name, view_name),
                page_size=EXPORT_PAGE_SIZE,
                columns=view.columns,
            ):
                rows = self._rows(view.columns, records)
                file_entries: list[tuple[str, FileRef]] = []
                if file_columns:
                    for record, row in zip(records, rows):
                        entries = self._record_svc.files_for_zip(
                            str(record.id), field_names=file_columns
                        )
                        for name, ref in entries:
                            file_entries.append((f"{record.id}/{name}", ref))
                        for col in file_columns:
                            row[col] = _display_filename(row.get(col))
                yield ExportBatch(rows=rows, file_entries=file_entries)

        return ViewExportStream(view=view, batches=batches())

    def export(self, schema_name: str, view_name: str) -> ViewExport:
        """`export_stream()` collected into memory."""
        stream = self.export_stream(schema_name, view_name)
        rows: list[dict[str, Any]] = []
        file_entries: list[tuple[str, FileRef]] = []
        for batch in stream.batches:
            rows.extend(batch.rows)
            file_entries.extend(batch.file_entries)
        return ViewExport(view=stream.view, rows=rows, file_entries=file_entries)


def _display_filename(value: Any) -> Any:
    """A file/file_list cell's raw FileRef dict(s) -> the resolved
    filename(s) already stamped on them by RecordService -- rows are
    display/export data, not a second copy of the file metadata."""
    if isinstance(value, dict):
        return value.get("resolved_filename") or value.get("filename")
    if isinstance(value, list):
        return [
            v.get("resolved_filename") or v.get("filename")
            for v in value
            if isinstance(v, dict)
        ]
    return value


def _nest_row(row: dict[str, Any]) -> dict[str, Any]:
    """{"amount": 100, "customer.email": "a@x"} -> {"amount": 100, "customer":
    {"email": "a@x"}} -- JSON export keeps joined columns nested instead of
    repeating the CSV's flat dotted-header convention."""
    nested: dict[str, Any] = {}
    for key, value in row.items():
        if "." in key:
            head, _, tail = key.partition(".")
            nested.setdefault(head, {})[tail] = value
        else:
            nested[key] = value
    return nested


def rows_to_csv(columns: list[str], rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                k: v if not isinstance(v, (list, dict)) else json.dumps(v)
                for k, v in row.items()
            }
        )
    return buf.getvalue()


def rows_to_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps([_nest_row(r) for r in rows], indent=2, default=str)


def write_csv(
    out: Any, columns: list[str], batches: Iterator[list[dict[str, Any]]]
) -> None:
    """Stream rows to a text file object as CSV, batch by batch."""
    writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for rows in batches:
        for row in rows:
            writer.writerow(
                {
                    k: v if not isinstance(v, (list, dict)) else json.dumps(v)
                    for k, v in row.items()
                }
            )


def write_json(out: Any, batches: Iterator[list[dict[str, Any]]]) -> None:
    """Stream rows to a text file object as a JSON array, batch by batch --
    byte-identical to `rows_to_json` (2-space indent), without building the
    whole array in memory."""
    first = True
    for rows in batches:
        for row in rows:
            body = json.dumps(_nest_row(row), indent=2, default=str)
            out.write("[\n" if first else ",\n")
            out.write("  " + body.replace("\n", "\n  "))
            first = False
    out.write("[]" if first else "\n]")
