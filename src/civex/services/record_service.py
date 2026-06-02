from __future__ import annotations

from pathlib import Path
from typing import Any

from civex.domain.dtos import FileRef, RecordDTO, ResolvedField
from civex.domain.exceptions import CoercionError, NotFoundError, ValidationError
from civex.repositories.protocols import DatasetRepository, FileObjectStore, RecordRepository
from civex.services.schema_service import SchemaService

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
    ) -> None:
        self._schema_svc = schema_svc
        self._datasets = dataset_repo
        self._records = record_repo
        self._files = file_store

    def coerce_value(self, raw: str, dtype: str, field_name: str) -> Any:
        """
        Coerce a raw string input to the correct Python type.
        For 'file' dtype: treats raw as a filesystem path, stores the bytes
        in the file object store, and returns a FileRef dict.
        Raises CoercionError on failure.
        """
        if dtype == "file":
            path = Path(raw)
            if not path.exists():
                raise CoercionError(field_name, dtype, raw)
            file_ref = self._files.put(path.read_bytes(), path.name)
            return file_ref.to_dict()

        coerce = _COERCE.get(dtype)
        if coerce is None:
            raise CoercionError(field_name, dtype, raw)

        try:
            return coerce(raw)
        except (ValueError, TypeError):
            raise CoercionError(field_name, dtype, raw)

    def validate(self, data: dict[str, Any], fields: list[ResolvedField]) -> None:
        """Raise ValidationError if any required field is absent."""
        missing = [
            rf.field.name
            for rf in fields
            if rf.field.required and rf.field.name not in data
        ]
        if missing:
            raise ValidationError(f"Missing required fields: {', '.join(missing)}")

    def add(self, dataset_name: str, data: dict[str, Any]) -> RecordDTO:
        dataset = self._datasets.get_by_name(dataset_name)
        if not dataset:
            raise NotFoundError(f"Dataset '{dataset_name}' not found")

        schema = self._schema_svc.get(dataset.schema_name)
        fields = self._schema_svc.collect_fields(schema)
        self.validate(data, fields)

        return self._records.create(dataset_id=dataset.id, data=data)

    def get(self, record_id: str) -> RecordDTO:
        record = self._records.get_by_prefix(record_id)
        if not record:
            raise NotFoundError(f"Record '{record_id}' not found")
        return record

    def update(self, record_id: str, data: dict[str, Any]) -> RecordDTO:
        record = self.get(record_id)
        return self._records.update(id=record.id, data=data)

    def find(
        self,
        dataset_name: str,
        filters: list[str],
        limit: int = 50,
    ) -> list[RecordDTO]:
        """
        filters: list of "field=value" strings.
        All filters are AND'd. Filtering is done in Python against the JSON data.
        """
        dataset = self._datasets.get_by_name(dataset_name)
        if not dataset:
            raise NotFoundError(f"Dataset '{dataset_name}' not found")

        records = self._records.list_by_dataset(dataset.id)

        for condition in filters:
            if "=" not in condition:
                raise ValueError(f"Invalid filter '{condition}'. Use field=value.")
            key, _, value = condition.partition("=")
            records = [r for r in records if str(r.data.get(key, "")) == value]

        return records[:limit]

    def delete(self, record_id: str) -> None:
        record = self.get(record_id)
        self._records.delete(record.id)

    def get_resolved_fields(self, dataset_name: str) -> list[ResolvedField]:
        """Convenience: get the full field list for a dataset's schema."""
        dataset = self._datasets.get_by_name(dataset_name)
        if not dataset:
            raise NotFoundError(f"Dataset '{dataset_name}' not found")
        schema = self._schema_svc.get(dataset.schema_name)
        return self._schema_svc.collect_fields(schema)
