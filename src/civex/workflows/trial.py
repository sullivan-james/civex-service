"""Trying a workflow on a record without keeping anything it does.

A trial runs the workflow exactly as a real run would (the same executor, the
same plugins, the same checks on every write), inside a SAVEPOINT that is
always rolled back (`AppContext.validation_scope`), and reports what the run
*would* have done: each record it created, changed or deleted with its fields
before and after, the runs its saves would have started, and the steps as a
run's page shows them. Nothing it writes stays: not the records, not their
history, not the runs its saves queue.

What a rollback can't take back: a plugin that reaches outside civex (sends a
request, writes a file of its own) does so for real, and the bytes of a file a
step stores stay in the object store with nothing pointing at them, for the
next clean-up to remove.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from civex.domain.dtos import ErrorEnvelope, RecordDTO
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.domain.file_refs import without_file_locations

if TYPE_CHECKING:
    from civex.context import AppContext
    from civex.workflows.definition import WorkflowDef

# How many pending runs are looked at to tell which ones the trial queued.
_PENDING_LOOKED_AT = 1000


@dataclass
class FieldChange:
    field: str
    label: str
    dtype: str | None
    before: Any
    after: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "label": self.label,
            "dtype": self.dtype,
            "before": self.before,
            "after": self.after,
        }


@dataclass
class RecordChange:
    """One record the trial touched: `action` is created, updated or deleted;
    `fields` only the values that differ (for a created record, those it set)."""

    record_id: str
    schema_name: str | None
    name: str | None
    action: str
    fields: list[FieldChange] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "schema_name": self.schema_name,
            "name": self.name,
            "action": self.action,
            "fields": [f.to_dict() for f in self.fields],
        }


@dataclass
class TrialResult:
    ok: bool
    steps: list[dict[str, Any]]
    changes: list[RecordChange]
    # {workflow: how many runs} the trial's saves would have queued.
    would_start: dict[str, int]
    error: dict[str, Any] | None = None
    log: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "steps": self.steps,
            "changes": [c.to_dict() for c in self.changes],
            "would_start": self.would_start,
            "error": self.error,
            "log": self.log,
        }


def try_workflow(
    ctx: AppContext,
    wf: WorkflowDef,
    record_id: str,
    input_data: dict[str, dict[str, Any]] | None = None,
) -> TrialResult:
    """Run `wf` on the record `record_id` and undo it, reporting what it did.

    Raises NotFoundError for no such record and ValidationError for a record
    the workflow isn't for (the same rule as a manual run). A workflow that
    fails part way is not an error here: the result says which step and why,
    with what the steps before it did."""
    from civex.plugins import registry as plugin_registry
    from civex.plugins.base import WorkflowContext
    from civex.workflows import executor
    from civex.workflows.logs import capture_output

    record = ctx.record_svc.get(record_id)
    if record.deleted_at is not None:
        raise ValidationError("That record is deleted, so a workflow can't run on it.")
    if wf.record_schema and record.schema_name != wf.record_schema:
        raise ValidationError(
            f"This workflow runs on {wf.record_schema} records; that one is a "
            f"{record.schema_name}."
        )
    dataset = ctx.dataset_svc._datasets.get_by_id(record.dataset_id)
    if dataset is None:
        raise NotFoundError("The record's collection was not found")

    steps: list[dict[str, Any]] = []
    error: dict[str, Any] | None = None
    after: dict[str, RecordDTO | None] = {}
    would_start: dict[str, int] = {}
    with capture_output() as log_buf:
        plugin_registry.discover_user_plugins(ctx.config.civex_dir / "plugins")
        plugins = plugin_registry.all_plugins()
        with ctx.validation_scope():
            pending_before = _pending_ids(ctx)
            wf_ctx = WorkflowContext(
                record=record,
                dataset=dataset,
                _app_ctx=ctx,
                workflow_name=wf.name,
            )
            try:
                steps = executor.run(
                    wf,
                    wf_ctx,
                    plugins,
                    initial_outputs=input_data or None,
                    default_timeout_seconds=ctx.config.plugins.default_timeout_seconds,
                )
            except Exception as e:
                steps = getattr(e, "step_executions", None) or []
                envelope = getattr(e, "envelope", None) or ErrorEnvelope.from_exception(
                    e
                )
                error = envelope.to_dict()
            touched = [a["record_id"] for a in wf_ctx.affected_records]
            for rid in touched:
                after[rid] = _live(ctx, rid)
            for job in ctx.job_svc.list_jobs(
                status="pending", limit=_PENDING_LOOKED_AT
            ):
                if job.id not in pending_before:
                    would_start[job.workflow_name] = (
                        would_start.get(job.workflow_name, 0) + 1
                    )
        # Rolled back: what is read now is how things were before the run.
        changes = [_change(ctx, rid, _live(ctx, rid), after[rid]) for rid in touched]
    return TrialResult(
        ok=error is None,
        steps=steps,
        changes=[c for c in changes if c is not None],
        would_start=would_start,
        error=error,
        log=log_buf.getvalue() or None,
    )


def _pending_ids(ctx: AppContext) -> set[Any]:
    return {
        job.id
        for job in ctx.job_svc.list_jobs(status="pending", limit=_PENDING_LOOKED_AT)
    }


def _live(ctx: AppContext, record_id: str) -> RecordDTO | None:
    try:
        record = ctx.record_svc.get(record_id)
    except NotFoundError:
        return None
    return None if record.deleted_at is not None else record


def _change(
    ctx: AppContext,
    record_id: str,
    before: RecordDTO | None,
    after: RecordDTO | None,
) -> RecordChange | None:
    if before is None and after is None:
        return None  # made and removed again within the run
    shown = after or before
    assert shown is not None
    action = "created" if before is None else "deleted" if after is None else "updated"
    old = without_file_locations(before.data) if before else {}
    new = without_file_locations(after.data) if after else {}
    fields: list[FieldChange] = []
    if action != "deleted":
        for name, label, dtype in _field_order(ctx, shown, old, new):
            o, n = old.get(name), new.get(name)
            if _same(o, n):
                continue
            fields.append(FieldChange(name, label, dtype, o, n))
        if action == "updated" and not fields:
            return None  # saved with the values it already had
    return RecordChange(
        record_id=record_id,
        schema_name=shown.schema_name,
        name=shown.natural_name,
        action=action,
        fields=fields,
    )


def _field_order(
    ctx: AppContext, record: RecordDTO, old: dict[str, Any], new: dict[str, Any]
) -> list[tuple[str, str, str | None]]:
    """(name, label, dtype) of every field either side has, in the schema's
    order, then any the schema doesn't know (as they are)."""
    out: list[tuple[str, str, str | None]] = []
    seen: set[str] = set()
    try:
        schema = ctx.schema_svc.get(record.schema_name) if record.schema_name else None
    except NotFoundError:
        schema = None
    if schema is not None:
        for rf in ctx.schema_svc.collect_fields(schema):
            f = rf.field
            if f.name in seen:
                continue
            seen.add(f.name)
            if f.name in old or f.name in new:
                out.append((f.name, f.display_name, f.dtype))
    for name in [*old, *new]:
        if name not in seen:
            seen.add(name)
            out.append((name, name, None))
    return out


_DERIVED = ("resolved_filename",)


def _same(a: Any, b: Any) -> bool:
    return _plain(a) == _plain(b)


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items() if k not in _DERIVED}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if value == "":
        return None
    return value
