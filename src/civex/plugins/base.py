from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from civex.domain.dtos import DatasetDTO, FieldDTO, FileRef, RecordDTO, SchemaDTO
from civex.domain.exceptions import DuplicateRecordError, ValidationError
from civex.domain.file_refs import without_file_locations
from civex.workflows.progress import RUNS

if TYPE_CHECKING:
    from civex.context import AppContext


class PluginTier(str, Enum):
    """Which launcher runs a plugin (`civex.plugins.launchers`): BUILTIN in
    this process, SUBPROCESS by uv, CONTAINER by Docker. Shown to people;
    nothing branches on it."""

    BUILTIN = "builtin"
    SUBPROCESS = "subprocess"
    CONTAINER = "container"


@dataclass
class StepResult:
    """Uniform return shape for PluginRegistration.invoke(), regardless of
    tier. `logs`/`error` are unused by tier BUILTIN this story (exceptions
    still propagate and are logged by the executor exactly as before) — they
    exist so subprocess/container tiers have somewhere to put out-of-band
    log lines / structured RPC error envelopes without another interface
    change."""

    outputs: dict[str, Any] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    error: Any | None = None


@dataclass
class WorkflowContext:
    """Standard CRUD across the non-administrative data areas a plugin
    actually works with (records, files) plus read access to the structural
    ones a plugin needs to introspect (schemas, collections) — schema/
    collection *writes* stay out of this surface; changing the shape of the
    data model is an administrative action, not something a workflow step
    does.

    Every operation's *target* (the record/dataset/schema being read,
    updated, or deleted) is an explicit argument — none of them special-case
    "the record that triggered this workflow." `.record`/`.dataset` are
    still plain fields for in-process code that wants to read the trigger
    record directly (most built-ins do), but a plugin that wants to *write*
    to it goes through the same `update_record(record_id, data)` as it
    would for any other record — `get_context_record()`/
    `get_context_dataset()` are how it gets that id in the first place, and
    are the *only* way an out-of-process plugin (civex-plugin-sdk's `Ctx`,
    which deliberately has no `.record`/`.dataset` fields at all) can learn
    what triggered it.

    `create_record`'s `context_record_id` is the one deliberate exception:
    when omitted it defaults to the trigger record, because "usually a
    workflow is run from a particular record and creates children of it" is
    the overwhelmingly common case (4 of the 11 built-ins were each
    independently re-deriving this exact default before it lived here). It's
    deliberately *not* called `parent_record_id`, even though it's the value
    that ends up in `RecordDTO.parent_record_id` when the target schema
    declares one — not every create_record call creates a child record (a
    flat schema just ignores it), so the parameter is named for what it
    always is (a record providing default context) rather than what it
    sometimes becomes (a parent link). This is safe rather than magic --
    record_svc.add() already ignores `parent_record_id` entirely for a
    schema that doesn't declare a parent, so the default can never attach an
    unwanted relationship, only supply the one you'd almost always want when
    it's actually needed."""

    # None for work that is not for one record (a table brought in at the top of
    # a collection): `get_context_record`/`get_context_dataset` then say so.
    record: RecordDTO | None
    dataset: DatasetDTO | None
    _app_ctx: "AppContext"
    job_depth: int = 0
    # Which run this is, so a record it saves can say, on any run that save
    # triggers, which run and workflow started it.
    job_id: str | None = None
    workflow_name: str | None = None
    # Records this workflow run has created or updated so far, in touch
    # order -- the job's audit trail of what it did to the data (surfaced on
    # WorkflowJobDTO.affected_records). Keyed by record id so a record
    # touched more than once in one run (e.g. created, then corrected by a
    # later step) appears once, with its most recent action.
    affected_records: list[dict[str, Any]] = field(default_factory=list)
    # Writes the run attempted that a uniqueness policy refused, since the last
    # step finished (see take_duplicates). A step that skips such a row and
    # carries on would otherwise leave no trace of *which* record it collided
    # with; the executor adds these to that step's outputs.
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    # The run's folder (`executor.run` makes it and removes it when the run
    # ends): files a plugin asks for, and values too large to send inline, are
    # kept here for every step of the run.
    run_dir: Path | None = None
    _affected_at: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        # However the record was built, a workflow sees a file's identity, not
        # where it happens to be stored this moment (see without_file_locations).
        if self.record is not None:
            self.record = dataclasses.replace(
                self.record, data=without_file_locations(self.record.data)
            )

    def _note_affected(self, dto: RecordDTO, action: str) -> None:
        # Only the record's id and schema, never its name: a name is worked out
        # from the record when someone looks (`RecordService.labels`), so a
        # rename or a change of name template shows in old runs too, instead of
        # a copy taken now going stale in the run's history.
        # Found by record, not by walking the list: a run that saves tens of
        # thousands of records would otherwise spend its time here.
        at = self._affected_at.get(str(dto.id), -1)
        if 0 <= at < len(self.affected_records) and (
            self.affected_records[at]["record_id"] == str(dto.id)
        ):
            self.affected_records[at]["action"] = action
            return
        entry = {
            "record_id": str(dto.id),
            "schema_name": dto.schema_name,
            "action": action,
        }
        self._affected_at[str(dto.id)] = len(self.affected_records)
        self.affected_records.append(entry)

    def get_context_record(self) -> RecordDTO:
        if self.record is None:
            raise ValidationError("This work is not for one record.")
        return self.record

    def get_context_dataset(self) -> DatasetDTO:
        if self.dataset is None:
            raise ValidationError("This work is not for one collection.")
        return self.dataset

    def get_file(self, sha256: str) -> bytes:
        return self._app_ctx.file_svc.retrieve(sha256)

    def store_file(self, data: bytes, filename: str) -> FileRef:
        return self._app_ctx.file_svc.store_bytes(
            data, filename, str(self.get_context_dataset().id)
        )

    def store_path(self, path: Path, filename: str) -> FileRef:
        """Store the file at `path` (read in chunks, never whole) in the run's
        collection, named `filename`."""
        return self._app_ctx.file_svc.store(
            path, str(self.get_context_dataset().id), filename=filename
        )

    def store_folder(
        self, folder: str, pattern: str = "*", subfolders: bool = False
    ) -> dict[str, Any]:
        """Store the files of a folder on this computer in the run's collection,
        the host reading them from disk itself (nothing is uploaded). A file
        whose content is already stored is not copied again. Says how far it
        has got as it goes. Only where the host offers reading folders
        (`features.SERVER_PATH_IMPORT`: never on a hub). Returns
        `{"files": [FileRef dicts], "stored": n, "already_stored": n}`."""
        from civex.domain import features
        from civex.domain.exceptions import FeatureUnavailableError, ValidationError

        if not features.enabled(self._app_ctx.features, features.SERVER_PATH_IMPORT):
            raise FeatureUnavailableError(features.SERVER_PATH_IMPORT)
        root = Path(folder).expanduser()
        if not root.is_absolute() or not root.is_dir():
            raise ValidationError(f"'{folder}' is not a folder on this computer.")
        pattern = pattern or "*"
        if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise ValidationError("The file filter must stay inside the folder.")
        matches = root.rglob(pattern) if subfolders else root.glob(pattern)
        real_root = root.resolve()
        paths = sorted(
            p
            for p in matches
            if p.is_file()
            and p.resolve().is_relative_to(real_root)
            and not any(part.startswith(".") for part in p.relative_to(root).parts)
        )
        refs: list[dict[str, Any]] = []
        new = 0
        for number, path in enumerate(paths, start=1):
            self.progress(number - 1, len(paths), f"Reading {path.name}")
            ref, stored = self._app_ctx.file_svc.store_unless_stored(
                path, str(self.get_context_dataset().id)
            )
            refs.append(ref.to_dict())
            new += stored
        self.progress(len(paths), len(paths), "")
        return {"files": refs, "stored": new, "already_stored": len(refs) - new}

    def copy_file(self, sha256: str, dest: Path) -> None:
        """Write a stored file's bytes to `dest`, a chunk at a time."""
        with open(dest, "wb") as out:
            for chunk in self._app_ctx.file_svc.stream(sha256):
                out.write(chunk)

    @property
    def _cause(self) -> dict[str, Any] | None:
        if self.job_id is None:
            return None
        return {"job_id": self.job_id, "workflow": self.workflow_name}

    def _note_duplicate(self, e: DuplicateRecordError) -> None:
        self.duplicates.append(
            {
                "message": str(e),
                "fields": e.fields,
                "existing_record_id": e.existing_id,
                "existing_record": e.existing_name,
            }
        )

    def progress(
        self, done: float, total: float | None = None, message: str = ""
    ) -> None:
        """Say how far the step running now has got (the status bar shows it
        while the run lasts; `civex.workflows.progress`). A context with no
        run (`job_id` None) shows it nowhere."""
        if self.job_id is not None:
            RUNS.report(self.job_id, done, total, message)

    def take_duplicates(self) -> list[dict[str, Any]]:
        """The refused writes noted since the last call, clearing the list."""
        taken, self.duplicates = self.duplicates, []
        return taken

    def update_record(self, record_id: str, data: dict[str, Any]) -> RecordDTO:
        try:
            dto = self._app_ctx.record_svc.update(
                record_id, data, _job_depth=self.job_depth + 1, _cause=self._cause
            )
        except DuplicateRecordError as e:
            self._note_duplicate(e)
            raise
        self._note_affected(dto, "updated")
        return dto

    def patch_record(self, record_id: str, fields: dict[str, Any]) -> RecordDTO:
        """Change only `fields` on a record; every other field stays exactly as it
        is *now*.

        `update_record` replaces a record's whole data with what it is given, so
        a plugin that passes only the fields it knows about erases the rest (a
        table with a few columns would wipe the file and every computed value on
        the records it matches). Almost every plugin wants this instead: it reads
        the record fresh, so a change an earlier step made isn't undone by a stale
        copy, and it writes nothing at all when the fields already hold these
        values, so a run that changes nothing leaves no history and triggers
        nothing. An absent value is simply not in `fields`; it never clears
        anything.
        """
        current, data = self._app_ctx.record_svc.patched_data(record_id, fields)
        if data is None:
            return current  # nothing to change: not touched, so not "affected"
        return self.update_record(record_id, data)

    def create_record(
        self,
        dataset_name: str,
        schema_name: str,
        data: dict[str, Any],
        context_record_id: str | None = None,
    ) -> RecordDTO:
        try:
            dto = self._app_ctx.record_svc.add(
                dataset_name,
                schema_name,
                data,
                parent_record_id=context_record_id
                or (str(self.record.id) if self.record else None),
                _job_depth=self.job_depth + 1,
                _cause=self._cause,
            )
        except DuplicateRecordError as e:
            self._note_duplicate(e)
            raise
        self._note_affected(dto, "created")
        return dto

    def get_record(self, record_id: str) -> RecordDTO:
        return self._app_ctx.record_svc.get(record_id)

    def find_records(
        self,
        dataset_name: str,
        schema_name: str | None = None,
        parent_record_id: str | None = None,
        filters: list[str] | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
        filter_tree: dict[str, Any] | None = None,
    ) -> list[RecordDTO]:
        return self._app_ctx.record_svc.find(
            dataset_name,
            schema_name=schema_name,
            parent_record_id=parent_record_id,
            filters=filters,
            filter_tree=filter_tree,
            search=search,
            limit=limit,
            offset=offset,
        )

    def delete_record(self, record_id: str) -> None:
        dto = self._app_ctx.record_svc.get(record_id)
        self._app_ctx.record_svc.delete(record_id)
        self._note_affected(dto, "deleted")

    def get_schema(self, name: str) -> SchemaDTO:
        return self._app_ctx.schema_svc.get(name)

    def schema_fields(self, name: str) -> list[FieldDTO]:
        """The live fields of records of `name`: its own, then inherited."""
        svc = self._app_ctx.schema_svc
        return [rf.field for rf in svc.collect_fields(svc.get(name))]

    def list_schemas(self) -> list[SchemaDTO]:
        return self._app_ctx.schema_svc.list_all()

    def get_collection(self, name: str) -> DatasetDTO:
        return self._app_ctx.dataset_svc.get(name)

    def list_collections(self) -> list[DatasetDTO]:
        return self._app_ctx.dataset_svc.list_all()
