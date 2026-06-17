from __future__ import annotations

import dataclasses
import uuid
from pathlib import Path
from typing import Any

from civex.domain.dtos import RecordDTO, ResolvedField
from civex.domain.exceptions import CoercionError, NotFoundError, ValidationError
from civex.repositories.protocols import AuditRepository, DatasetRepository, FileObjectStore, RecordRepository
from civex.services.schema_service import SchemaService

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from civex.services.workflow_job_service import WorkflowJobService

_COERCE: dict[str, Any] = {
    "integer": int,
    "float": float,
    "string": str,
    "boolean": lambda v: v.strip().lower() in ("true", "yes", "1"),
}


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

    def _names_to_ids(self, data: dict[str, Any], schema_id: uuid.UUID) -> dict[str, Any]:
        schema = self._schema_svc._repo.get_by_id(schema_id)
        if schema is None:
            return data
        name_map = self._schema_svc.name_to_id_map(schema)
        return {name_map.get(k, k): v for k, v in data.items()}

    def _ids_to_names(self, data: dict[str, Any], schema_id: uuid.UUID) -> dict[str, Any]:
        schema = self._schema_svc._repo.get_by_id(schema_id)
        if schema is None:
            return data
        id_map = self._schema_svc.id_to_name_map(schema)
        return {id_map.get(k, k): v for k, v in data.items()}

    def _with_names(self, dto: RecordDTO) -> RecordDTO:
        return dataclasses.replace(dto, data=self._ids_to_names(dto.data, dto.schema_id))

    def coerce_value(self, raw: str, dtype: str, field_name: str, restrictions: dict[str, Any] | None = None) -> Any:
        if dtype == "file":
            path = Path(raw)
            if not path.exists():
                raise CoercionError(field_name, dtype, raw)
            file_ref = self._files.put(path.read_bytes(), path.name)
            return file_ref.to_dict()

        if dtype == "file_list":
            path = Path(raw)
            if not path.exists():
                raise CoercionError(field_name, dtype, raw)
            file_ref = self._files.put(path.read_bytes(), path.name)
            return [file_ref.to_dict()]

        if dtype == "reference":
            record = self._records.get_by_prefix(raw)
            if not record:
                raise CoercionError(field_name, dtype, raw, extra="record not found")
            target_schema = (restrictions or {}).get("schema")
            if target_schema and record.schema_name != target_schema:
                raise CoercionError(
                    field_name, dtype, raw,
                    extra=f"record has schema '{record.schema_name}', expected '{target_schema}'",
                )
            return str(record.id)

        coerce = _COERCE.get(dtype)
        if coerce is None:
            raise CoercionError(field_name, dtype, raw)
        try:
            return coerce(raw)
        except (ValueError, TypeError):
            raise CoercionError(field_name, dtype, raw)

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
            return [ResolvedField(field=f, source_schema_name=schema.name) for f in schema.fields]
        return self._schema_svc.collect_fields(schema)

    def add(
        self,
        dataset_name: str,
        schema_name: str,
        data: dict[str, Any],
        parent_record_id: str | None = None,
    ) -> RecordDTO:
        dataset = self._datasets.get_by_name(dataset_name)
        if not dataset:
            raise NotFoundError(f"Dataset '{dataset_name}' not found")

        schema = self._schema_svc.get(schema_name)

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
            expected_parent = self._schema_svc._repo.get_by_id(schema.parent_id)
            if parent_record.schema_id != schema.parent_id:
                raise ValidationError(
                    f"Parent record uses schema '{parent_record.schema_name}', "
                    f"expected '{expected_parent.name if expected_parent else schema.parent_id}'"
                )
            resolved_parent_id = parent_record.id
            own_fields = [ResolvedField(field=f, source_schema_name=schema.name) for f in schema.fields]
            self.validate(data, own_fields)
        else:
            self.validate(data, self._schema_svc.collect_fields(schema))

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
            self._job_svc.trigger_for_record(named, "record_created")
            if named.data:
                # Also fire record_updated so field-specific triggers (e.g. triggered on
                # a particular field being set) fire even when the record is first created.
                self._job_svc.trigger_for_record(named, "record_updated", changed_fields=set(named.data.keys()))
        return named

    def get(self, record_id: str) -> RecordDTO:
        record = self._records.get_by_prefix(record_id)
        if not record:
            raise NotFoundError(f"Record '{record_id}' not found")
        return self._with_names(record)

    def update(self, record_id: str, data: dict[str, Any]) -> RecordDTO:
        raw = self._records.get_by_prefix(record_id)
        if not raw:
            raise NotFoundError(f"Record '{record_id}' not found")
        old_data = self._ids_to_names(raw.data, raw.schema_id)
        id_data = self._names_to_ids(data, raw.schema_id)
        dto = self._records.update(id=raw.id, data=id_data)
        named = self._with_names(dto)
        if self._audit:
            old_named = dataclasses.replace(raw, data=old_data, schema_name=named.schema_name)
            self._audit.log_change("update", "record", raw.id, old_named.to_dict(), named.to_dict())
        if self._job_svc:
            changed = {k for k in set(old_data) | set(named.data) if old_data.get(k) != named.data.get(k)}
            self._job_svc.trigger_for_record(named, "record_updated", changed_fields=changed)
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

    def delete(self, record_id: str) -> None:
        record = self.get(record_id)
        if self._audit:
            self._audit.log_change("delete", "record", record.id, record.to_dict(), None)
        self._records.delete(record.id)
