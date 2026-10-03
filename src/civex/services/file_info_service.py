"""Where a file's content is stored and what uses it."""

from __future__ import annotations

from civex.domain.dtos import CollectionUse, FileInfo
from civex.domain.exceptions import NotFoundError
from civex.repositories.protocols import (
    DatasetRepository,
    FileObjectStore,
    FileReferenceRepository,
)


class FileInfoService:
    def __init__(
        self,
        store: FileObjectStore,
        refs: FileReferenceRepository,
        datasets: DatasetRepository,
    ) -> None:
        self._store = store
        self._refs = refs
        self._datasets = datasets

    def info(self, sha256: str) -> FileInfo:
        """Every place the content is, its size, and the records, collections
        and workflow runs that use it. Raises NotFoundError for content that is
        neither stored anywhere nor used by anything."""
        copies = self._store.copies_of(sha256)
        by_collection, jobs = self._refs.usage(sha256)
        if not copies and not by_collection and not jobs:
            raise NotFoundError(f"No file with hash {sha256} is stored or used.")

        collections = []
        for dataset_id, records in by_collection.items():
            dataset = (
                self._datasets.get_by_id(
                    dataset_id,
                    include_deleted=True,
                    with_count=False,
                    with_schemas=False,
                )
                if dataset_id is not None
                else None
            )
            collections.append(
                CollectionUse(
                    id=str(dataset_id) if dataset_id else "",
                    name=dataset.name if dataset else None,
                    records=records,
                )
            )
        collections.sort(key=lambda c: (c.name or "").casefold())
        return FileInfo(
            sha256=sha256,
            size=self._store.size_of(sha256),
            copies=copies,
            records=sum(by_collection.values()),
            jobs=jobs,
            collections=collections,
        )
