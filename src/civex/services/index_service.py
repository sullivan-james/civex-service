"""Which fields have an index in this computer's database: the one place that
decides, and keeps the database in step.

A field index (`domain/field_index.py`, built by `db/field_indexes.py`) makes
sorting by a field, and filtering it by a range or a value, fast at a million
records, and costs a little on every save of that kind of record. A field has
one when:

- it is part of a uniqueness key (`schemas.unique_keys`): every save of the
  kind looks its key up (`RecordRepository.find_key_match`), and
- a person asked for it (`set_indexed`; kept in `[db] indexed_fields` in the
  project's settings, by field id, through the config store).

Fields used by saved views are deliberately not indexed by themselves: a view
is shared with everyone and synced, while an index is this computer's, and
what it costs is paid on every save; a person sees what is slow here and
chooses. The choice is about this database only, so it is a setting (never in
a record, the history or a sync bundle) and survives a database move, which
also copies the indexes themselves.

`reconcile` builds what is wanted and missing and drops managed indexes nothing
wants (field or schema deleted, key removed, choice taken back), then refreshes
the planner's statistics, without which SQLite ignores a new index. It can be
slow on a big table, so it always runs in the background (`index_jobs`: the
server's thread, or a process of its own started by the CLI), never in a
request; until an index exists, lists are just as right, only slower.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from civex.config import ConfigStore
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.domain.field_index import (
    BULK_WRITE,
    INDEX_BUILT,
    IndexBuildYielded,
    IndexProgress,
    PERIODIC,
    CHOSEN,
    UNIQUE_KEY,
    FieldIndexReport,
    FieldIndexSpec,
    FieldIndexState,
    ReconcileResult,
    field_of,
    kind_of,
)
from civex.domain.dtos import FieldDTO, SchemaDTO
from civex.domain.permissions import EVERYTHING, Permissions
from civex.repositories.protocols import FieldIndexRepository

# On SQLite a build starts only after nobody has saved for this long.
QUIET_SECONDS = 5.0


class IndexService:
    def __init__(
        self,
        repo: FieldIndexRepository,
        schema_svc,  # SchemaService: the live schemas and their fields
        config_store: ConfigStore,
        permissions: Permissions = EVERYTHING,
    ) -> None:
        self._repo = repo
        self._schemas = schema_svc
        self._config_store = config_store
        self._permissions = permissions

    # -- what is wanted -------------------------------------------------------

    def _wanted(self) -> dict[uuid.UUID, tuple[SchemaDTO, FieldDTO, list[str]]]:
        chosen = set(self._config_store.load().db.indexed_fields)
        wanted: dict[uuid.UUID, tuple[SchemaDTO, FieldDTO, list[str]]] = {}
        for schema in self._schemas.list_all():
            in_keys = {fid for key in schema.unique_keys for fid in key}
            for f in schema.fields:
                if kind_of(f.dtype) is None:
                    continue
                reasons = []
                if str(f.id) in in_keys:
                    reasons.append(UNIQUE_KEY)
                if str(f.id) in chosen:
                    reasons.append(CHOSEN)
                if reasons:
                    wanted[f.id] = (schema, f, reasons)
        return wanted

    def specs(self) -> list[FieldIndexSpec]:
        """The indexes that should exist."""
        return [
            FieldIndexSpec(f.id, f.schema_id, kind_of(f.dtype) or "text")
            for _, f, _ in self._wanted().values()
        ]

    def status(self) -> FieldIndexReport:
        """Every wanted index, whether it is built, and the managed indexes
        nothing wants any more."""
        wanted = self._wanted()
        have = self._repo.existing()
        report = FieldIndexReport()
        for schema, f, reasons in wanted.values():
            state = FieldIndexState(
                field_id=f.id,
                field_name=f.name,
                schema_name=schema.name,
                reasons=reasons,
            )
            state.built = state.name in have
            report.fields.append(state)
        report.fields.sort(key=lambda s: (s.schema_name, s.field_name))
        report.stale = sorted(n for n in have if field_of(n) not in wanted)
        return report

    def field_status(self, schema_name: str, field_name: str) -> FieldIndexState:
        """One field: why it is indexed (no reasons: it isn't) and whether the
        index is built."""
        schema, f = self._field(schema_name, field_name)
        if f.schema_id != schema.id:  # reported on the schema that defines it
            schema = next(s for s in self._schemas.list_all() if s.id == f.schema_id)
        for state in self.status().fields:
            if state.field_id == f.id:
                return state
        return FieldIndexState(
            field_id=f.id,
            field_name=f.name,
            schema_name=schema.name,
            indexable=kind_of(f.dtype) is not None,
        )

    def _field(self, schema_name: str, field_name: str) -> tuple[SchemaDTO, FieldDTO]:
        schema = self._schemas.lookup(schema_name)
        # Inherited fields too, so asking for one says where it can be indexed.
        for resolved in self._schemas.collect_fields(schema):
            if resolved.field.name == field_name:
                return schema, resolved.field
        raise NotFoundError(f"Field '{field_name}' not found on '{schema.name}'")

    # -- choosing ---------------------------------------------------------------

    def set_indexed(
        self, schema_name: str, field_name: str, indexed: bool
    ) -> FieldIndexState:
        """Ask for (or stop asking for) an index on a field of the schema
        itself (an inherited field is indexed on the schema that defines it).
        Saves the choice only; `reconcile` builds or drops the index."""
        self._permissions.require("change_structure")
        schema, f = self._field(schema_name, field_name)
        if f.schema_id != schema.id:
            raise ValidationError(
                f"'{field_name}' is inherited: index it on the schema that defines it"
            )
        if indexed and kind_of(f.dtype) is None:
            raise ValidationError(
                f"A {f.dtype} field can't be indexed: only single values "
                "(numbers, text, dates, choices, yes/no, links to a record) can"
            )
        config = self._config_store.load()
        chosen = [x for x in config.db.indexed_fields if x != str(f.id)]
        if indexed:
            chosen.append(str(f.id))
        if chosen != config.db.indexed_fields:
            config.db.indexed_fields = chosen
            self._config_store.save(config)
        return self.field_status(schema.name, f.name)

    # -- keeping the database in step ---------------------------------------------

    def reconcile(
        self,
        progress: Callable[[IndexProgress], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> ReconcileResult:
        """Build every wanted index that is missing and drop every managed
        index nothing wants, then refresh the planner's statistics if anything
        was built. Each step is committed by itself (call with nothing
        pending). Slow on a big table, so it is always run in the background
        (`index_jobs`) or when a person asks in the foreground
        (`civex db indexes --reconcile`), never inside a request.

        On SQLite a build holds saves back, so each one waits for a moment
        when nobody has saved for `QUIET_SECONDS`, and gives way when a save
        comes along (`IndexBuildYielded`), to be started again once it is
        quiet. `should_stop` is asked while waiting: the result then says
        `stopped`."""
        started = time.monotonic()
        report = progress or (lambda p: None)
        stop = should_stop or (lambda: False)
        have = self._repo.existing()
        wanted = self._wanted()
        todo = sorted(
            (
                (schema, f)
                for schema, f, _ in wanted.values()
                if FieldIndexSpec(f.id, f.schema_id, "text").name not in have
            ),
            key=lambda sf: (sf[0].name, sf[1].name),
        )
        stale = sorted(n for n in have if field_of(n) not in wanted)
        result = ReconcileResult()
        with self._repo.upkeep():
            for name in stale:
                if not self._wait_turn(lambda: None, stop):
                    result.stopped = True
                    break
                self._repo.drop(name)
                result.dropped.append(name)
            for done, (schema, f) in enumerate(todo):
                if result.stopped:
                    break
                spec = FieldIndexSpec(f.id, f.schema_id, kind_of(f.dtype) or "text")

                def state(waiting: bool, _s=schema, _f=f, _d=done) -> IndexProgress:
                    return IndexProgress(
                        done=_d,
                        total=len(todo),
                        schema_label=_s.display_name,
                        field_label=_f.display_name,
                        waiting=waiting,
                        yielded=result.yielded,
                    )

                while True:
                    if not self._wait_turn(lambda: report(state(True)), stop):
                        result.stopped = True
                        break
                    report(state(False))
                    try:
                        self._repo.create(spec)
                    except IndexBuildYielded:
                        result.yielded += 1
                        continue
                    result.created.append(spec.name)
                    break
            if result.created:
                self._repo.refresh_statistics(INDEX_BUILT)
        if todo and not result.stopped:
            report(IndexProgress(done=len(todo), total=len(todo)))
        result.seconds = time.monotonic() - started
        return result

    def _wait_turn(self, waiting: Callable[[], None], stop: Callable[[], bool]) -> bool:
        """Wait until nobody has saved for `QUIET_SECONDS`; False if told to
        stop meanwhile."""
        while True:
            if stop():
                return False
            quiet = self._repo.quiet_for()
            if quiet >= QUIET_SECONDS:
                return True
            waiting()
            time.sleep(min(1.0, QUIET_SECONDS - quiet))

    def in_step(self) -> bool:
        """Whether the database has exactly the indexes wanted (cheap: the
        schemas and the database's list of indexes)."""
        return {s.name for s in self.specs()} == self._repo.existing()

    def after_bulk_write(self) -> None:
        """Refresh the planner's statistics after many records were written at
        once (an import), so a list of them is planned on today's numbers."""
        self._repo.refresh_statistics(BULK_WRITE)

    def refresh_statistics(self) -> None:
        """The periodic refresh (the server's `index_jobs`)."""
        self._repo.refresh_statistics(PERIODIC)
