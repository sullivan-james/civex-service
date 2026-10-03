"""Where a file's content is stored and what uses it."""

from __future__ import annotations

from civex.domain.dtos import (
    CollectionStorage,
    CollectionUse,
    CollectionVolumeShare,
    FileInfo,
    VolumeSurplus,
)
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

    def surplus_by_volume(self) -> dict[str, VolumeSurplus]:
        """For each volume, how much of what it holds no collection uses: files
        nothing uses (reclaimable) and files kept only for workflow run history.
        Volumes that hold no such files are absent."""
        return {
            volume: VolumeSurplus(*counts)
            for volume, counts in self._refs.surplus_by_volume().items()
            if any(counts)
        }

    def collection_storage(self, collection_id: str) -> CollectionStorage:
        """Which volumes hold a collection's files, and how much each holds
        (largest first), read from the catalog. A volume that isn't reachable
        is still listed, with its state, since its files are still the
        collection's."""
        return self.all_collection_storage([collection_id])[collection_id]

    def all_collection_storage(
        self, collection_ids: list[str] | None = None
    ) -> dict[str, CollectionStorage]:
        """The same for several collections (all, if none are named), in a few
        queries. A collection with no files is still answered, with none."""
        found = self._refs.volume_breakdowns(collection_ids)
        status: dict[str, tuple[str, bool]] = {}  # a volume's state, asked once

        def state(volume: str) -> tuple[str, bool]:
            if volume not in status:
                s = self._store.volume_status(volume)
                status[volume] = (s.state, s.reachable)
            return status[volume]

        out = {}
        for cid in collection_ids if collection_ids is not None else list(found):
            total, rows = found.get(cid, (0, []))
            shares = [
                CollectionVolumeShare(
                    volume=volume,
                    files=files,
                    bytes=size,
                    shared_files=shared,
                    state=state(volume)[0],
                    available=state(volume)[1],
                )
                for volume, files, size, shared in sorted(rows, key=lambda r: -r[2])
            ]
            out[cid] = CollectionStorage(
                collection_id=cid,
                files=total,
                bytes=sum(s.bytes for s in shares),
                volumes=shares,
                unlocated_files=max(total - sum(s.files for s in shares), 0),
            )
        return out

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
