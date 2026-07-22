"""Validate a workflow's steps against the contracts their plugins declared
in `describe` (CIVEX-142).

Runs at save time (WorkflowService.validate) and again at run time
(executor.run) -- so a plugin whose contract changed after a workflow was
saved against it is caught lazily, on the next save or run of that workflow,
rather than needing a reverse index of "which workflows use plugin X".

Everything here works off PluginRegistration, which already carries the same
declarations for all three tiers, so none of these checks branch on tier.
What's checked:

  * the plugin exists at all
  * `config` against the plugin's declared JSON Schema, plus a rejection of
    keys the schema doesn't name (see _check_config)
  * `inputs` keys against declared input names -- unknown rejected, required
    ones must be present
  * every `<step>.<output>` reference resolves to a real upstream step (or a
    declared workflow input) *and* to an output that step's plugin actually
    declares -- including references inside `if:` (CIVEX-129)
  * step ids are unique

What isn't, and can't be: the *values* flowing between steps. A step's
inputs at run time are live Python objects (a DataFrame, raw bytes, FileRef
dicts); IOSpec.type describes the shape a workflow author wires together,
and nothing is ever validated against it.

A plugin that declares `inputs`/`outputs` as None (the PluginBase default,
meaning "no contract declared") opts out of the name checks in that
direction -- but never out of config validation, which every plugin has by
virtue of having a Config model. See civex_plugin_sdk.PluginBase.inputs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from jsonschema import Draft202012Validator

from civex.workflows.conditions import ConditionError, condition_refs

if TYPE_CHECKING:
    from civex.plugins.registry import PluginRegistration
    from civex.workflows.definition import StepDef, WorkflowDef

# The step-like id that manual-run inputs are exposed under; see
# executor.run()'s `initial_outputs`.
INPUT_STEP_ID = "__input__"


def validate_workflow_contracts(
    wf: "WorkflowDef", plugins: Mapping[str, "PluginRegistration"]
) -> list[str]:
    """Every contract violation in `wf`, as human-readable messages.

    Returns all of them rather than raising on the first: a workflow is
    typically saved by someone (or something -- the AI's save_workflow tool)
    that would otherwise have to fix one error, re-submit, and discover the
    next.
    """
    errors: list[str] = []
    errors.extend(_check_unique_step_ids(wf))

    steps_by_id = {step.id: step for step in wf.steps}
    workflow_input_names = set(wf.inputs or {})

    for step in wf.steps:
        registration = plugins.get(step.plugin)
        if registration is None:
            errors.append(f"Step '{step.id}' references unknown plugin '{step.plugin}'")
        else:
            errors.extend(_check_config(step, registration))
            errors.extend(_check_inputs(step, registration))
            errors.extend(
                _check_input_references(
                    step, plugins, steps_by_id, workflow_input_names
                )
            )
        errors.extend(
            _check_condition(step, plugins, steps_by_id, workflow_input_names)
        )

    return errors


def _check_unique_step_ids(wf: "WorkflowDef") -> list[str]:
    """Duplicate ids don't currently fail anywhere -- the executor's
    topological sort keys steps by id, so a duplicate silently drops a step
    rather than running it."""
    seen: set[str] = set()
    duplicates: list[str] = []
    for step in wf.steps:
        if step.id in seen and step.id not in duplicates:
            duplicates.append(step.id)
        seen.add(step.id)
    return [f"Step id '{sid}' is used more than once" for sid in duplicates]


def _check_config(step: "StepDef", registration: "PluginRegistration") -> list[str]:
    """Validate step.config against the plugin's declared config schema.

    Unknown keys are rejected on top of standard JSON Schema validation,
    which would otherwise accept them (Pydantic emits no
    `additionalProperties: false`, and JSON Schema's default is to allow
    extras). Catching a typo'd config key is most of the value of validating
    at all -- an ignored `fileds:` is exactly the failure that currently
    surfaces as a plugin doing nothing at run time. A plugin whose Config
    genuinely accepts arbitrary keys says so with `extra="allow"`, which
    emits `additionalProperties: true` and is honored here.
    """
    schema = registration.config_schema
    if schema is None:
        schema = registration.config_model.model_json_schema()

    errors = [
        f"Step '{step.id}' config: {_format_schema_error(e)}"
        for e in sorted(
            Draft202012Validator(schema).iter_errors(step.config),
            key=lambda e: list(e.path),
        )
    ]

    properties = schema.get("properties")
    if properties is not None and schema.get("additionalProperties") is not True:
        unknown = sorted(set(step.config) - set(properties))
        known = ", ".join(sorted(properties)) or "none"
        errors.extend(
            f"Step '{step.id}' config has unknown key '{key}' for plugin "
            f"'{step.plugin}' (accepts: {known})"
            for key in unknown
        )
    return errors


def _format_schema_error(error: Any) -> str:
    location = ".".join(str(part) for part in error.path)
    return f"{location}: {error.message}" if location else error.message


def _check_inputs(step: "StepDef", registration: "PluginRegistration") -> list[str]:
    if registration.inputs is None:
        return []  # plugin declares no input contract
    declared = {spec.name for spec in registration.inputs}
    required = {spec.name for spec in registration.inputs if spec.required}
    known = ", ".join(sorted(declared)) or "none"
    errors = [
        f"Step '{step.id}' supplies unknown input '{name}' to plugin "
        f"'{step.plugin}' (accepts: {known})"
        for name in sorted(set(step.inputs) - declared)
    ]
    errors.extend(
        f"Step '{step.id}' is missing required input '{name}' for plugin "
        f"'{step.plugin}'"
        for name in sorted(required - set(step.inputs))
    )
    return errors


def _check_input_references(
    step: "StepDef",
    plugins: Mapping[str, "PluginRegistration"],
    steps_by_id: Mapping[str, "StepDef"],
    workflow_input_names: set[str],
) -> list[str]:
    errors: list[str] = []
    for input_name, ref in step.inputs.items():
        source, _, output_name = ref.partition(".")
        if not output_name:
            errors.append(
                f"Step '{step.id}' input '{input_name}' must reference "
                f"'step_id.output_name', got '{ref}'"
            )
            continue

        if source == INPUT_STEP_ID:
            if output_name not in workflow_input_names:
                known = ", ".join(sorted(workflow_input_names)) or "none declared"
                errors.append(
                    f"Step '{step.id}' input '{input_name}' references "
                    f"'{ref}', but the workflow declares no input "
                    f"'{output_name}' (has: {known})"
                )
            continue

        source_step = steps_by_id.get(source)
        if source_step is None:
            errors.append(
                f"Step '{step.id}' input '{input_name}' references unknown "
                f"step '{source}'"
            )
            continue

        # Whether the upstream step actually produces that output. Skipped
        # when its plugin is unknown (already reported against the step that
        # names it) or declares no output contract -- there's nothing to
        # check against.
        source_registration = plugins.get(source_step.plugin)
        if source_registration is None or source_registration.outputs is None:
            continue
        declared = {spec.name for spec in source_registration.outputs}
        if output_name not in declared:
            known = ", ".join(sorted(declared)) or "none"
            errors.append(
                f"Step '{step.id}' input '{input_name}' references "
                f"'{ref}', but step '{source}' ({source_step.plugin}) "
                f"produces no output '{output_name}' (produces: {known})"
            )
    return errors


def _check_condition(
    step: "StepDef",
    plugins: Mapping[str, "PluginRegistration"],
    steps_by_id: Mapping[str, "StepDef"],
    workflow_input_names: set[str],
) -> list[str]:
    """Same reference checks as `_check_input_references`, applied to
    `if:` -- an `if:` typo should fail at save time rather than surface as
    a run-time "step has not run yet" the first time that branch is hit."""
    if step.if_ is None:
        return []

    try:
        refs = condition_refs(step.if_)
    except ConditionError as e:
        return [f"Step '{step.id}' 'if': {e}"]

    errors: list[str] = []
    for source, output_name in refs:
        if source == INPUT_STEP_ID:
            if output_name not in workflow_input_names:
                known = ", ".join(sorted(workflow_input_names)) or "none declared"
                errors.append(
                    f"Step '{step.id}' 'if' references '{source}.{output_name}', "
                    f"but the workflow declares no input '{output_name}' "
                    f"(has: {known})"
                )
            continue

        source_step = steps_by_id.get(source)
        if source_step is None:
            errors.append(f"Step '{step.id}' 'if' references unknown step '{source}'")
            continue

        source_registration = plugins.get(source_step.plugin)
        if source_registration is None or source_registration.outputs is None:
            continue
        declared = {spec.name for spec in source_registration.outputs}
        if output_name not in declared:
            known = ", ".join(sorted(declared)) or "none"
            errors.append(
                f"Step '{step.id}' 'if' references '{source}.{output_name}', "
                f"but step '{source}' ({source_step.plugin}) produces no "
                f"output '{output_name}' (produces: {known})"
            )
    return errors
