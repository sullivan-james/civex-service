from __future__ import annotations

import csv
import io
import json
import uuid
from dataclasses import dataclass
from typing import Any, Iterator

from civex.domain.dtos import FieldDTO, FileRef, RecordDTO, SchemaDTO, ViewDTO
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from civex.domain.filters import FilterGroup, FilterNode, parse_filter_tree
from civex.domain.naming import validate_name
from civex.repositories.protocols import (
    AuditRepository,
    RecordRepository,
    ViewRepository,
)
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
        record_repo: RecordRepository,
        record_svc: RecordService,
        audit_repo: AuditRepository | None = None,
    ) -> None:
        self._views = view_repo
        self._schemas = schema_svc
        self._records = record_repo
        self._record_svc = record_svc
        self._audit = audit_repo

    def _validate_columns(
        self, columns: list[str] | None, schema: SchemaDTO
    ) -> list[str]:
        cols = list(columns or [])
        fields_by_name = {
            rf.field.name: rf.field for rf in self._schemas.collect_fields(schema)
        }
        unknown = []
        for col in cols:
            if "." in col:
                self._validate_join_column(col, fields_by_name)
            elif col not in fields_by_name:
                unknown.append(col)
        if unknown:
            raise ValidationError(
                f"Unknown column field(s) {sorted(unknown)} for this schema"
            )
        return cols

    def _validate_join_column(
        self, col: str, fields_by_name: dict[str, FieldDTO]
    ) -> None:
        parts = col.split(".")
        if len(parts) != 2:
            raise ValidationError(
                f"Column '{col}' is not a valid reference-field join -- only "
                "one hop is supported (e.g. 'customer.email')"
            )
        ref_name, target_name = parts
        ref_field = fields_by_name.get(ref_name)
        if ref_field is None:
            raise ValidationError(
                f"Unknown column field(s) ['{ref_name}'] for this schema"
            )
        if ref_field.dtype != "reference":
            raise ValidationError(
                f"Column '{col}' joins through '{ref_name}', a '{ref_field.dtype}' "
                "field -- only single 'reference' fields support joins"
            )
        target_schema_name = ref_field.restrictions.get("schema")
        if not target_schema_name:
            raise ValidationError(
                f"Column '{col}' joins through '{ref_name}', which has no target "
                "schema restriction set"
            )
        try:
            target_schema = self._schemas.get(target_schema_name)
        except NotFoundError:
            raise ValidationError(
                f"Column '{col}' targets schema '{target_schema_name}', which "
                "does not exist"
            ) from None
        target_known = {
            rf.field.name for rf in self._schemas.collect_fields(target_schema)
        }
        if target_name not in target_known:
            raise ValidationError(
                f"Unknown column field(s) ['{col}'] for schema '{target_schema_name}'"
            )

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
            self._validate_columns(columns, schema),
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
        if new_name and new_name != view_name:
            validate_name(new_name, "view name")
            if self._views.get_by_name(schema.id, new_name):
                raise AlreadyExistsError(
                    f"View '{new_name}' already exists on schema '{schema_name}'"
                )
        known = {rf.field.name for rf in self._schemas.collect_fields(schema)}
        extra: dict[str, Any] = {}
        if columns is not ...:
            extra["columns"] = self._validate_columns(columns, schema)
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

    def _join_specs(
        self, columns: list[str], fields_by_name: dict[str, FieldDTO]
    ) -> dict[str, tuple[str, str]]:
        """column -> (reference field name, target field id) for every dotted
        join column. Columns that no longer resolve (a field or target schema
        renamed/removed after the view was saved) are silently dropped rather
        than raised -- resolution happens at query time, long after
        create/update validation ran."""
        joins: dict[str, tuple[str, str]] = {}
        for col in columns:
            if "." not in col:
                continue
            ref_name, _, target_name = col.partition(".")
            ref_field = fields_by_name.get(ref_name)
            if ref_field is None or ref_field.dtype != "reference":
                continue
            target_schema_name = ref_field.restrictions.get("schema")
            if not target_schema_name:
                continue
            try:
                target_schema = self._schemas.get(target_schema_name)
            except NotFoundError:
                continue
            target_id = self._schemas.name_to_id_map(target_schema).get(target_name)
            if target_id is None:
                continue
            joins[col] = (ref_name, target_id)
        return joins

    def _build_rows(
        self,
        columns: list[str],
        records: list[RecordDTO],
        fields_by_name: dict[str, FieldDTO],
    ) -> list[dict[str, Any]]:
        """Flatten `records` (name-keyed record data for the base schema)
        into rows matching `columns`, joining one hop through the stored
        UUID of any dotted reference-field column ("customer.email")."""
        joins = self._join_specs(columns, fields_by_name)

        target_cache: dict[str, RecordDTO | None] = {}

        def target_record(ref_value: str) -> RecordDTO | None:
            if ref_value not in target_cache:
                try:
                    target_cache[ref_value] = self._records.get_by_id(
                        uuid.UUID(ref_value)
                    )
                except (ValueError, TypeError):
                    target_cache[ref_value] = None
            return target_cache[ref_value]

        rows = []
        for record in records:
            row: dict[str, Any] = {}
            for col in columns:
                if col in joins:
                    ref_name, target_field_id = joins[col]
                    ref_value = record.data.get(ref_name)
                    target = target_record(ref_value) if ref_value else None
                    row[col] = target.data.get(target_field_id) if target else None
                else:
                    row[col] = record.data.get(col)
            rows.append(row)
        return rows

    def resolve_rows(
        self, schema_name: str, view_name: str, records: list[RecordDTO]
    ) -> list[dict[str, Any]]:
        """Flatten `records` (name-keyed record data for the view's base
        schema, e.g. from RecordService.find) into rows matching `view.columns`,
        joining one hop through the stored UUID of any dotted reference-field
        column ("customer.email")."""
        view = self.get(schema_name, view_name)
        schema = self._schemas.get(schema_name)
        fields_by_name = {
            rf.field.name: rf.field for rf in self._schemas.collect_fields(schema)
        }
        return self._build_rows(view.columns, records, fields_by_name)

    def preview(
        self,
        schema_name: str,
        columns: list[str] | None = None,
        filter_tree: dict[str, Any] | None = None,
        sort: list[dict[str, Any]] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Rows + total count for the current (possibly unsaved) column/
        filter/sort selection while building a view -- the same join/flatten
        logic as `resolve_rows`, but against an arbitrary selection rather
        than an already-saved view."""
        schema = self._schemas.get(schema_name)
        cols = self._validate_columns(columns, schema)
        known = {rf.field.name for rf in self._schemas.collect_fields(schema)}
        validated_tree = self._validate_filter_tree(filter_tree, known)
        validated_sort = self._validate_sort(sort, known)

        total = self._record_svc.count_by_schema_filtered(
            schema_name, filter_tree=validated_tree
        )
        # Filter, sort and page all happen in SQL, so this only ever
        # materialises the `limit` rows actually shown.
        records = self._record_svc.find_by_schema_filtered(
            schema_name,
            filter_tree=validated_tree,
            limit=limit,
            offset=offset,
            sort=validated_sort,
        )
        fields_by_name = {
            rf.field.name: rf.field for rf in self._schemas.collect_fields(schema)
        }
        return self._build_rows(cols, records, fields_by_name), total

    def _file_columns(self, schema: SchemaDTO, columns: list[str]) -> list[str]:
        """Base-schema (non-joined) columns whose field is file/file_list --
        the ones export bundles as a zip. Joined file columns aren't
        supported: resolve_rows reads join targets straight off the raw
        repo, bypassing the filename-template resolution that only runs for
        the view's own base-schema records."""
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
        """Every record for the view's schema (across all datasets -- a view
        isn't dataset-scoped), filtered/sorted per the view's own definition
        in SQL and flattened into `columns` via `_build_rows`, yielded in
        pages of EXPORT_PAGE_SIZE. When any column is a file/file_list field,
        its row value is swapped for the same `resolved_filename` the record
        API stamps on file values (falling back to the original filename),
        and each batch's `file_entries` carries the matching zip path
        (record id + collision-suffixed name, via RecordService.files_for_zip)
        and FileRef for every file to bundle alongside the CSV/JSON."""
        view = self.get(schema_name, view_name)
        schema = self._schemas.get(schema_name)
        fields_by_name = {
            rf.field.name: rf.field for rf in self._schemas.collect_fields(schema)
        }
        file_columns = self._file_columns(schema, view.columns)

        def batches() -> Iterator[ExportBatch]:
            for records in self._record_svc.iter_find_by_schema_filtered(
                schema_name,
                filter_tree=view.filter_tree,
                sort=view.sort or None,
                page_size=EXPORT_PAGE_SIZE,
            ):
                rows = self._build_rows(view.columns, records, fields_by_name)
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
