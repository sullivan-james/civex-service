from __future__ import annotations

from abc import ABC, abstractmethod
import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from civex.domain.dtos import DatasetDTO, FileRef, RecordDTO, SchemaDTO
from civex.domain.exceptions import DuplicateRecordError
from civex.domain.file_refs import without_file_locations
from civex_plugin_sdk.plugin_base import PluginBase

if TYPE_CHECKING:
    from civex.context import AppContext


class PluginTier(str, Enum):
    """Which runtime executes a plugin. BUILTIN (in-process) and SUBPROCESS
    (uv-managed, CIVEX-127) are populated; CONTAINER is structurally
    reserved for a later story."""

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


class Tier0Plugin(PluginBase, ABC):
    """New-style in-process plugin contract that all built-in plugins
    implement. Shares its id/name/category/capabilities/Config declarations
    with civex-plugin-sdk's out-of-process `Plugin` (via the common
    `PluginBase`) so that shape can't drift between tiers -- only `invoke()`
    itself is declared separately per tier, since the in-process
    WorkflowContext and out-of-process Ctx deliberately expose different
    surfaces (WorkflowContext gives ambient `.record`/`.dataset` access that
    Ctx intentionally withholds from untrusted out-of-process code; several
    built-ins rely on that ambient access, e.g. get_field/save_field/
    extract_from_filename).

    Capability declarations are metadata only here — not enforced for tier
    BUILTIN, since capability allowlisting is an RPC-boundary control for
    untrusted out-of-process tiers, and there's no RPC call to intercept for
    in-process execution."""

    @abstractmethod
    def invoke(
        self,
        inputs: dict[str, Any],
        config: Any,
        ctx: "WorkflowContext",
    ) -> dict[str, Any]: ...


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

    record: RecordDTO
    dataset: DatasetDTO
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

    def __post_init__(self) -> None:
        # However the record was built, a workflow sees a file's identity, not
        # where it happens to be stored this moment (see without_file_locations).
        self.record = dataclasses.replace(
            self.record, data=without_file_locations(self.record.data)
        )

    def _note_affected(self, dto: RecordDTO, action: str) -> None:
        # Only the record's id and schema, never its name: a name is worked out
        # from the record when someone looks (`RecordService.labels`), so a
        # rename or a change of name template shows in old runs too, instead of
        # a copy taken now going stale in the run's history.
        for entry in self.affected_records:
            if entry["record_id"] == str(dto.id):
                entry["action"] = action
                return
        self.affected_records.append(
            {
                "record_id": str(dto.id),
                "schema_name": dto.schema_name,
                "action": action,
            }
        )

    def get_context_record(self) -> RecordDTO:
        return self.record

    def get_context_dataset(self) -> DatasetDTO:
        return self.dataset

    def get_file(self, sha256: str) -> bytes:
        return self._app_ctx.file_svc.retrieve(sha256)

    def store_file(self, data: bytes, filename: str) -> FileRef:
        return self._app_ctx.file_svc.store_bytes(data, filename, str(self.dataset.id))

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
        current = self._app_ctx.record_svc.get(record_id)
        existing = without_file_locations(current.data)
        if all(existing.get(k) == v for k, v in fields.items()):
            return current  # nothing to change: not touched, so not "affected"
        return self.update_record(record_id, {**existing, **fields})

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
                parent_record_id=context_record_id or str(self.record.id),
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
    ) -> list[RecordDTO]:
        return self._app_ctx.record_svc.find(
            dataset_name,
            schema_name=schema_name,
            parent_record_id=parent_record_id,
            filters=filters,
            search=search,
            limit=limit,
            offset=offset,
        )

    def delete_record(self, record_id: str) -> None:
        self._app_ctx.record_svc.delete(record_id)

    def get_schema(self, name: str) -> SchemaDTO:
        return self._app_ctx.schema_svc.get(name)

    def list_schemas(self) -> list[SchemaDTO]:
        return self._app_ctx.schema_svc.list_all()

    def get_collection(self, name: str) -> DatasetDTO:
        return self._app_ctx.dataset_svc.get(name)

    def list_collections(self) -> list[DatasetDTO]:
        return self._app_ctx.dataset_svc.list_all()

    def commit(self) -> None:
        self._app_ctx.commit()
