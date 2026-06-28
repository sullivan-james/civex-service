from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

from civex.plugins.base import BasePlugin, WorkflowContext
from civex.workflows.definition import StepDef, WorkflowDef

log = logging.getLogger(__name__)


def _topological_sort(steps: list[StepDef], virtual_ids: set[str] | None = None) -> list[StepDef]:
    """Kahn's algorithm — returns steps in execution order.

    virtual_ids: step-like ids (e.g. "__input__") that may be referenced in inputs
                 but are not actual steps; they carry no deps and are never enqueued.
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
                raise ValueError(f"Step '{step.id}' references unknown step '{source_id}'")
            if source_id in ids:  # virtual ids carry no real deps
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


def run(
    wf: WorkflowDef,
    ctx: WorkflowContext,
    plugins: dict[str, type[BasePlugin]],
    initial_outputs: dict[str, dict[str, Any]] | None = None,
) -> None:
    log.info(wf)
    virtual_ids = set(initial_outputs.keys()) if initial_outputs else None
    log.info("Virtual IDs: %s", virtual_ids)
    order = _topological_sort(wf.steps, virtual_ids=virtual_ids)
    log.info("Execution order: %s", [s.id for s in order])
    step_outputs: dict[str, dict[str, Any]] = dict(initial_outputs or {})

    log.info("▶ workflow '%s' | record %s | %d step(s)", wf.name, str(ctx.record.id)[:8], len(order))
    wf_start = time.perf_counter()

    for step in order:
        plugin_cls = plugins.get(step.plugin)
        if plugin_cls is None:
            raise ValueError(f"Unknown plugin '{step.plugin}'")

        log.info("  [%s] → %s", step.id, step.plugin)
        t = time.perf_counter()
        config = plugin_cls.Config(**step.config)
        inputs = _resolve_inputs(step.inputs, step_outputs)
        try:
            result = plugin_cls().run(inputs, config, ctx)
        except Exception as e:
            log.error("  [%s] ✗ %s: %s", step.id, type(e).__name__, e)
            raise
        step_outputs[step.id] = result or {}
        log.info("  [%s] ✓ %.3fs", step.id, time.perf_counter() - t)

    ctx.commit()
    log.info("✓ done (%.3fs total)", time.perf_counter() - wf_start)
