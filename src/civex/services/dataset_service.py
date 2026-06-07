from __future__ import annotations

from civex.domain.dtos import DatasetDTO
from civex.domain.exceptions import AlreadyExistsError, NotFoundError
from civex.repositories.protocols import DatasetRepository


class DatasetService:
    def __init__(self, dataset_repo: DatasetRepository) -> None:
        self._datasets = dataset_repo

    def create(self, name: str, description: str | None = None) -> DatasetDTO:
        if self._datasets.get_by_name(name):
            raise AlreadyExistsError(f"Dataset '{name}' already exists")
        return self._datasets.create(name=name, description=description)

    def get(self, name: str) -> DatasetDTO:
        dto = self._datasets.get_by_name(name)
        if not dto:
            raise NotFoundError(f"Dataset '{name}' not found")
        return dto

    def list_all(self) -> list[DatasetDTO]:
        return self._datasets.list_all()

    def update(
        self,
        name: str,
        new_name: str | None = None,
        description: str | None = None,
    ) -> DatasetDTO:
        dataset = self.get(name)
        if new_name and new_name != name:
            if self._datasets.get_by_name(new_name):
                raise AlreadyExistsError(f"Dataset '{new_name}' already exists")
        return self._datasets.update(dataset.id, name=new_name, description=description)

    def delete(self, name: str) -> None:
        dataset = self.get(name)
        self._datasets.delete(dataset.id)
