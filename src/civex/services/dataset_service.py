from __future__ import annotations

from civex.domain.dtos import DatasetDTO
from civex.domain.exceptions import AlreadyExistsError, NotFoundError
from civex.repositories.protocols import DatasetRepository, SchemaRepository


class DatasetService:
    def __init__(self, schema_repo: SchemaRepository, dataset_repo: DatasetRepository) -> None:
        self._schemas = schema_repo
        self._datasets = dataset_repo

    def create(
        self,
        name: str,
        schema_name: str,
        description: str | None = None,
    ) -> DatasetDTO:
        schema = self._schemas.get_by_name(schema_name)
        if not schema:
            raise NotFoundError(f"Schema '{schema_name}' not found")

        if self._datasets.get_by_name(name):
            raise AlreadyExistsError(f"Dataset '{name}' already exists")

        return self._datasets.create(name=name, description=description, schema_id=schema.id)

    def get(self, name: str) -> DatasetDTO:
        dto = self._datasets.get_by_name(name)
        if not dto:
            raise NotFoundError(f"Dataset '{name}' not found")
        return dto

    def list_all(self) -> list[DatasetDTO]:
        return self._datasets.list_all()

    def delete(self, name: str) -> None:
        dataset = self.get(name)
        self._datasets.delete(dataset.id)
