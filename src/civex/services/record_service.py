from __future__ import annotations

import dataclasses
import uuid
from datetime import date as _date, datetime as _dt, timezone as _tz
from pathlib import Path
from typing import Any

from civex.domain.dtos import RecordDTO, ResolvedField
from civex.domain.exceptions import CoercionError, NotFoundError, ValidationError
from civex.repositories.protocols import (
    AuditRepository,
    DatasetRepository,
    FileObjectStore,
    RecordRepository,
)
from civex.services.schema_service import SchemaService

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from civex.services.workflow_job_service import WorkflowJobService


def _parse_date(v: str) -> str:
    return _date.fromisoformat(v.strip()).isoformat()


def _parse_datetime(v: str) -> str:
    s = v.strip()
    # datetime-local inputs omit seconds; fromisoformat needs them on Python <3.11
    if len(s) == 16 and s[10] == "T":
        s += ":00"
    dt = _dt.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz.utc)
    return dt.astimezone(_tz.utc).isoformat()


_COERCE: dict[str, Any] = {
    "integer": int,
    "float": float,
    "string": str,
    "boolean": lambda v: (
        v.strip().lower() in ("true", "yes", "1") if isinstance(v, str) else bool(v)
    ),
    "date": _parse_date,
    "datetime": _parse_datetime,
    "enum": str,
    "url": str,
    "tags": lambda v: (
        [t.strip() for t in v.split(",")] if isinstance(v, str) else [str(t) for t in v]
    ),
}


def _check_restrictions(
    value: Any, dtype: str, restrictions: dict[str, Any], field_name: str
) -> None:
    """Raise ValidationError if value violates field restrictions. Single source of truth."""
    if value is None:
        return

    # URL format is always validated regardless of restrictions.
    if dtype == "url":
        s = str(value)
        if not (s.startswith("http://") or s.startswith("https://")):
            raise ValidationError(
                f"Field '{field_name}': '{value}' is not a valid URL (must start with http:// or https://)"
            )
        return

    if not restrictions:
        return

    if dtype in ("integer", "float"):
        mn = restrictions.get("min")
        mx = restrictions.get("max")
        if mn is not None and value < mn:
            raise ValidationError(
                f"Field '{field_name}': {value} is below minimum ({mn})"
            )
        if mx is not None and value > mx:
            raise ValidationError(
                f"Field '{field_name}': {value} exceeds maximum ({mx})"
            )

    elif dtype == "string":
        choices = restrictions.get("choices")
        max_length = restrictions.get("max_length")
        if choices is not None and value not in choices:
            raise ValidationError(
                f"Field '{field_name}': '{value}' must be one of: {', '.join(str(c) for c in choices)}"
            )
        if max_length is not None and len(value) > int(max_length):
            raise ValidationError(
                f"Field '{field_name}': value length {len(value)} exceeds max_length {max_length}"
            )

    elif dtype == "enum":
        choices = restrictions.get("choices")
        if choices is not None and value not in choices:
            raise ValidationError(
                f"Field '{field_name}': '{value}' must be one of: {', '.join(str(c) for c in choices)}"
            )

    elif dtype in ("date", "datetime"):
        mn = restrictions.get("min")
        mx = restrictions.get("max")
        # Compare via parsed objects so timezone offsets don't cause lexicographic bugs.
        try:
            if dtype == "date":
                v_cmp = _date.fromisoformat(str(value))
                mn_cmp = _date.fromisoformat(str(mn)) if mn is not None else None
                mx_cmp = _date.fromisoformat(str(mx)) if mx is not None else None
            else:
                v_cmp = _dt.fromisoformat(str(value))
                mn_cmp = _dt.fromisoformat(str(mn)) if mn is not None else None
                mx_cmp = _dt.fromisoformat(str(mx)) if mx is not None else None
            if mn_cmp is not None and v_cmp < mn_cmp:
                raise ValidationError(
                    f"Field '{field_name}': {value} is before minimum ({mn})"
                )
            if mx_cmp is not None and v_cmp > mx_cmp:
                raise ValidationError(
                    f"Field '{field_name}': {value} is after maximum ({mx})"
                )
        except (ValueError, TypeError):
            pass  # malformed restriction — let it through; the value was already normalised

    elif dtype in ("file", "file_list"):
        refs = value if isinstance(value, list) else [value]
        accept = restrictions.get("accept")
        max_size = restrictions.get("max_size")
        allowed_exts = (
            {
                e.strip().lower().lstrip(".")
                for e in accept.split(",")
                if e.strip().startswith(".")
            }
            if accept
            else set()
        )
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            if allowed_exts:
                ext = Path(ref.get("filename", "")).suffix.lstrip(".").lower()
                if ext not in allowed_exts:
                    raise ValidationError(
                        f"Field '{field_name}': '{ref.get('filename')}' type '.{ext}' not allowed"
                        f" — accepted: {accept}"
                    )
            if max_size is not None and ref.get("size", 0) > int(max_size):
                raise ValidationError(
                    f"Field '{field_name}': file size {ref.get('size', 0)} bytes"
                    f" exceeds max_size {max_size}"
                )


