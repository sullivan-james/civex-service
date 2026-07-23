from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

from civex.domain.dtos import ErrorEnvelope
from civex.plugins.base import WorkflowContext
from civex.plugins.registry import PluginRegistration
from civex.workflows.conditions import (
    SKIPPED_OUTPUTS,
    condition_refs,
    evaluate_condition,
)
from civex.workflows.contract_validation import validate_workflow_contracts
from civex.workflows.definition import StepDef, WorkflowDef

log = logging.getLogger(__name__)


def topological_sort(
    steps: list[StepDef], virtual_ids: set[str] | None = None
) -> list[StepDef]:
    """Kahn's algorithm — returns steps in execution order.

    virtual_ids: step-like ids (e.g. "__input__") that may be referenced in inputs
                 but are not actual steps; they carry no deps and are never enqueued.

    Raises ValueError on an unresolvable step reference or a dependency cycle.
    Public (no leading underscore) so WorkflowService.validate() can reuse the
    same cycle check as a dry-run at save time (CIVEX-108), rather than only
    discovering a cycle when a trigger fires at run time.
    """
    ids = {s.id for s in steps}
    known_ids = ids | (virtual_ids or set())
    by_id = {s.id: s for s in steps}

    # Build: step_id → set of step_ids it depends on
    deps: dict[str, set[str]] = {s.id: set() for s in steps}
    for step in steps:
        for ref in step.inputs.values():
            source_id = ref.split(".")[0]
            if source_id not in known_ids:
                raise ValueError(
                    f"Step '{step.id}' references unknown step '{source_id}'"
                )
            if source_id in ids:  # virtual ids carry no real deps
                deps[step.id].add(source_id)
        if step.if_ is not None:
            for source_id, _ in condition_refs(step.if_):
                if source_id not in known_ids:
                    raise ValueError(
                        f"Step '{step.id}' 'if' references unknown step '{source_id}'"
                    )
                if source_id in ids:
                    deps[step.id].add(source_id)

    # Kahn's
    in_degree = {sid: len(d) for sid, d in deps.items()}
    queue = deque(sid for sid, d in in_degree.items() if d == 0)
    order: list[StepDef] = []

    while queue:
        sid = queue.popleft()
        order.append(by_id[sid])
        for other_id, other_deps in deps.items():
            if sid in other_deps:
                other_deps.discard(sid)
                in_degree[other_id] -= 1
                if in_degree[other_id] == 0:
                    queue.append(other_id)

    if len(order) != len(steps):
        raise ValueError("Workflow has a dependency cycle")
    return order


def _resolve_inputs(
    input_refs: dict[str, str],
    step_outputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    resolved = {}
    for input_name, ref in input_refs.items():
        parts = ref.split(".", 1)
        if len(parts) != 2:
            raise ValueError(f"Input reference '{ref}' must be 'step_id.output_name'")
        step_id, output_name = parts
        if step_id not in step_outputs:
            raise ValueError(f"Step '{step_id}' has not been executed yet")
        outputs = step_outputs[step_id]
        if output_name not in outputs:
            raise KeyError(f"Step '{step_id}' has no output '{output_name}'")
        resolved[input_name] = outputs[output_name]
    return resolved


def _validate_contracts(
    wf: WorkflowDef, plugins: dict[str, PluginRegistration]
) -> None:
    """Re-check the workflow against its plugins' declared contracts before
    running a single step (CIVEX-142).

    A workflow validated at save time can still be wrong by the time it runs:
    a plugin it uses may have been edited since, and an edited plugin is
    re-described on discovery. Failing here means failing before any step has
    written anything, with the same message the author would have seen at
    save time -- rather than part-way through, with whatever half-finished
    record writes that leaves behind.
    """
    errors = validate_workflow_contracts(wf, plugins)
    if errors:
        raise ValueError(
            "Workflow no longer matches its plugins' declared contracts:\n"
            + "\n".join(errors)
        )


def run(
    wf: WorkflowDef,
    ctx: WorkflowContext,
    plugins: dict[str, PluginRegistration],
    initial_outputs: dict[str, dict[str, Any]] | None = None,
    default_timeout_seconds: float = 60.0,
) -> None:
    log.info(wf)
    _validate_contracts(wf, plugins)
    virtual_ids = set(initial_outputs.keys()) if initial_outputs else None
    log.info("Virtual IDs: %s", virtual_ids)
    order = topological_sort(wf.steps, virtual_ids=virtual_ids)
    log.info("Execution order: %s", [s.id for s in order])
    step_outputs: dict[str, dict[str, Any]] = dict(initial_outputs or {})

    log.info(
        "▶ workflow '%s' | record %s | %d step(s)",
        wf.name,
        str(ctx.record.id)[:8],
        len(order),
    )
    wf_start = time.perf_counter()

    for step in order:
        registration = plugins.get(step.plugin)
        if registration is None:
            raise ValueError(f"Unknown plugin '{step.plugin}'")

        if step.if_ is not None and not evaluate_condition(step.if_, step_outputs):
            log.info("  [%s] ⏭ skipped ('if' was false)", step.id)
            step_outputs[step.id] = SKIPPED_OUTPUTS
            continue

        log.info("  [%s] → %s", step.id, step.plugin)
        t = time.perf_counter()
        config = registration.config_model(**step.config)
        inputs = _resolve_inputs(step.inputs, step_outputs)
        timeout = step.timeout if step.timeout is not None else default_timeout_seconds
        try:
            result = registration.invoke(inputs, config, ctx, timeout)
        except Exception as e:
            # Attach the step id and re-raise unchanged. The exception keeps
            # its own type and kind -- this is the one place that knows which
            # step was running, and a job error that doesn't name the failing
            # step is close to useless in a multi-step workflow (CIVEX-143).
            e.envelope = ErrorEnvelope.from_exception(e, step=step.id)  # type: ignore[attr-defined]
            log.error(
                "  [%s] ✗ %s (%s): %s",
                step.id,
                type(e).__name__,
                e.envelope.kind,  # type: ignore[attr-defined]
                e,
            )
            raise
        step_outputs[step.id] = result.outputs
        log.info("  [%s] ✓ %.3fs", step.id, time.perf_counter() - t)

    ctx.commit()
    log.info("✓ done (%.3fs total)", time.perf_counter() - wf_start)