# Types that skip the generic _COERCE path (handled explicitly in coerce_value)
# and are also excluded from natural-name computation (they're collection/blob types).
_SKIP_TYPES = {"reference", "reference_list", "file", "file_list", "tags"}


def _natural_name(
    data: dict[str, Any], fields: list, display_fields: list[str] | None = None
) -> str | None:
    if display_fields:
        parts = []
        for name in display_fields:
            val = data.get(name)
            if val is not None and str(val).strip():
                parts.append(str(val))
        return " ".join(parts) if parts else None
    for rf in fields:
        f = rf.field
        if f.dtype in _SKIP_TYPES:
            continue
        val = data.get(f.name)
        if val is not None and str(val).strip():
            return str(val)
    return None


def _referrers_message(referrers: list[tuple[RecordDTO, dict[str, str]]]) -> str:
    shown = referrers[:10]
    parts = [
        f"{rec.schema_name} record {rec.id} (via {', '.join(sorted(set(fields.values())))})"
        for rec, fields in shown
    ]
    msg = (
        f"Cannot delete: still referenced by {len(referrers)} record(s): "
        + "; ".join(parts)
    )
    if len(referrers) > len(shown):
        msg += f" and {len(referrers) - len(shown)} more"
    return msg


class RecordService:
    def __init__(
        self,
        schema_svc: SchemaService,
        dataset_repo: DatasetRepository,
        record_repo: RecordRepository,
        file_store: FileObjectStore,
        job_svc: WorkflowJobService | None = None,
        audit_repo: AuditRepository | None = None,
    ) -> None:
        self._schema_svc = schema_svc
        self._datasets = dataset_repo
        self._records = record_repo
        self._files = file_store
        self._job_svc = job_svc
        self._audit = audit_repo

    # ------------------------------------------------------------------
    # Field ID translation (name-keyed ↔ UUID-keyed record data)
    # ------------------------------------------------------------------

    def _names_to_ids(
        self, data: dict[str, Any], schema_id: uuid.UUID
    ) -> dict[str, Any]:
        schema = self._schema_svc._repo.get_by_id(schema_id, include_deleted=True)
        if schema is None:
            return data
        name_map = self._schema_svc.name_to_id_map(schema)
        return {name_map.get(k, k): v for k, v in data.items()}

    def _ids_to_names(
        self, data: dict[str, Any], schema_id: uuid.UUID
    ) -> dict[str, Any]:
        schema = self._schema_svc._repo.get_by_id(schema_id, include_deleted=True)
        if schema is None:
            return data
        id_map = self._schema_svc.id_to_name_map(schema)
        return {id_map.get(k, k): v for k, v in data.items()}

    def _with_names(self, dto: RecordDTO) -> RecordDTO:
        schema = self._schema_svc._repo.get_by_id(dto.schema_id, include_deleted=True)
        if schema is None:
            return dataclasses.replace(dto)
        id_map = self._schema_svc.id_to_name_map(schema)
        named_data = {id_map.get(k, k): v for k, v in dto.data.items()}
        fields = self._schema_svc.collect_fields(schema)
        natural_name = _natural_name(named_data, fields, schema.display_fields)
        return dataclasses.replace(dto, data=named_data, natural_name=natural_name)

    def _apply_defaults(
        self, data: dict[str, Any], schema_id: uuid.UUID
    ) -> dict[str, Any]:
        """For any field with a default_value that is absent from data, insert the default."""
        schema = self._schema_svc._repo.get_by_id(schema_id, include_deleted=True)
        if schema is None:
            return data
        all_fields = self._schema_svc.collect_fields(schema)
        result = dict(data)
        for rf in all_fields:
            f = rf.field
            if f.default_value is not None and f.name not in result:
                result[f.name] = f.default_value
        return result

    def coerce_value(
        self,
        raw: str,
        dtype: str,
        field_name: str,
        restrictions: dict[str, Any] | None = None,
    ) -> Any:
        if dtype == "file":
            path = Path(raw)
            if not path.exists():
                raise CoercionError(field_name, dtype, raw)
            file_ref = self._files.put(path.read_bytes(), path.name)
            value = file_ref.to_dict()
            _check_restrictions(value, dtype, restrictions or {}, field_name)
            return value

        if dtype == "file_list":
            path = Path(raw)
            if not path.exists():
                raise CoercionError(field_name, dtype, raw)
            file_ref = self._files.put(path.read_bytes(), path.name)
            file_list_value = [file_ref.to_dict()]
            _check_restrictions(file_list_value, dtype, restrictions or {}, field_name)
            return file_list_value

        if dtype == "reference":
            record = self._records.get_by_prefix(raw)
            if not record:
                raise CoercionError(field_name, dtype, raw, extra="record not found")
            target_schema = (restrictions or {}).get("schema")
            if target_schema and record.schema_name != target_schema:
                raise CoercionError(
                    field_name,
                    dtype,
                    raw,
                    extra=f"record has schema '{record.schema_name}', expected '{target_schema}'",
                )
            return str(record.id)

        if dtype == "reference_list":
            if isinstance(raw, str):
                items: list[Any] = [x.strip() for x in raw.split(",") if x.strip()]
            else:
                items = list(raw)
            target_schema = (restrictions or {}).get("schema")
            result = []
            for item in items:
                record = self._records.get_by_prefix(str(item))
                if not record:
                    raise CoercionError(
                        field_name, dtype, str(item), extra="record not found"
                    )
                if target_schema and record.schema_name != target_schema:
                    raise CoercionError(
                        field_name,
                        dtype,
                        str(item),
                        extra=f"record has schema '{record.schema_name}', expected '{target_schema}'",
                    )
                result.append(str(record.id))
            return result

        coerce = _COERCE.get(dtype)
        if coerce is None:
            raise CoercionError(field_name, dtype, raw)
        try:
            value = coerce(raw)
        except (ValueError, TypeError):
            raise CoercionError(field_name, dtype, raw)
        _check_restrictions(value, dtype, restrictions or {}, field_name)
        return value

    def _validate_data(self, data: dict[str, Any], schema_id: uuid.UUID) -> None:
        """Validate all field values in data against their restrictions."""
        schema = self._schema_svc._repo.get_by_id(schema_id, include_deleted=True)
        if schema is None:
            return
        fields_by_name = {
            rf.field.name: rf.field for rf in self._schema_svc.collect_fields(schema)
        }
        for name, value in data.items():
            field = fields_by_name.get(name)
            if field is None or value is None:
                continue
            _check_restrictions(value, field.dtype, field.restrictions, name)

    def validate(self, data: dict[str, Any], fields: list[ResolvedField]) -> None:
        missing = [
            rf.field.name
            for rf in fields
            if rf.field.required and rf.field.name not in data
        ]
        if missing:
            raise ValidationError(f"Missing required fields: {', '.join(missing)}")

    def get_resolved_fields(self, schema_name: str) -> list[ResolvedField]:
        """
        Fields to prompt for when adding/updating a record of this schema.
        For child schemas, only own fields are returned — inherited fields
        live on the parent record.
        """
        schema = self._schema_svc.get(schema_name)
        if schema.parent_id:
            return [
                ResolvedField(field=f, source_schema_name=schema.name)
                for f in schema.fields
            ]
        return self._schema_svc.collect_fields(schema)

    def add(
        self,
        dataset_name: str,
        schema_name: str,
        data: dict[str, Any],
        parent_record_id: str | None = None,
        _job_depth: int = 0,
    ) -> RecordDTO:
        dataset = self._datasets.get_by_name(dataset_name)
        if not dataset:
            raise NotFoundError(f"Dataset '{dataset_name}' not found")

        schema = self._schema_svc.get(schema_name)

        # Apply field defaults before validation
        data = self._apply_defaults(data, schema.id)

        resolved_parent_id = None
        if schema.parent_id:
            if not parent_record_id:
                raise ValidationError(
                    f"Schema '{schema.name}' inherits from another schema — a parent record ID is required"
                )
            parent_record = self._records.get_by_prefix(parent_record_id)
            if not parent_record:
                raise NotFoundError(f"Parent record '{parent_record_id}' not found")
            if parent_record.dataset_id != dataset.id:
                raise ValidationError(
                    f"Parent record must belong to dataset '{dataset_name}'"
                )
            expected_parent = self._schema_svc._repo.get_by_id(schema.parent_id, include_deleted=True)
            if parent_record.schema_id != schema.parent_id:
                raise ValidationError(
                    f"Parent record uses schema '{parent_record.schema_name}', "
                    f"expected '{expected_parent.name if expected_parent else schema.parent_id}'"
                )
            resolved_parent_id = parent_record.id
            own_fields = [
                ResolvedField(field=f, source_schema_name=schema.name)
                for f in schema.fields
            ]
            self.validate(data, own_fields)
        else:
            self.validate(data, self._schema_svc.collect_fields(schema))

        self._validate_data(data, schema.id)
        id_data = self._names_to_ids(data, schema.id)
        dto = self._records.create(
            dataset_id=dataset.id,
            schema_id=schema.id,
            data=id_data,
            parent_record_id=resolved_parent_id,
        )
        named = self._with_names(dto)
        if self._audit:
            self._audit.log_change("create", "record", dto.id, None, named.to_dict())
        if self._job_svc:
            self._job_svc.trigger_for_record(named, "record_created", depth=_job_depth)
            if named.data:
                # Also fire record_updated so field-specific triggers (e.g. triggered on
                # a particular field being set) fire even when the record is first created.
                set_fields = {k for k, v in named.data.items() if v is not None}
                if set_fields:
                    self._job_svc.trigger_for_record(
                        named,
                        "record_updated",
                        changed_fields=set_fields,
                        depth=_job_depth,
                    )
        return named

    def get(self, record_id: str) -> RecordDTO:
        record = self._records.get_by_prefix(record_id)
        if not record:
            raise NotFoundError(f"Record '{record_id}' not found")
        return self._with_names(record)

    def update(
        self, record_id: str, data: dict[str, Any], _job_depth: int = 0
    ) -> RecordDTO:
        raw = self._records.get_by_prefix(record_id)
        if not raw:
            raise NotFoundError(f"Record '{record_id}' not found")
        # Apply field defaults before validation
        data = self._apply_defaults(data, raw.schema_id)
        self._validate_data(data, raw.schema_id)
        old_data = self._ids_to_names(raw.data, raw.schema_id)
        id_data = self._names_to_ids(data, raw.schema_id)
        dto = self._records.update(id=raw.id, data=id_data)
        named = self._with_names(dto)
        if self._audit:
            old_named = dataclasses.replace(
                raw, data=old_data, schema_name=named.schema_name
            )
            self._audit.log_change(
                "update", "record", raw.id, old_named.to_dict(), named.to_dict()
            )
        if self._job_svc:
            changed = {
                k
                for k in set(old_data) | set(named.data)
                if old_data.get(k) != named.data.get(k)
            }
            self._job_svc.trigger_for_record(
                named, "record_updated", changed_fields=changed, depth=_job_depth
            )
        return named

    def find(
        self,
        dataset_name: str,
        schema_name: str | None = None,
        parent_record_id: str | None = None,
        filters: list[str] | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RecordDTO]:
        dataset, schema_id, parent_uuid, field_filters = self._resolve_query_params(
            dataset_name, schema_name, parent_record_id, filters or []
        )
        records = self._records.list_filtered(
            dataset_id=dataset.id,
            schema_id=schema_id,
            parent_record_id=parent_uuid,
            field_filters=field_filters,
            search=search or None,
            offset=offset,
            limit=limit,
        )
        return [self._with_names(r) for r in records]

    def count(
        self,
        dataset_name: str,
        schema_name: str | None = None,
        parent_record_id: str | None = None,
        filters: list[str] | None = None,
        search: str | None = None,
    ) -> int:
        dataset, schema_id, parent_uuid, field_filters = self._resolve_query_params(
            dataset_name, schema_name, parent_record_id, filters or []
        )
        return self._records.count(
            dataset_id=dataset.id,
            schema_id=schema_id,
            parent_record_id=parent_uuid,
            field_filters=field_filters,
            search=search or None,
        )

    def schema_counts(self, dataset_name: str) -> dict[str, int]:
        dataset = self._datasets.get_by_name(dataset_name)
        if not dataset:
            raise NotFoundError(f"Dataset '{dataset_name}' not found")
        return self._records.count_by_schema(dataset.id)

    def _resolve_query_params(
        self,
        dataset_name: str,
        schema_name: str | None,
        parent_record_id: str | None,
        filters: list[str],
    ):
        dataset = self._datasets.get_by_name(dataset_name)
        if not dataset:
            raise NotFoundError(f"Dataset '{dataset_name}' not found")

        schema_id = None
        name_map: dict[str, str] = {}
        if schema_name:
            schema = self._schema_svc.get(schema_name)
            schema_id = schema.id
            name_map = self._schema_svc.name_to_id_map(schema)

        parent_uuid = None
        if parent_record_id:
            parent = self._records.get_by_prefix(parent_record_id)
            if not parent:
                raise NotFoundError(f"Parent record '{parent_record_id}' not found")
            parent_uuid = parent.id

        field_filters: list[tuple[str, str]] = []
        for condition in filters:
            if "=" not in condition:
                raise ValueError(f"Invalid filter '{condition}'. Use field=value.")
            key, _, value = condition.partition("=")
            field_filters.append((name_map.get(key, key), value))

        return dataset, schema_id, parent_uuid, field_filters

    def find_by_schema(
        self,
        schema_name: str,
        search: str | None = None,
        limit: int = 20,
    ) -> list[RecordDTO]:
        schema = self._schema_svc.get(schema_name)
        records = self._records.list_by_schema(schema.id, search=search, limit=limit)
        return [self._with_names(r) for r in records]

    def delete(self, record_id: str, force: bool = False) -> None:
        record = self.get(record_id)
        delete_set = self._collect_delete_set(record.id)
        self._handle_referrers(delete_set, force)
        self._delete_recursive(record.id)

    def delete_many(self, record_ids: list[str], force: bool = False) -> int:
        records = []
        for rid in record_ids:
            try:
                records.append(self.get(rid))
            except NotFoundError:
                continue

        delete_set: set[uuid.UUID] = set()
        for r in records:
            delete_set |= self._collect_delete_set(r.id)
        self._handle_referrers(delete_set, force)

        deleted = 0
        for r in records:
            if not self._records.get_by_id(r.id):
                continue  # already gone via a parent cascade earlier in this batch
            self._delete_recursive(r.id)
            deleted += 1
        return deleted

    def delete_all(
        self, dataset_name: str, schema_name: str | None = None, force: bool = False
    ) -> int:
        dataset = self._datasets.get_by_name(dataset_name)
        if not dataset:
            raise NotFoundError(f"Dataset '{dataset_name}' not found")
        schema_id = None
        if schema_name:
            schema = self._schema_svc.get(schema_name)
            schema_id = schema.id
        records = self._records.list_by_dataset(dataset.id)
        targets = [r for r in records if not schema_id or r.schema_id == schema_id]

        delete_set: set[uuid.UUID] = set()
        for r in targets:
            delete_set |= self._collect_delete_set(r.id)
        self._handle_referrers(delete_set, force)

        deleted = 0
        for r in targets:
            if not self._records.get_by_id(r.id):
                continue  # already gone via a parent cascade
            self._delete_recursive(r.id)
            deleted += 1
        return deleted

    def list_deleted(self, dataset_name: str | None = None) -> list[RecordDTO]:
        dataset_id = None
        if dataset_name:
            dataset = self._datasets.get_by_name(dataset_name)
            if not dataset:
                raise NotFoundError(f"Dataset '{dataset_name}' not found")
            dataset_id = dataset.id
        return [
            self._with_names(r) for r in self._records.list_deleted(dataset_id)
        ]

    def restore(self, record_id: str) -> RecordDTO:
        """Undo delete(): the record and every descendant cascade-deleted
        with it (see _restore_recursive) become live again."""
        record = self._records.get_by_prefix(record_id, include_deleted=True)
        if record is None:
            raise NotFoundError(f"Record '{record_id}' not found")
        if record.deleted_at is None:
            raise ValidationError(f"Record '{record_id}' is not deleted")
        self._restore_recursive(record.id)
        return self.get(str(record.id))

    def purge(self, record_id: str) -> None:
        """Permanently remove a record (and its cascade-deleted descendants)
        that's already in Recently Deleted — a separate, explicit action
        from delete(). Irreversible."""
        record = self._records.get_by_prefix(record_id, include_deleted=True)
        if record is None:
            raise NotFoundError(f"Record '{record_id}' not found")
        if record.deleted_at is None:
            raise ValidationError(
                f"Record '{record_id}' must be deleted before it can be purged"
            )
        self._purge_recursive(record.id)

    def _restore_recursive(self, id: uuid.UUID) -> None:
        for child in self._records.list_children(id, include_deleted=True):
            if child.deleted_at is not None:
                self._restore_recursive(child.id)
        record_dto = self._records.get_by_id(id, include_deleted=True)
        restored = self._records.restore(id)
        if self._audit and record_dto:
            old_named = dataclasses.replace(
                record_dto, schema_name=self._with_names(record_dto).schema_name
            )
            self._audit.log_change(
                "restore",
                "record",
                id,
                old_named.to_dict(),
                self._with_names(restored).to_dict(),
            )

    def _purge_recursive(self, id: uuid.UUID) -> None:
        for child in self._records.list_children(id, include_deleted=True):
            self._purge_recursive(child.id)
        record_dto = self._records.get_by_id(id, include_deleted=True)
        if self._audit and record_dto:
            self._audit.log_change(
                "purge", "record", id, self._with_names(record_dto).to_dict(), None
            )
        self._records.purge(id)

    def _delete_recursive(self, id: uuid.UUID) -> None:
        for child in self._records.list_children(id):
            self._delete_recursive(child.id)
        record_dto = self._records.get_by_id(id)
        if self._audit and record_dto:
            self._audit.log_change("delete", "record", id, record_dto.to_dict(), None)
        self._records.delete(id)

    def _collect_delete_set(self, root_id: uuid.UUID) -> set[uuid.UUID]:
        """A record plus every descendant that cascades with it via
        parent_record_id -- the full set of ids that will disappear together,
        so referrers *within* the set don't block the delete."""
        ids = {root_id}
        for child in self._records.list_children(root_id):
            ids |= self._collect_delete_set(child.id)
        return ids

    def _reference_field_map(self) -> dict[str, tuple[str, str]]:
        """field id (str) -> (field name, dtype) for every reference/reference_list
        field across all schemas -- record data is stored id-keyed (see
        _names_to_ids), and a reference field on any schema can point at a
        record of any other schema, so this has to span all of them."""
        result: dict[str, tuple[str, str]] = {}
        for schema in self._schema_svc.list_all():
            for f in schema.fields:
                if f.dtype in ("reference", "reference_list"):
                    result[str(f.id)] = (f.name, f.dtype)
        return result

    def _find_referrers(
        self, target_ids: set[uuid.UUID], exclude_ids: set[uuid.UUID]
    ) -> list[tuple[RecordDTO, dict[str, str]]]:
        """Records outside exclude_ids holding a reference/reference_list value
        that points at any of target_ids. Returns (referrer, {field_id: field_name})
        pairs so callers know exactly which field(s) to null out or report."""
        field_map = self._reference_field_map()
        if not field_map:
            return []
        ref_ids = [
            uuid.UUID(fid) for fid, (_, dt) in field_map.items() if dt == "reference"
        ]
        ref_list_ids = [
            uuid.UUID(fid)
            for fid, (_, dt) in field_map.items()
            if dt == "reference_list"
        ]
        target_strs = {str(t) for t in target_ids}
        candidates = self._records.list_referencing(
            list(target_ids), ref_ids, ref_list_ids
        )

        results = []
        for rec in candidates:
            if rec.id in exclude_ids:
                continue
            matched: dict[str, str] = {}
            for fid_str, (fname, dt) in field_map.items():
                val = rec.data.get(fid_str)
                if dt == "reference" and val in target_strs:
                    matched[fid_str] = fname
                elif (
                    dt == "reference_list"
                    and isinstance(val, list)
                    and target_strs & set(val)
                ):
                    matched[fid_str] = fname
            if matched:
                results.append((rec, matched))
        return results

    def _handle_referrers(self, target_ids: set[uuid.UUID], force: bool) -> None:
        """Block a delete of target_ids if anything outside the batch still
        references it, unless force=True -- in which case the referencing
        fields are cleared (ON DELETE SET NULL) and audit-logged instead."""
        referrers = self._find_referrers(target_ids, exclude_ids=target_ids)
        if not referrers:
            return
        if not force:
            raise ValidationError(_referrers_message(referrers))

        target_strs = {str(t) for t in target_ids}
        for rec, matched_fields in referrers:
            old_named = self._with_names(rec)
            new_data = dict(rec.data)
            for fid_str in matched_fields:
                val = new_data.get(fid_str)
                if isinstance(val, list):
                    new_data[fid_str] = [v for v in val if v not in target_strs]
                else:
                    new_data[fid_str] = None
            updated = self._records.update(id=rec.id, data=new_data)
            if self._audit:
                self._audit.log_change(
                    "update",
                    "record",
                    rec.id,
                    old_named.to_dict(),
                    self._with_names(updated).to_dict(),
                )

    def find_dangling_references(self) -> list[dict[str, Any]]:
        """Scan every record for reference/reference_list values pointing at a
        record id that no longer exists. Surfaces integrity violations left
        over from before delete-time enforcement existed (CIVEX-169) --
        used by `civex doctor`."""
        field_map = self._reference_field_map()
        if not field_map:
            return []
        all_records = self._records.list_all()
        existing_ids = {r.id for r in all_records}

        dangling: list[dict[str, Any]] = []
        for rec in all_records:
            for fid_str, (fname, dt) in field_map.items():
                val = rec.data.get(fid_str)
                if val is None:
                    continue
                targets = val if dt == "reference_list" else [val]
                if not isinstance(targets, list):
                    continue
                for t in targets:
                    try:
                        tid = uuid.UUID(str(t))
                    except ValueError:
                        continue
                    if tid not in existing_ids:
                        dangling.append(
                            {
                                "record_id": rec.id,
                                "schema_name": rec.schema_name,
                                "field_name": fname,
                                "dangling_target_id": tid,
                            }
                        )
        return dangling
